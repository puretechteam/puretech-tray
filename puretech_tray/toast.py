# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Windows toast notifications through WinRT, called with plain ctypes.

An unpackaged app needs an AppUserModelID that Windows knows about. register_app_id() writes one per user under
HKCU\\Software\\Classes\\AppUserModelId\\<id> (DisplayName, optional IconUri) and a Start menu shortcut carrying
the id: Windows 11 (build 26200) accepts toasts for a registry-only id but never shows them.
Button and body clicks reach Python while the app runs, through an Activated handler implemented as a COM delegate."""

import ctypes
import os
import threading
import winreg
from ctypes import POINTER, byref, c_void_p, wintypes

# Only cheap modules up here: xml.sax.saxutils pulls in urllib.request (ssl, OpenSSL, sockets, bz2, lzma) and uuid
# pulls in hashlib, together about 10 MB of working set for a tray icon that may never show a toast.

APP_ID_KEY = r"Software\Classes\AppUserModelId"
MAX_ACTIONS = 5                      # Windows shows at most five buttons
_MARKER_VALUES = ("DisplayName", "IconUri", "Shortcut", "ShortcutCheck")

# ---- XML -------------------------------------------------------------------------------------------------------
def _escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _attr(text):
    return '"' + _escape(text).replace('"', "&quot;").replace("\n", "&#10;").replace("\r", "&#13;") \
        .replace("\t", "&#9;") + '"'

def build_toast_xml(title, text="", actions=(), launch="", silent=False, image=None):
    """ToastGeneric XML. `actions` is a list of (label, arguments) pairs; at most five are kept."""
    head = f"<toast launch={_attr(launch)} activationType=\"foreground\">" if launch else "<toast>"
    parts = [head, "<visual><binding template=\"ToastGeneric\">", f"<text>{_escape(title)}</text>"]
    if text:
        parts.append(f"<text>{_escape(text)}</text>")
    if image:
        parts.append(f"<image placement=\"appLogoOverride\" src={_attr(image)}/>")
    parts.append("</binding></visual>")
    if actions:
        parts.append("<actions>")
        for label, args in list(actions)[:MAX_ACTIONS]:
            parts.append(f"<action content={_attr(label)} arguments={_attr(args)} activationType=\"foreground\"/>")
        parts.append("</actions>")
    if silent:
        parts.append("<audio silent=\"true\"/>")
    parts.append("</toast>")
    return "".join(parts)

# ---- AUMID registration -----------------------------------------------------------------------------------------
def _plan(app_id, display_name, icon_path, shortcut, target, arguments, folder):
    """The registry values we want, minus the shortcut check, plus the shortcut details."""
    want = {"DisplayName": str(display_name)}
    if icon_path:
        want["IconUri"] = str(icon_path)
    if not shortcut:
        return want, None
    from . import shortcut as sc
    lnk = sc.shortcut_path(display_name, folder)
    workdir = None
    if target is None:
        target, default_args, workdir = sc.default_target()
        arguments = default_args if arguments is None else arguments
    icon = str(icon_path) if icon_path and str(icon_path).lower().endswith(".ico") else ""
    want["Shortcut"] = lnk
    return want, (lnk, str(target), arguments or "", icon, workdir)

def _check_value(app_id, link):
    """What ShortcutCheck holds: the shortcut's id, target, arguments and icon, and the file's size and mtime when
    they were last verified. A match means the .lnk is ours and unchanged, without opening it through COM."""
    lnk, target, arguments, icon, _workdir = link
    try:
        st = os.stat(lnk)
    except OSError:
        return None
    return f"{app_id}|{target}|{arguments}|{icon}|{st.st_size}|{st.st_mtime_ns}"

def app_id_ready(app_id, display_name, icon_path=None, *, shortcut=True, target=None, arguments=None, folder=None,
                 base=APP_ID_KEY, root=winreg.HKEY_CURRENT_USER):
    """True when register_app_id() would change nothing. Reads the registry and stats one file: no COM."""
    _check_id(app_id)
    want, link = _plan(app_id, display_name, icon_path, shortcut, target, arguments, folder)
    if link:
        check = _check_value(app_id, link)
        if check is None:
            return False
        want["ShortcutCheck"] = check
    current = app_id_info(app_id, base=base, root=root) or {}
    return {k: v for k, v in current.items() if k in _MARKER_VALUES} == want

def register_app_id(app_id, display_name, icon_path=None, *, shortcut=True, target=None, arguments=None,
                    folder=None, wait=10.0, base=APP_ID_KEY, root=winreg.HKEY_CURRENT_USER):
    """Register `app_id` for toasts, for the current user only:

    - HKCU\\Software\\Classes\\AppUserModelId\\<app_id> with DisplayName and IconUri (the toast's name and icon);
    - with `shortcut=True`, a Start menu shortcut carrying the id, which current Windows 11 builds require before
      they show toasts from an unpackaged app. It starts `target` with `arguments` (default: the running app).

    Returns at once (False) when app_id_ready() says all of that is already in place. After creating or changing
    the Start menu shortcut it waits (up to `wait` seconds, about 2.5 s in practice) until Windows has indexed it,
    because toasts sent earlier are dropped. Returns True if anything changed."""
    _check_id(app_id)
    if app_id_ready(app_id, display_name, icon_path, shortcut=shortcut, target=target, arguments=arguments,
                    folder=folder, base=base, root=root):
        return False
    path = f"{base}\\{app_id}"
    want, link = _plan(app_id, display_name, icon_path, shortcut, target, arguments, folder)
    changed = False
    lnk = None
    if link:
        from . import shortcut as sc
        lnk, target, arguments, icon, workdir = link
        have = sc.read_shortcut(lnk)
        if have and have["app_id"] not in (None, app_id):
            raise FileExistsError(f"{lnk} already belongs to {have['app_id']}")
        wanted = (app_id, target.lower(), arguments, icon.lower())
        if not have or (have["app_id"], have["target"].lower(), have["arguments"], have["icon"].lower()) != wanted:
            sc.create_shortcut(lnk, app_id, target, arguments, str(display_name), icon or None, workdir)
            changed = True
            if wait and sc.in_real_start_menu(lnk):
                sc.wait_indexed(app_id, wait)
        want["ShortcutCheck"] = _check_value(app_id, link)
    current = app_id_info(app_id, base=base, root=root)
    if current != want:
        old_lnk = (current or {}).get("Shortcut")
        if old_lnk and old_lnk != lnk:
            from . import shortcut as sc
            sc.remove_shortcut(old_lnk, app_id)
        with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            for name in set(current or ()) - set(want):
                if name in _MARKER_VALUES:
                    winreg.DeleteValue(key, name)
            for name, value in want.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        changed = True
    return changed

def _check_id(app_id):
    if not app_id or "\\" in app_id:
        raise ValueError("app_id must be a non-empty name without backslashes")

def app_id_info(app_id, *, base=APP_ID_KEY, root=winreg.HKEY_CURRENT_USER):
    """The values under the app id's key ({'DisplayName': ..., 'IconUri': ..., 'Shortcut': ...}), or None."""
    try:
        with winreg.OpenKey(root, f"{base}\\{app_id}") as key:
            out, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    return out
                out[name] = value
                i += 1
    except FileNotFoundError:
        return None

def unregister_app_id(app_id, *, base=APP_ID_KEY, root=winreg.HKEY_CURRENT_USER):
    """Remove the key (and anything under it) and the Start menu shortcut it recorded, if that shortcut still
    carries `app_id`. Returns True if anything existed."""
    _check_id(app_id)
    lnk = (app_id_info(app_id, base=base, root=root) or {}).get("Shortcut")
    removed = False
    if lnk:
        from . import shortcut as sc
        removed = sc.remove_shortcut(lnk, app_id)
    return _delete_tree(root, f"{base}\\{app_id}") or removed

def _delete_tree(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            subs = []
            while True:
                try:
                    subs.append(winreg.EnumKey(key, len(subs)))
                except OSError:
                    break
        for sub in subs:
            _delete_tree(root, f"{path}\\{sub}")
        winreg.DeleteKey(root, path)
        return True
    except FileNotFoundError:
        return False

# ---- WinRT plumbing ----------------------------------------------------------------------------------------------
def pinterface_iid(signature):
    """IID of a parameterized WinRT interface (UUID v5 over the type signature, as the C++/WinRT tooling does)."""
    import hashlib
    import uuid
    ns = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee").bytes
    digest = bytearray(hashlib.sha1(ns + signature.encode("utf-8")).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x50
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))

IID_IToastNotification = "997e2675-059e-4e60-8b06-1760917c8b80"
TYPED_EVENT_HANDLER = "{9de1c534-6ae1-11e0-84e1-18a905bcc53f}"

def _handler_signature(args_signature):
    return (f"pinterface({TYPED_EVENT_HANDLER};rc(Windows.UI.Notifications.ToastNotification;"
            f"{{{IID_IToastNotification}}});{args_signature})")

ACTIVATED_SIGNATURE = _handler_signature("cinterface(IInspectable)")
DISMISSED_SIGNATURE = _handler_signature("rc(Windows.UI.Notifications.ToastDismissedEventArgs;"
                                         "{3f89d935-d9cb-4538-a0f0-ffe7659938f8})")
FAILED_SIGNATURE = _handler_signature("rc(Windows.UI.Notifications.ToastFailedEventArgs;"
                                      "{35176862-cfd4-44f8-ad64-f500fd896c3b})")

# pinterface_iid() of the three signatures above, precomputed so showing a toast needs no hashlib/uuid
# (tests check these against pinterface_iid() and the Windows SDK headers).
ACTIVATED_IID = "ab54de2d-97d9-5528-b6ad-105afe156530"
DISMISSED_IID = "61c2402f-0ed0-5a18-ab69-59f4aa99a368"
FAILED_IID = "95e3e803-c969-5e3a-9753-ea2ad22a9a33"

S_OK = 0
E_NOINTERFACE = 0x80004002 - (1 << 32)
RPC_E_CHANGED_MODE = 0x80010106 - (1 << 32)
NOTIFICATION_SETTINGS = {0: "enabled", 1: "disabled for app", 2: "disabled for user", 3: "disabled by policy",
                         4: "disabled by manifest"}

class EventRegistrationToken(ctypes.Structure):
    _fields_ = [("value", ctypes.c_int64)]

_combase = None
_api = {}

def _load():
    global _combase
    if _combase is None:
        from . import _win32 as W
        _combase = ctypes.WinDLL("combase")
        HSTRING = c_void_p
        for name, res, args in (
                ("RoInitialize", ctypes.c_long, [ctypes.c_int]),
                ("RoUninitialize", None, []),
                ("WindowsCreateString", ctypes.c_long, [wintypes.LPCWSTR, ctypes.c_uint32, POINTER(HSTRING)]),
                ("WindowsDeleteString", ctypes.c_long, [HSTRING]),
                ("WindowsGetStringRawBuffer", wintypes.LPCWSTR, [HSTRING, POINTER(ctypes.c_uint32)]),
                ("RoGetActivationFactory", ctypes.c_long, [HSTRING, POINTER(W.GUID), POINTER(c_void_p)]),
                ("RoActivateInstance", ctypes.c_long, [HSTRING, POINTER(c_void_p)])):
            fn = getattr(_combase, name)
            fn.restype, fn.argtypes = res, args
            _api[name] = fn
    return _api

class HString:
    """A WinRT HSTRING that deletes itself."""
    def __init__(self, text):
        api = _load()
        self.handle = c_void_p()
        _check(api["WindowsCreateString"](text, len(text), byref(self.handle)), "WindowsCreateString")

    def __enter__(self):
        return self.handle

    def __exit__(self, *exc):
        _load()["WindowsDeleteString"](self.handle)

def hstring_text(handle):
    if not handle:
        return ""
    n = ctypes.c_uint32()
    raw = _load()["WindowsGetStringRawBuffer"](handle, byref(n))
    return raw[:n.value] if raw else ""

class WinRTError(OSError):
    pass

def _check(hr, what):
    if hr < 0:
        raise WinRTError(f"{what} failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")
    return hr

# ---- delegates -------------------------------------------------------------------------------------------------
_QI = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, POINTER(c_void_p))
_REF = ctypes.WINFUNCTYPE(wintypes.ULONG, c_void_p)
_INVOKE = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, c_void_p)

