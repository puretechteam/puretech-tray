# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""The tray icon: a hidden window on its own thread, Shell_NotifyIconW (NOTIFYICON_VERSION_4), a native popup menu,
toasts with a balloon fallback."""

import ctypes
import threading
from collections import deque
from ctypes import byref

from . import _win32 as W
from .icon import as_rgba, make_hicon, prepare
from .menu import Menu, call_with, find_default, resolve, walk

class _Log:
    """logging, imported only when something needs reporting (keeps import time down)."""
    def __getattr__(self, name):
        import logging
        return getattr(logging.getLogger("puretech_tray"), name)

log = _Log()

_WM_TRAY = W.WM_APP + 1        # Shell_NotifyIcon callback
_WM_CALL = W.WM_APP + 2        # run queued callables on the tray thread
_WM_STOP = W.WM_APP + 3
_WM_REFRESH = W.WM_APP + 4
_ICON_ID = 1
_RETRY_TIMER = 1
_RETRIES = 60                  # NIM_ADD retries, one per second, while Explorer is not up yet (logon autostart)
_NOTIFY_WAIT = 10              # seconds notify() waits for a busy tray thread before returning "queued"


def _signed16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Tray:
    """A notification-area icon.

    Tray(icon, tooltip="", menu=None, on_click=None, app_id=None, *, app_name=None, app_icon=None,
         app_shortcut=True, theme="auto")

    - `icon`: RGBA bytes with a size, or an object with .tobytes()/.size (e.g. a Pillow image).
    - `menu`: a Menu (or list of Items). Opened by right click; evaluated fresh every time it opens.
    - `on_click`: left click. Without it, a left click runs the menu's default item, or opens the menu.
    - `app_id`: an AppUserModelID such as "PureTech.FrameKeep". Needed for real toasts; without it notify() uses
      a balloon. On the first toast the id is registered for the current user (HKCU) with `app_name` and
      `app_icon` (a path), and, unless `app_shortcut=False`, a Start menu shortcut named `app_name` that carries
      the id and starts the running app: Windows 11 only shows toasts for ids such a shortcut carries.
    - `theme`: "auto" follows Windows dark/light mode for menus, "dark" or "light" force one, None leaves menus as
      they are. The setting is process-wide (it is how Windows themes popup menus).
    """

    def __init__(self, icon, tooltip="", menu=None, on_click=None, app_id=None, *, app_name=None, app_icon=None,
                 app_shortcut=True, theme="auto"):
        as_rgba(icon)                                  # fail fast on a bad icon
        self._icon, self._tooltip = icon, str(tooltip or "")
        self.menu = menu if isinstance(menu, Menu) or menu is None else Menu(*menu)
        self.on_click, self.app_id, self.app_name, self.app_icon, self.theme = on_click, app_id, app_name, app_icon, theme
        self.app_shortcut = app_shortcut
        self._lock = threading.RLock()
        self._queue = deque()
        self._ready = threading.Event()
        self._thread = None
        self._thread_id = None
        self._hwnd = None
        self._hicon = None
        self._balloon_icon = None
        self._balloon_click = None
        self._added = False
        self._retries = 0
        self._size = 16
        self._error = None
        self._open = None            # (hmenu, entries, slots) while the popup menu is showing
        self._toaster = None
        self._app_state = None       # None, "registering", "ready" or "failed": toast registration, done lazily
        self._app_waiting = []       # notifications queued while the app id is being registered
        self._dark = None
        self._last_key = 0
        self._taskbar_created = -1   # registered once the window exists; creation messages arrive before that

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    def start(self):
        """Run the tray on its own daemon thread and return once the icon is set up."""
        if self._thread and self._thread.is_alive():
            return self
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._loop, name="puretech-tray", daemon=True)
        self._thread.start()
        self._ready.wait(10)
        if self._error:
            raise self._error
        return self

    def run(self):
        """Run the tray on the calling thread until stop()."""
        self._loop()
        if self._error:
            raise self._error

    def stop(self):
        """Remove the icon and end the tray thread. Safe to call from any thread, including tray callbacks."""
        hwnd = self._hwnd
        if not hwnd:
            return
        if threading.get_ident() == self._thread_id:
            W.DestroyWindow(hwnd)
            return
        W.PostMessageW(hwnd, _WM_STOP, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(5)

    @property
    def running(self):
        return self._hwnd is not None

    @property
    def visible(self):
        """True while the icon is in the notification area."""
        return self._added

    @property
    def hwnd(self):
        return self._hwnd

    def icon_rect(self):
        """Screen rectangle (left, top, right, bottom) of the icon, or None. Useful to place a popup near it."""
        if not self._hwnd:
            return None
        ident = W.NOTIFYICONIDENTIFIER(ctypes.sizeof(W.NOTIFYICONIDENTIFIER), self._hwnd, _ICON_ID)
        rect = W.wintypes.RECT()
        if W.Shell_NotifyIconGetRect(byref(ident), byref(rect)) != 0:
            return None
        return rect.left, rect.top, rect.right, rect.bottom

    # ---- live updates ------------------------------------------------------------------------------------------
    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value):
        self.update(icon=value)

    @property
    def tooltip(self):
        return self._tooltip

    @tooltip.setter
    def tooltip(self, value):
        self.update(tooltip=value)

    def update(self, icon=None, tooltip=None):
        """Change the icon and/or tooltip. Callable from any thread; returns once the shell has the change."""
        if icon is not None:
            as_rgba(icon)
        with self._lock:
            if icon is not None:
                self._icon = icon
            if tooltip is not None:
                self._tooltip = str(tooltip)
            if not (self._hwnd and self._added):
                if icon is not None and self._hicon:      # rebuilt from the new icon when it is added (again)
                    W.DestroyIcon(self._hicon)
                    self._hicon = None
                return
            flags = (W.NIF_ICON if icon is not None else 0) | (W.NIF_TIP | W.NIF_SHOWTIP if tooltip is not None else 0)
            if flags:
                self._modify(flags, new_icon=icon is not None)

    def refresh_menu(self):
        """Re-evaluate the menu. Menus are rebuilt on every open anyway; this updates one that is open right now
        (in place, when its structure is unchanged)."""
        if self._hwnd:
            W.PostMessageW(self._hwnd, _WM_REFRESH, 0, 0)

    # ---- notifications -----------------------------------------------------------------------------------------
    def notify(self, title, text="", actions=(), on_click=None, *, silent=False, prefer="toast"):
        """Show a notification and return how: "toast" or "balloon".

        `actions` is a list of (label, fn) buttons (toasts only, up to five); `on_click` runs when the body is
        clicked. Callbacks run on the tray thread while the app runs. A balloon has no buttons: its click runs
        `on_click`, or the first action. Returns "queued" instead of raising if the tray thread is busy (a menu
        action still running) for more than 10 seconds; the notification is shown when it is free."""
        if not self._hwnd:
            raise RuntimeError("tray is not running")
        try:
            return self._call_sync(lambda: self._notify(title, text, list(actions or ()), on_click, silent, prefer),
                                   _NOTIFY_WAIT)
        except TimeoutError:
            log.warning("tray thread busy; notification queued")
            return "queued"

    def _notify(self, title, text, actions, on_click, silent, prefer):
        if prefer == "toast" and self.app_id:
            if self._app_state is None:
                self._app_state = "ready" if self._app_id_ready() else "registering"
                if self._app_state == "registering":   # first run: COM, a new shortcut, ~2.5 s of indexing
                    threading.Thread(target=self._register_app, name="puretech-tray-register", daemon=True).start()
            if self._app_state == "registering":
                self._app_waiting.append((title, text, actions, on_click, silent))
                return "toast"
            if self._app_state == "ready":
                try:
                    if self._toaster is None:
                        from .toast import Toaster
                        self._toaster = Toaster(self.app_id, self._post, self._toast_failed, self._toaster_idle)
                    self._toaster.show(title, text, actions, on_click, silent=silent)
                    return "toast"
                except OSError as e:
                    log.warning("toast unavailable, using a balloon: %s", e)
                    self._toaster_idle()        # e.g. notifications switched off: do not keep WinRT loaded
        self._balloon(title, text, on_click or (actions[0][1] if actions else None), silent)
        return "balloon"

    def _app_args(self):
        return (self.app_id, self.app_name or self._tooltip or self.app_id, self.app_icon), \
            {"shortcut": self.app_shortcut}

    def _app_id_ready(self):
        """The registry-and-stat check (no COM, no thread) that keeps an already-registered app cheap."""
        from .toast import app_id_ready
        args, kwargs = self._app_args()
        try:
            return app_id_ready(*args, **kwargs)
        except (OSError, ValueError):
            return False

    def _register_app(self):
        """First-time registration, off the tray thread. Queued notifications are shown once it is done."""
        try:
            from .toast import register_app_id
            args, kwargs = self._app_args()
            register_app_id(*args, **kwargs)
            state = "ready"
        except Exception as e:
            log.warning("could not register %s for toasts, using balloons: %s", self.app_id, e)
            state = "failed"

        def done():
            self._app_state = state
            waiting, self._app_waiting = self._app_waiting, []
            for item in waiting:
                self._notify(*item, "toast")
        self._post(done)

    def _toaster_idle(self):
        """No toast can be clicked any more: release WinRT so Windows can unload it (measured: about 6 MB of
        working set back after a toast). The next notify() opens it again."""
        toaster = self._toaster
        if toaster is not None and not toaster.live:
            self._toaster = None
            toaster.close()

    def _toast_failed(self, title, text, click, code):
        log.warning("toast failed (0x%08X), using a balloon", code & 0xFFFFFFFF)
        self._balloon(title, text, click, False)

    def _balloon(self, title, text, click, silent):
        with self._lock:
            size = W.icon_size(self._hwnd, large=True)
            old = self._balloon_icon
            self._balloon_icon = make_hicon(prepare(self._icon, size), size, size)
            nid = self._nid(W.NIF_INFO)
            nid.szInfoTitle = str(title)[:63]
            nid.szInfo = (str(text) or " ")[:255]
            nid.dwInfoFlags = W.NIIF_USER | W.NIIF_LARGE_ICON | W.NIIF_RESPECT_QUIET_TIME | (W.NIIF_NOSOUND if silent else 0)
            nid.hBalloonIcon = self._balloon_icon
            self._balloon_click = click
            W.Shell_NotifyIconW(W.NIM_MODIFY, byref(nid))
            if old:
                W.DestroyIcon(old)

    # ---- thread plumbing ---------------------------------------------------------------------------------------
    def _post(self, fn):
        self._queue.append(fn)
        if self._hwnd:
            W.PostMessageW(self._hwnd, _WM_CALL, 0, 0)

    def _call_sync(self, fn, timeout=10):
        if threading.get_ident() == self._thread_id:
            return fn()
        box, done = [], threading.Event()

        def wrapper():
            try:
                box.append((True, fn()))
            except BaseException as e:
                box.append((False, e))
            finally:
                done.set()
        self._post(wrapper)
        if not done.wait(timeout):
            raise TimeoutError("tray thread did not respond")
        ok, value = box[0]
        if not ok:
            raise value
        return value

    def _run(self, fn, *args):
        try:
            call_with(fn, *args)
        except Exception:
            log.exception("tray callback failed")

    # ---- the window thread -------------------------------------------------------------------------------------
    def _loop(self):
        self._thread_id = threading.get_ident()
        cls = f"PureTechTray{id(self):x}"
        hinst = W.GetModuleHandleW(None)
        self._wndproc = W.WNDPROC(self._proc)
        try:
            if W.SetThreadDpiAwarenessContext:                # crisp icons and menus on high-DPI screens
                W.SetThreadDpiAwarenessContext(W.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            wc = W.WNDCLASSEXW(cbSize=ctypes.sizeof(W.WNDCLASSEXW), lpfnWndProc=self._wndproc, hInstance=hinst,
                               lpszClassName=cls)
            if not W.RegisterClassExW(byref(wc)):
                raise OSError(ctypes.get_last_error(), "RegisterClassExW failed")
            # A hidden top-level window, not a message-only one: only top-level windows receive the TaskbarCreated
            # broadcast, and TrackPopupMenu needs a window that can take the foreground.
            hwnd = W.CreateWindowExW(0, cls, cls, W.WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None)
            if not hwnd:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")
            self._hwnd = hwnd
            self._taskbar_created = W.RegisterWindowMessageW("TaskbarCreated")
            W.ChangeWindowMessageFilterEx(hwnd, self._taskbar_created, W.MSGFLT_ALLOW, None)
            if self.theme:
                self._dark = W.DarkMenus()
                self._dark.apply(hwnd, self.theme)
            self._size = W.icon_size(hwnd)
            self._add_icon()
        except Exception as e:
            self._error = e
            self._cleanup(cls, hinst)
            self._ready.set()
            return
        self._ready.set()
        msg = W.MSG()
        while W.GetMessageW(byref(msg), None, 0, 0) > 0:
            W.TranslateMessage(byref(msg))
            W.DispatchMessageW(byref(msg))
        self._cleanup(cls, hinst)

    def _cleanup(self, cls, hinst):
        with self._lock:
            if self._toaster is not None:
                try:
                    self._toaster.close()
                except Exception:
                    log.exception("closing toasts failed")
                self._toaster = None
            if self._hwnd:
                if self._added:
                    W.Shell_NotifyIconW(W.NIM_DELETE, byref(self._nid(0)))
                W.DestroyWindow(self._hwnd)
            for h in (self._hicon, self._balloon_icon):
                if h:
                    W.DestroyIcon(h)
            self._hicon = self._balloon_icon = None
            self._hwnd, self._added = None, False
        W.UnregisterClassW(cls, hinst)
        self._thread_id = None

    def _nid(self, flags):
        nid = W.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(W.NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags = self._hwnd, _ICON_ID, flags
        return nid

    def _add_icon(self):
        with self._lock:
            nid = self._nid(W.NIF_MESSAGE | W.NIF_ICON | W.NIF_TIP | W.NIF_SHOWTIP)
            nid.uCallbackMessage = _WM_TRAY
            if not self._hicon:
                self._hicon = make_hicon(prepare(self._icon, self._size), self._size, self._size)
            nid.hIcon = self._hicon
            nid.szTip = self._tooltip[:127]
            if not W.Shell_NotifyIconW(W.NIM_ADD, byref(nid)):
                if self._retries < _RETRIES:                    # Explorer not ready yet: try again shortly
                    self._retries += 1
                    W.SetTimer(self._hwnd, _RETRY_TIMER, 1000, None)
                    return False
                raise OSError("Shell_NotifyIconW(NIM_ADD) failed")
            self._retries = 0
            nid.uVersion = W.NOTIFYICON_VERSION_4
            W.Shell_NotifyIconW(W.NIM_SETVERSION, byref(nid))
            self._added = True
            return True

    def _modify(self, flags, new_icon=False):
        nid = self._nid(flags)
        old = None
        if new_icon:
            old, self._hicon = self._hicon, make_hicon(prepare(self._icon, self._size), self._size, self._size)
        nid.hIcon = self._hicon
        nid.szTip = self._tooltip[:127]
        W.Shell_NotifyIconW(W.NIM_MODIFY, byref(nid))
        if old:
            W.DestroyIcon(old)

    def _check_size(self):
        size = W.icon_size(self._hwnd)
        with self._lock:
            if size != self._size:
                self._size = size
                if self._added:
                    self._modify(W.NIF_ICON, new_icon=True)

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == _WM_TRAY:
                self._on_tray(_signed16(lparam), _signed16(wparam), _signed16(wparam >> 16))
                return 0
            if msg == _WM_CALL:
                while self._queue:
                    self._run(self._queue.popleft())
                return 0
            if msg == _WM_REFRESH:
                self._refresh_open_menu()
                return 0
            if msg == _WM_STOP:
                W.DestroyWindow(hwnd)
                return 0
            if msg == W.WM_DESTROY:
                with self._lock:
                    if self._added:
                        W.Shell_NotifyIconW(W.NIM_DELETE, byref(self._nid(0)))
                        self._added = False
                W.PostQuitMessage(0)
                return 0
            if msg == self._taskbar_created:                    # Explorer restarted: the icon is gone, add it back
                with self._lock:
                    self._added = False
                    W.Shell_NotifyIconW(W.NIM_DELETE, byref(self._nid(0)))
                    self._size = W.icon_size(hwnd)
                    if self._hicon:
                        W.DestroyIcon(self._hicon)
                        self._hicon = None
                    self._add_icon()
                return 0
            if msg == W.WM_TIMER and wparam == _RETRY_TIMER:
                W.KillTimer(hwnd, _RETRY_TIMER)
                if not self._added:
                    self._add_icon()
                return 0
            if msg == W.WM_SETTINGCHANGE:
                if lparam and ctypes.wstring_at(lparam) == "ImmersiveColorSet" and self._dark:
                    self._dark.refresh()
                self._check_size()
            elif msg in (W.WM_DISPLAYCHANGE, W.WM_DPICHANGED):
                self._check_size()
        except Exception:
            log.exception("tray window procedure failed")
        return W.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---- clicks and the menu -----------------------------------------------------------------------------------
    def _on_tray(self, event, x, y):
        if event == W.NIN_KEYSELECT:                    # Enter sends NIN_KEYSELECT twice; keep the first
            now = W.GetMessageTime()
            if 0 <= now - self._last_key < 300:
                return
            self._last_key = now
        if event in (W.NIN_SELECT, W.NIN_KEYSELECT):
            if self.on_click is not None:
                self._run(self.on_click, self)
                return
            entries = self._resolve()
            target = find_default(entries) if entries is not None else None
            if target is not None:
                if target.item.action:
                    self._run(target.item.action, self, target.item)
            else:
                self._show_menu(x, y, entries)
        elif event == W.WM_CONTEXTMENU:
            self._show_menu(x, y)
        elif event == W.NIN_BALLOONUSERCLICK:
            click, self._balloon_click = self._balloon_click, None
            if click is not None:
                self._run(click, self)

    def _resolve(self):
        if self.menu is None:
            return None
        try:
            return resolve(self.menu)
        except Exception:
            log.exception("evaluating the tray menu failed")
            return None

    def _show_menu(self, x, y, entries=None):
        entries = entries if entries is not None else self._resolve()
        if not entries:
            return
        slots = []
        hmenu = self._build(entries, slots)
        self._open = (hmenu, entries, slots)
        try:
            if x == 0 and y == 0:
                pt = W.wintypes.POINT()
                W.GetCursorPos(byref(pt))
                x, y = pt.x, pt.y
            W.SetForegroundWindow(self._hwnd)
            align = W.TPM_RIGHTALIGN if W.GetSystemMetrics(W.SM_MENUDROPALIGNMENT) else W.TPM_LEFTALIGN
            cmd = W.TrackPopupMenuEx(hmenu, align | W.TPM_BOTTOMALIGN | W.TPM_RIGHTBUTTON | W.TPM_RETURNCMD |
                                     W.TPM_NONOTIFY, x, y, self._hwnd, None)
            W.PostMessageW(self._hwnd, W.WM_NULL, 0, 0)
            entries = self._open[1]
        finally:
            self._open = None
            W.DestroyMenu(hmenu)
        if cmd:
            for e in walk(entries):
                if e.id == cmd and e.children is None and not e.separator:
                    if e.item.action:
                        self._run(e.item.action, self, e.item)
                    break

    def _menu_info(self, e, with_id=True):
        mii = W.MENUITEMINFOW()
        mii.cbSize = ctypes.sizeof(W.MENUITEMINFOW)
        if e.separator:
            mii.fMask, mii.fType = W.MIIM_FTYPE, W.MFT_SEPARATOR
            return mii, None
        text = ctypes.create_unicode_buffer(e.text)
        mii.fMask = W.MIIM_FTYPE | W.MIIM_STATE | W.MIIM_STRING | (W.MIIM_ID if with_id else 0)
        mii.fType = W.MFT_STRING | (W.MFT_RADIOCHECK if e.radio else 0)
        enabled = e.enabled and (e.children is None or bool(e.children))
        mii.fState = ((W.MFS_CHECKED if e.checked else 0) | (0 if enabled else W.MFS_DISABLED) |
                      (W.MFS_DEFAULT if e.default else 0))
        mii.wID = e.id
        mii.dwTypeData = ctypes.cast(text, W.wintypes.LPWSTR)
        mii.cch = len(e.text)
        return mii, text

    def _build(self, entries, slots):
        hmenu = W.CreatePopupMenu()
        for pos, e in enumerate(entries):
            mii, _text = self._menu_info(e)
            if e.children is not None:
                mii.fMask |= W.MIIM_SUBMENU
                mii.hSubMenu = self._build_children(e, slots, hmenu, pos)
            else:
                slots.append((hmenu, pos))
            W.InsertMenuItemW(hmenu, pos, True, byref(mii))
        return hmenu

    def _build_children(self, e, slots, parent, pos):
        slots.append((parent, pos))
        return self._build(e.children, slots)

    def _refresh_open_menu(self):
        if not self._open:
            return
        hmenu, entries, slots = self._open
        fresh = self._resolve()
        if fresh is None or [e.shape() for e in fresh] != [e.shape() for e in entries]:
            return
        for e, (menu, pos) in zip(self._walk_build_order(fresh), slots):
            mii, _text = self._menu_info(e, with_id=False)
            W.SetMenuItemInfoW(menu, pos, True, byref(mii))
        self._open = (hmenu, fresh, slots)

    def _walk_build_order(self, entries):
        """Entries in the order _build appends their slots (a submenu's own slot before its children)."""
        for e in entries:
            yield e
            if e.children is not None:
                yield from self._walk_build_order(e.children)
