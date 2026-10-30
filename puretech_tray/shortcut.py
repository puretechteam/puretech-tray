# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Start menu shortcuts that carry an AppUserModelID (System.AppUserModel.ID), written with plain ctypes COM.

Windows only shows toasts from an unpackaged app when its AppUserModelID belongs to a Start menu shortcut; a
registry entry alone is accepted and then silently dropped on current Windows 11 builds."""

import ctypes
import os
import sys
from ctypes import POINTER, byref, c_void_p, wintypes

from . import _win32 as W

CLSID_ShellLink = "00021401-0000-0000-c000-000000000046"
IID_IShellLinkW = "000214f9-0000-0000-c000-000000000046"
IID_IPersistFile = "0000010b-0000-0000-c000-000000000046"
IID_IPropertyStore = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
PKEY_AppUserModel_ID = ("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3", 5)
VT_LPWSTR = 31
MAX_PATH = 260
_INVALID = '<>:"/\\|?*'


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", W.GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("pwszVal", c_void_p), ("pad", c_void_p)]


_ole32 = None

def _ole():
    global _ole32
    if _ole32 is None:
        _ole32 = ctypes.WinDLL("ole32")
        _ole32.CoInitializeEx.restype, _ole32.CoInitializeEx.argtypes = ctypes.c_long, [c_void_p, wintypes.DWORD]
        _ole32.CoUninitialize.restype, _ole32.CoUninitialize.argtypes = None, []
        _ole32.CoCreateInstance.restype = ctypes.c_long
        _ole32.CoCreateInstance.argtypes = [POINTER(W.GUID), c_void_p, wintypes.DWORD, POINTER(W.GUID), POINTER(c_void_p)]
        _ole32.PropVariantClear.restype, _ole32.PropVariantClear.argtypes = ctypes.c_long, [POINTER(PROPVARIANT)]
    return _ole32


def _check(hr, what):
    if hr < 0:
        raise OSError(f"{what} failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")


class _Link:
    """A ShellLink object with COM initialized for the duration of a `with` block."""
    def __enter__(self):
        ole = _ole()
        hr = ole.CoInitializeEx(None, 0x2 | 0x4)          # apartment threaded, no OLE1 DDE
        self._uninit = hr >= 0                             # RPC_E_CHANGED_MODE: the thread already has COM
        self.link = c_void_p()
        hr = ole.CoCreateInstance(byref(W.guid(CLSID_ShellLink)), None, 1, byref(W.guid(IID_IShellLinkW)),
                                  byref(self.link))
        if hr < 0:
            self.__exit__()
            _check(hr, "CoCreateInstance(ShellLink)")
        return self

    def __exit__(self, *exc):
        W.release(getattr(self, "link", None))
        if self._uninit:
            _ole().CoUninitialize()

    def iface(self, iid, what):
        p = W.query(self.link, W.guid(iid))
        if not p:
            raise OSError(f"ShellLink has no {what}")
        return p


def real_start_menu_folder():
    """The per-user Programs folder as Windows knows it (FOLDERID_Programs), which is what Windows indexes for
    toasts; %APPDATA% is only the fallback. Differs from start_menu_folder() when a program runs with a private
    APPDATA (for example a test harness), and then waiting for Windows to index the shortcut would be pointless."""
    path = c_void_p()
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    shell32.SHGetKnownFolderPath.argtypes = [POINTER(W.GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)]
    try:
        if shell32.SHGetKnownFolderPath(byref(W.guid("a77f5d77-2e2b-44c3-a6a2-aba601054a51")), 0, None,
                                        byref(path)) >= 0 and path:
            return ctypes.wstring_at(path)
    finally:
        if path:
            ctypes.windll.ole32.CoTaskMemFree(path)
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")


def in_real_start_menu(path):
    return os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(real_start_menu_folder())


def start_menu_folder():
    """Where new shortcuts go: %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs, so a program run with a
    private APPDATA keeps its shortcut there too (tests point this at a temp folder)."""
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")


def shortcut_path(display_name, folder=None):
    """Where the shortcut for `display_name` lives (characters Windows forbids in file names are replaced)."""
    name = "".join("_" if c in _INVALID or ord(c) < 32 else c for c in str(display_name)).strip(" .") or "App"
    return os.path.join(folder or start_menu_folder(), name + ".lnk")


def default_target():
    """(executable, arguments, working folder) that start the running app again: the frozen exe; pythonw.exe with
    `-m package` when it was started with `python -m package`; or pythonw.exe with the main script."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", os.path.dirname(sys.executable)
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    name = getattr(spec, "name", "") or ""
    if name:                                        # python -m pkg (runs pkg.__main__) or python -m module
        module = name[:-len(".__main__")] if name.endswith(".__main__") else name
        return exe, f"-m {module}", os.getcwd()
    main = sys.argv[0] if sys.argv and sys.argv[0] not in ("", "-c", "-m") else ""
    main = os.path.abspath(main) if main and os.path.isfile(main) else ""
    return exe, f'"{main}"' if main else "", os.path.dirname(main) if main else os.path.dirname(exe)