class _Delegate:
    """A TypedEventHandler<ToastNotification, T> COM object. Instances are module-level and never freed, so a late
    callback from Windows after the tray stopped can never land on freed memory; reference counting is a no-op."""
    def __init__(self, iid, fn):
        from . import _win32 as W
        wanted = {bytes(W.guid(i)) for i in ("00000000-0000-0000-c000-000000000046",      # IUnknown
                                             "94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90",      # IAgileObject
                                             iid)}

        def query(this, riid, out):
            if bytes(ctypes.string_at(riid, 16)) in wanted:
                out[0] = this
                return S_OK
            out[0] = None
            return E_NOINTERFACE

        def invoke(this, sender, args):
            try:
                fn(sender, args)
            except Exception:                       # never let an exception unwind into Windows
                import logging
                logging.getLogger("puretech_tray").exception("toast event handler failed")
            return S_OK

        self._fns = [_QI(query), _REF(lambda this: 1), _REF(lambda this: 1), _INVOKE(invoke)]
        self._vtbl = (c_void_p * 4)(*[ctypes.cast(f, c_void_p) for f in self._fns])
        self._obj = (c_void_p * 1)(ctypes.addressof(self._vtbl))
        self.ptr = c_void_p(ctypes.addressof(self._obj))

# toast key -> record; shared by every Toaster because the delegates are shared
_records = {}
_records_lock = threading.Lock()
_delegates = None

