# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Live tests: they add a real (briefly visible) tray icon. Set PURETECH_TRAY_NO_GUI=1 to skip them."""

import ctypes
import os
import threading
import time
from ctypes import byref

import pytest

from puretech_tray import RGBA, SEPARATOR, Item, Menu, Tray
from puretech_tray import _win32 as W
from puretech_tray import tray as TR
from puretech_tray.menu import resolve

pytestmark = pytest.mark.skipif(os.environ.get("PURETECH_TRAY_NO_GUI") == "1", reason="GUI tests disabled")

GetMenuItemCount = W._proto(W.user32, "GetMenuItemCount", ctypes.c_int, W.wintypes.HMENU)
GetMenuItemInfoW = W._proto(W.user32, "GetMenuItemInfoW", W.wintypes.BOOL, W.wintypes.HMENU, W.wintypes.UINT,
                            W.wintypes.BOOL, ctypes.POINTER(W.MENUITEMINFOW))


def icon(rgb):
    return RGBA(bytes(rgb + (255,)) * (32 * 32), 32, 32)


@pytest.fixture
def tray():
    t = Tray(icon((255, 0, 0)), "puretech-tray test", theme=None)
    t.start()
    yield t
    t.stop()


def wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_start_shows_icon_and_stop_ends_thread():
    t = Tray(icon((0, 255, 0)), "tip", theme=None).start()
    assert t.running and t.visible and t.icon_rect() is not None
    assert t._thread.name == "puretech-tray" and t._thread.daemon
    t.stop()
    assert not t._thread.is_alive() and not t.running and not t.visible


def test_update_icon_and_tooltip(tray):
    before = tray._hicon
    tray.update(icon=icon((0, 0, 255)), tooltip="x" * 300)
    assert tray._hicon and tray._hicon != before
    assert tray.tooltip == "x" * 300                # stored in full, sent truncated to 127 characters
    tray.tooltip = "short"
    assert tray.tooltip == "short"
    with pytest.raises(ValueError):
        tray.update(icon=(b"\x00", (4, 4)))


def test_explorer_restart_is_recovered(tray):
    """Simulates Explorer losing the icon, then the TaskbarCreated broadcast Explorer sends when it comes back."""
    assert W.Shell_NotifyIconW(W.NIM_DELETE, byref(tray._nid(0)))
    assert wait(lambda: tray.icon_rect() is None)
    W.PostMessageW(tray.hwnd, W.RegisterWindowMessageW("TaskbarCreated"), 0, 0)
    assert wait(lambda: tray.icon_rect() is not None)
    assert tray.visible


def test_calls_are_marshalled_to_the_tray_thread(tray):
    assert tray._call_sync(lambda: threading.current_thread().name) == "puretech-tray"
    with pytest.raises(ZeroDivisionError):
        tray._call_sync(lambda: 1 / 0)


def test_native_menu_flags(tray):
    m = Menu(Item("Open", None, default=True), SEPARATOR, Item("Check", None, checked=True),
             Item("Radio", None, checked=True, radio=True), Item("Off", None, enabled=False),
             Item("Sub", Menu(Item("Inner", None))), Item("Empty", Menu(lambda: [])))
    entries = resolve(m)
    slots = []
    hmenu = tray._call_sync(lambda: tray._build(entries, slots))
    try:
        assert GetMenuItemCount(hmenu) == 7

        def info(pos):
            mii = W.MENUITEMINFOW(cbSize=ctypes.sizeof(W.MENUITEMINFOW),
                                  fMask=W.MIIM_FTYPE | W.MIIM_STATE | W.MIIM_ID | W.MIIM_SUBMENU)
            assert GetMenuItemInfoW(hmenu, pos, True, byref(mii))
            return mii
        assert info(0).fState & W.MFS_DEFAULT and info(0).wID == entries[0].id
        assert info(1).fType & W.MFT_SEPARATOR
        assert info(2).fState & W.MFS_CHECKED and not info(2).fType & W.MFT_RADIOCHECK
        assert info(3).fState & W.MFS_CHECKED and info(3).fType & W.MFT_RADIOCHECK
        assert info(4).fState & W.MFS_DISABLED
        sub = info(5).hSubMenu
        assert sub and GetMenuItemCount(sub) == 1
        assert info(6).fState & W.MFS_DISABLED          # an empty submenu is greyed out
        assert len(slots) == 8
    finally:
        W.DestroyMenu(hmenu)


def test_menu_opens_and_action_runs_on_tray_thread():
    ran = []
    t = Tray(icon((9, 9, 9)), "menu test", Menu(Item("Go", lambda tr, it: ran.append((tr, it.text,
                                                    threading.current_thread().name)))), theme=None).start()
    try:
        opened = threading.Event()
        orig = W.TrackPopupMenuEx

        def fake_track(hmenu, flags, x, y, hwnd, params):     # pick the first item instead of waiting for a person
            opened.set()
            assert flags & W.TPM_RETURNCMD
            return 1
        TR.W.TrackPopupMenuEx = fake_track
        try:
            W.PostMessageW(t.hwnd, TR._WM_TRAY, (500 << 16) | 500, W.WM_CONTEXTMENU)
            assert opened.wait(2) and wait(lambda: ran)
        finally:
            TR.W.TrackPopupMenuEx = orig
        assert ran == [(t, "Go", "puretech-tray")]
    finally:
        t.stop()