def create_shortcut(path, app_id, target, arguments="", description="", icon_path=None, working_dir=None):
    """Write a .lnk at `path` pointing at `target` and carrying `app_id`. Overwrites an existing file."""
    with _Link() as s:
        link = s.link
        _check(W.com(link, 20, wintypes.LPCWSTR)(str(target)), "IShellLink.SetPath")
        _check(W.com(link, 11, wintypes.LPCWSTR)(str(arguments or "")), "IShellLink.SetArguments")
        _check(W.com(link, 9, wintypes.LPCWSTR)(str(working_dir or os.path.dirname(str(target)))),
               "IShellLink.SetWorkingDirectory")
        if description:
            _check(W.com(link, 7, wintypes.LPCWSTR)(str(description)[:259]), "IShellLink.SetDescription")
        if icon_path:
            _check(W.com(link, 17, wintypes.LPCWSTR, ctypes.c_int)(str(icon_path), 0), "IShellLink.SetIconLocation")
        store = s.iface(IID_IPropertyStore, "IPropertyStore")
        try:
            text = ctypes.create_unicode_buffer(str(app_id))
            pv = PROPVARIANT(vt=VT_LPWSTR, pwszVal=ctypes.cast(text, c_void_p))
            key = PROPERTYKEY(W.guid(PKEY_AppUserModel_ID[0]), PKEY_AppUserModel_ID[1])
            _check(W.com(store, 6, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(byref(key), byref(pv)),
                   "IPropertyStore.SetValue")
            _check(W.com(store, 7)(), "IPropertyStore.Commit")
        finally:
            W.release(store)
        persist = s.iface(IID_IPersistFile, "IPersistFile")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            _check(W.com(persist, 6, wintypes.LPCWSTR, wintypes.BOOL)(os.path.abspath(path), True), "IPersistFile.Save")
        finally:
            W.release(persist)
    return path


def read_shortcut(path):
    """{'app_id', 'target', 'arguments', 'icon'} of a .lnk, or None if it cannot be read."""
    if not os.path.isfile(path):
        return None
    with _Link() as s:
        persist = s.iface(IID_IPersistFile, "IPersistFile")
        try:
            if W.com(persist, 5, wintypes.LPCWSTR, wintypes.DWORD)(os.path.abspath(path), 0) < 0:
                return None
        finally:
            W.release(persist)
        buf = ctypes.create_unicode_buffer(1024)
        out = {"app_id": None}
        W.com(s.link, 3, wintypes.LPWSTR, ctypes.c_int, c_void_p, wintypes.DWORD)(buf, 1024, None, 0)
        out["target"] = buf.value
        W.com(s.link, 10, wintypes.LPWSTR, ctypes.c_int)(buf, 1024)
        out["arguments"] = buf.value
        idx = ctypes.c_int()
        W.com(s.link, 16, wintypes.LPWSTR, ctypes.c_int, POINTER(ctypes.c_int))(buf, 1024, byref(idx))
        out["icon"] = buf.value
        store = s.iface(IID_IPropertyStore, "IPropertyStore")
        try:
            key = PROPERTYKEY(W.guid(PKEY_AppUserModel_ID[0]), PKEY_AppUserModel_ID[1])
            pv = PROPVARIANT()
            if W.com(store, 5, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(byref(key), byref(pv)) >= 0:
                if pv.vt == VT_LPWSTR and pv.pwszVal:
                    out["app_id"] = ctypes.wstring_at(pv.pwszVal)
                _ole().PropVariantClear(byref(pv))
        finally:
            W.release(store)
        return out


def app_indexed(app_id):
    """True once Windows lists `app_id` in its Apps folder (shell:AppsFolder\\<id>). A new Start menu shortcut
    takes about 2.5 s to get there, and toasts sent before that are dropped."""
    ole = _ole()
    hr = ole.CoInitializeEx(None, 0x2 | 0x4)
    try:
        shell32 = ctypes.WinDLL("shell32")
        create = shell32.SHCreateItemFromParsingName
        create.restype = ctypes.c_long
        create.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(W.GUID), POINTER(c_void_p)]
        item = c_void_p()
        if create("shell:AppsFolder\\" + str(app_id), None, byref(W.guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")),
                  byref(item)) >= 0 and item:
            W.release(item)
            return True
        return False
    finally:
        if hr >= 0:
            ole.CoUninitialize()


def wait_indexed(app_id, timeout=10.0, interval=0.05):
    """Wait until app_indexed(app_id); returns whether it got there within `timeout` seconds."""
    import time
    end = time.monotonic() + timeout
    while True:
        if app_indexed(app_id):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(interval)


def remove_shortcut(path, app_id):
    """Delete the .lnk only if it carries `app_id` (never a shortcut someone else made). True if deleted."""
    info = read_shortcut(path)
    if not info or info["app_id"] != app_id:
        return False
    os.remove(path)
    return True