def _record_for_sender(sender):
    with _records_lock:
        for rec in _records.values():
            if rec.toast.value == sender:
                return rec
    return None

def _on_activated(sender, args):
    from . import _win32 as W
    arguments = ""
    eargs = W.query(c_void_p(args), W.guid("e3bf92f3-c197-436f-8265-0625824f8dac")) if args else None
    if eargs:
        h = c_void_p()
        if W.com(eargs, 6, POINTER(c_void_p))(byref(h)) >= 0:
            arguments = hstring_text(h)
            _load()["WindowsDeleteString"](h)
        W.release(eargs)
    rec = None
    if arguments.startswith("ptt:"):
        _, key, which = (arguments.split(":", 2) + ["", ""])[:3]
        with _records_lock:
            rec = _records.get(key)
    else:
        rec, which = _record_for_sender(sender), "click"
    if rec is not None:
        rec.owner._toast_event(rec, "activated", which)

def _on_dismissed(sender, args):
    from . import _win32 as W
    reason = -1
    eargs = W.query(c_void_p(args), W.guid("3f89d935-d9cb-4538-a0f0-ffe7659938f8")) if args else None
    if eargs:
        r = ctypes.c_int()
        if W.com(eargs, 6, POINTER(ctypes.c_int))(byref(r)) >= 0:
            reason = r.value
        W.release(eargs)
    rec = _record_for_sender(sender)
    if rec is not None:
        rec.owner._toast_event(rec, "dismissed", reason)