def test_left_click_runs_default_item_then_on_click():
    ran = []
    t = Tray(icon((1, 2, 3)), "click", Menu(Item("Plain", lambda: ran.append("plain")),
                                             Item("Default", lambda: ran.append("default"), default=True)),
             theme=None).start()
    try:
        W.PostMessageW(t.hwnd, TR._WM_TRAY, 0, W.NIN_SELECT)
        assert wait(lambda: ran == ["default"])
        t.on_click = lambda tr: ran.append(("on_click", tr is t))
        W.PostMessageW(t.hwnd, TR._WM_TRAY, 0, W.NIN_SELECT)
        assert wait(lambda: ran[-1] == ("on_click", True))
    finally:
        t.stop()


def test_balloon_fallback_and_its_click(tray):
    clicked = []
    assert tray.notify("Title", "Body", on_click=lambda: clicked.append(1), prefer="balloon") == "balloon"
    W.PostMessageW(tray.hwnd, TR._WM_TRAY, 0, W.NIN_BALLOONUSERCLICK)
    assert wait(lambda: clicked == [1])
    W.PostMessageW(tray.hwnd, TR._WM_TRAY, 0, W.NIN_BALLOONUSERCLICK)       # one click, one run
    time.sleep(0.1)
    assert clicked == [1]


def test_no_app_id_means_balloon(tray):
    assert tray.notify("t", "x", actions=[("A", lambda: None)]) == "balloon"


def test_notify_requires_running():
    with pytest.raises(RuntimeError):
        Tray(icon((0, 0, 0))).notify("t")


def test_app_id_is_registered_lazily_on_first_notify(no_real_start_menu):
    import uuid
    from puretech_tray import shortcut as S
    from puretech_tray.toast import app_id_info, app_id_ready, unregister_app_id
    app = "PureTech.TrayTest" + uuid.uuid4().hex[:8]
    t = Tray(icon((4, 5, 6)), "lazy register", app_id=app, app_name="Tray Test App", theme=None).start()
    try:
        assert app_id_info(app) is None and t._app_state is None          # start() registers nothing
        assert t.notify("t", "x") == "toast"                               # queued while registering
        assert wait(lambda: t._app_state == "ready", 10)
        info = app_id_info(app)
        assert info["DisplayName"] == "Tray Test App" and "ShortcutCheck" in info
        assert S.read_shortcut(info["Shortcut"])["app_id"] == app
        assert os.path.dirname(info["Shortcut"]) == str(no_real_start_menu)
        assert app_id_ready(app, "Tray Test App")
    finally:
        t.stop()
        assert unregister_app_id(app)
    assert app_id_info(app) is None and os.listdir(no_real_start_menu) == []


def test_icon_changed_while_missing_is_used_when_readded(tray):
    """update(icon=...) while Explorer has no icon (restart in progress) must not be lost."""
    assert W.Shell_NotifyIconW(W.NIM_DELETE, byref(tray._nid(0)))
    with tray._lock:
        tray._added = False
    tray.update(icon=icon((0, 0, 255)))
    assert tray._hicon is None                         # the stale handle is gone
    W.PostMessageW(tray.hwnd, W.RegisterWindowMessageW("TaskbarCreated"), 0, 0)
    assert wait(lambda: tray.visible and tray._hicon)
    assert tray.icon.tobytes()[:4] == bytes((0, 0, 255, 255))


def test_notify_returns_queued_when_tray_thread_is_busy(tray, monkeypatch):
    monkeypatch.setattr(TR, "_NOTIFY_WAIT", 0.2)
    release = threading.Event()
    tray._post(lambda: release.wait(3))                # a long menu action holding the tray thread
    assert tray.notify("busy", "x", prefer="balloon") == "queued"
    release.set()
    assert wait(lambda: tray._balloon_icon is not None, 3)   # shown once the thread is free


class _FailingToaster:
    instances = []

    def __init__(self, *args):
        self.closed = False
        self.live = 0
        _FailingToaster.instances.append(self)

    def show(self, *args, **kwargs):
        raise OSError("toasts are disabled for user")

    def close(self):
        self.closed = True


def test_failed_toast_releases_winrt_and_uses_a_balloon(tray, monkeypatch):
    from puretech_tray import toast
    monkeypatch.setattr(toast, "Toaster", _FailingToaster)
    tray.app_id = "PureTech.NotUsed"
    tray._app_state = "ready"
    assert tray.notify("t", "x") == "balloon"
    assert _FailingToaster.instances[-1].closed and tray._toaster is None