def _on_failed(sender, args):
    from . import _win32 as W
    code = 0
    eargs = W.query(c_void_p(args), W.guid("35176862-cfd4-44f8-ad64-f500fd896c3b")) if args else None
    if eargs:
        c = ctypes.c_int32()
        if W.com(eargs, 6, POINTER(ctypes.c_int32))(byref(c)) >= 0:
            code = c.value
        W.release(eargs)
    rec = _record_for_sender(sender)
    if rec is not None:
        rec.owner._toast_event(rec, "failed", code)

def _get_delegates():
    global _delegates
    if _delegates is None:
        _delegates = {"activated": _Delegate(ACTIVATED_IID, _on_activated),
                      "dismissed": _Delegate(DISMISSED_IID, _on_dismissed),
                      "failed": _Delegate(FAILED_IID, _on_failed)}
    return _delegates

_key_counter = [0]

def _next_key():
    """A key unique in this process (Toaster objects come and go; their keys must never repeat)."""
    with _records_lock:
        _key_counter[0] += 1
        return f"{_key_counter[0]:x}"

class _Record:
    __slots__ = ("key", "owner", "toast", "tokens", "actions", "on_click", "title", "text")

# ---- the toaster -------------------------------------------------------------------------------------------------
class Toaster:
    """Shows toasts for one AppUserModelID. All methods must be called on one thread (the tray thread).

    `post(fn)` is how a click gets back to that thread; Activated arrives on a Windows worker thread."""
    KEEP = 20                 # toasts whose buttons stay live (older ones in Action Center become inert)

    def __init__(self, app_id, post, on_failed=None, on_idle=None):
        """`on_idle()` runs (on the owner's thread) when the last toast that could still be clicked is gone, so
        the owner can close() and let Windows unload WinRT (about 6 MB of working set)."""
        self.app_id, self.post, self.on_failed, self.on_idle = app_id, post, on_failed, on_idle
        self.notifier = None
        self.factory = None
        self._inited = False
        self._mine = []

    def open(self):
        """Initialize WinRT and the notifier. Raises WinRTError with the reason when toasts cannot work."""
        from . import _win32 as W
        api = _load()
        if not self._inited:
            hr = api["RoInitialize"](1)                    # RO_INIT_MULTITHREADED
            if hr < 0 and hr != RPC_E_CHANGED_MODE:
                _check(hr, "RoInitialize")
            self._inited = hr >= 0
        if self.notifier is None:
            statics = c_void_p()
            with HString("Windows.UI.Notifications.ToastNotificationManager") as name:
                _check(api["RoGetActivationFactory"](name, byref(W.guid("50ac103f-d235-4598-bbef-98fe4d1a3ad4")),
                                                     byref(statics)), "ToastNotificationManager")
            try:
                notifier = c_void_p()
                with HString(self.app_id) as hid:
                    _check(W.com(statics, 7, c_void_p, POINTER(c_void_p))(hid, byref(notifier)),
                           "CreateToastNotifierWithId")
            finally:
                W.release(statics)
            factory = c_void_p()
            with HString("Windows.UI.Notifications.ToastNotification") as name:
                hr = api["RoGetActivationFactory"](name, byref(W.guid("04124b20-82c6-4229-b109-fd9ed4662b53")),
                                                   byref(factory))
            if hr < 0:
                W.release(notifier)
                _check(hr, "ToastNotification factory")
            self.notifier, self.factory = notifier, factory
        return self.setting()

    def setting(self):
        """Windows' NotificationSetting for this app id as text ('enabled' when toasts can show)."""
        from . import _win32 as W
        value = ctypes.c_int(-1)
        if self.notifier is None or W.com(self.notifier, 8, POINTER(ctypes.c_int))(byref(value)) < 0:
            return "unknown"
        return NOTIFICATION_SETTINGS.get(value.value, f"setting {value.value}")

    def show(self, title, text="", actions=(), on_click=None, silent=False, image=None):
        """Show a toast. Returns its key. Raises WinRTError if Windows refuses it."""
        from . import _win32 as W
        api = _load()
        state = self.open()
        if state.startswith("disabled"):       # "unknown" is normal for some ids that do show (e.g. shortcut ids)
            raise WinRTError(f"toasts are {state} for {self.app_id}")
        key = _next_key()
        actions = list(actions or ())[:MAX_ACTIONS]
        xml = build_toast_xml(title, text, [(label, f"ptt:{key}:{i}") for i, (label, _) in enumerate(actions)],
                              launch=f"ptt:{key}:click", silent=silent, image=image)

        inspectable = c_void_p()
        with HString("Windows.Data.Xml.Dom.XmlDocument") as cls:
            _check(api["RoActivateInstance"](cls, byref(inspectable)), "XmlDocument")
        doc_io = doc = toast = None
        try:
            doc_io = W.query(inspectable, W.guid("6cd0e74e-ee65-4489-9ebf-ca43e87ba637"))
            doc = W.query(inspectable, W.guid("f7f3a506-1e87-42d6-bcfb-b8c809fa5494"))
            if not doc_io or not doc:
                raise WinRTError("XmlDocument interfaces missing")
            with HString(xml) as hxml:
                _check(W.com(doc_io, 6, c_void_p)(hxml), "XmlDocument.LoadXml")
            toast = c_void_p()
            _check(W.com(self.factory, 6, c_void_p, POINTER(c_void_p))(doc, byref(toast)), "CreateToastNotification")
        finally:
            for p in (doc_io, doc, inspectable):
                W.release(p)

        rec = _Record()
        rec.key, rec.owner, rec.toast, rec.tokens = key, self, toast, {}
        rec.actions, rec.on_click, rec.title, rec.text = [fn for _, fn in actions], on_click, title, text
        with _records_lock:
            _records[key] = rec
        delegates = _get_delegates()
        for event, slot in (("dismissed", 9), ("activated", 11), ("failed", 13)):
            token = EventRegistrationToken()
            if W.com(toast, slot, c_void_p, POINTER(EventRegistrationToken))(delegates[event].ptr, byref(token)) >= 0:
                rec.tokens[slot + 1] = token          # remove_X is the slot after add_X
        hr = W.com(self.notifier, 6, c_void_p)(toast)
        if hr < 0:
            self._drop(rec)
            _check(hr, "ToastNotifier.Show")
        self._mine.append(rec)
        while len(self._mine) > self.KEEP:
            self._drop(self._mine[0])
        return key

    def _toast_event(self, rec, kind, detail):
        """Runs on a Windows worker thread: hand everything to the owner's thread."""
        self.post(lambda: self._handle(rec, kind, detail))

    def _handle(self, rec, kind, detail):
        if kind == "activated":
            if detail == "click":
                fn = rec.on_click
            else:
                try:
                    fn = rec.actions[int(detail)]
                except (ValueError, IndexError):
                    fn = None
            self._drop(rec)                                 # an activated toast is gone from the screen
            if fn is not None:
                fn()
        elif kind == "failed":
            self._drop(rec)
            if self.on_failed:
                self.on_failed(rec.title, rec.text, rec.on_click or (rec.actions[0] if rec.actions else None), detail)
        elif kind == "dismissed" and detail in (0, 1):     # UserCanceled, ApplicationHidden; TimedOut stays live
            self._drop(rec)

    def _drop(self, rec):
        from . import _win32 as W
        with _records_lock:
            _records.pop(rec.key, None)
        if rec in self._mine:
            self._mine.remove(rec)
        if rec.toast:
            for slot, token in rec.tokens.items():
                W.com(rec.toast, slot, EventRegistrationToken)(token)
            W.release(rec.toast)
            rec.toast = c_void_p()
        if not self._mine and self.on_idle and not getattr(self, "_closing", False):
            self.post(self.on_idle)

    @property
    def live(self):
        """How many shown toasts can still be clicked."""
        return len(self._mine)

    def close(self):
        from . import _win32 as W
        self._closing = True
        for rec in list(self._mine):
            self._drop(rec)
        W.release(self.notifier)
        W.release(self.factory)
        self.notifier = self.factory = None
        # Event callbacks arrive on Windows worker threads that keep the MTA alive, so uninitializing alone does
        # not unload the notification DLLs; ask COM to free whatever is unused now.
        try:
            ctypes.windll.ole32.CoFreeUnusedLibrariesEx(0, 0)
        except (OSError, AttributeError):
            pass
        if self._inited:
            _load()["RoUninitialize"]()
            self._inited = False
