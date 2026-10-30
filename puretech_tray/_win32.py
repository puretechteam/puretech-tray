# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""ctypes bindings for the bits of user32, shell32, gdi32, uxtheme and combase this package uses."""

import ctypes
import sys
from ctypes import POINTER, byref, c_void_p, wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
HRESULT = ctypes.c_long

# ---- messages and flags ----------------------------------------------------------------------------------------
WM_NULL, WM_DESTROY, WM_CLOSE, WM_TIMER = 0x0000, 0x0002, 0x0010, 0x0113
WM_SETTINGCHANGE, WM_DISPLAYCHANGE, WM_DPICHANGED = 0x001A, 0x007E, 0x02E0
WM_CONTEXTMENU, WM_LBUTTONUP, WM_RBUTTONUP = 0x007B, 0x0202, 0x0205
WM_USER, WM_APP = 0x0400, 0x8000

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NOTIFYICON_VERSION_4 = 4
NIN_SELECT, NIN_KEYSELECT, NIN_BALLOONUSERCLICK = WM_USER, WM_USER + 1, WM_USER + 5
NIIF_INFO, NIIF_USER, NIIF_NOSOUND, NIIF_LARGE_ICON, NIIF_RESPECT_QUIET_TIME = 0x01, 0x04, 0x10, 0x20, 0x80

MIIM_STATE, MIIM_ID, MIIM_SUBMENU, MIIM_STRING, MIIM_FTYPE = 0x01, 0x02, 0x04, 0x40, 0x100
MFT_STRING, MFT_RADIOCHECK, MFT_SEPARATOR = 0x000, 0x200, 0x800
MFS_ENABLED, MFS_DISABLED, MFS_CHECKED, MFS_DEFAULT = 0x0, 0x3, 0x8, 0x1000
TPM_LEFTALIGN, TPM_RIGHTALIGN, TPM_BOTTOMALIGN = 0x0, 0x8, 0x20
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
SM_CXICON, SM_CXSMICON, SM_MENUDROPALIGNMENT = 11, 49, 40
MSGFLT_ALLOW = 1
WS_OVERLAPPED = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

# ---- structures ------------------------------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

def guid(text):
    """GUID from 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'."""
    h = text.strip("{}").replace("-", "")
    return GUID(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16), (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]

class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("guidItem", GUID)]

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("fMask", wintypes.UINT), ("fType", wintypes.UINT), ("fState", wintypes.UINT),
                ("wID", wintypes.UINT), ("hSubMenu", wintypes.HMENU), ("hbmpChecked", wintypes.HBITMAP),
                ("hbmpUnchecked", wintypes.HBITMAP), ("dwItemData", ctypes.c_size_t), ("dwTypeData", wintypes.LPWSTR),
                ("cch", wintypes.UINT), ("hbmpItem", wintypes.HBITMAP)]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]

class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

# ---- prototypes ------------------------------------------------------------------------------------------------
def _proto(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, list(argtypes)
    return fn

RegisterClassExW = _proto(user32, "RegisterClassExW", wintypes.ATOM, POINTER(WNDCLASSEXW))
UnregisterClassW = _proto(user32, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE)
CreateWindowExW = _proto(user32, "CreateWindowExW", wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                         wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                         wintypes.HMENU, wintypes.HINSTANCE, c_void_p)
DestroyWindow = _proto(user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
DefWindowProcW = _proto(user32, "DefWindowProcW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
GetMessageW = _proto(user32, "GetMessageW", wintypes.BOOL, POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
TranslateMessage = _proto(user32, "TranslateMessage", wintypes.BOOL, POINTER(MSG))
DispatchMessageW = _proto(user32, "DispatchMessageW", LRESULT, POINTER(MSG))
PostMessageW = _proto(user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
PostQuitMessage = _proto(user32, "PostQuitMessage", None, ctypes.c_int)
RegisterWindowMessageW = _proto(user32, "RegisterWindowMessageW", wintypes.UINT, wintypes.LPCWSTR)
ChangeWindowMessageFilterEx = _proto(user32, "ChangeWindowMessageFilterEx", wintypes.BOOL, wintypes.HWND, wintypes.UINT,
                                     wintypes.DWORD, c_void_p)
SetForegroundWindow = _proto(user32, "SetForegroundWindow", wintypes.BOOL, wintypes.HWND)
GetCursorPos = _proto(user32, "GetCursorPos", wintypes.BOOL, POINTER(wintypes.POINT))
GetSystemMetrics = _proto(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
GetMessageTime = _proto(user32, "GetMessageTime", wintypes.LONG)
SetTimer = _proto(user32, "SetTimer", ctypes.c_size_t, wintypes.HWND, ctypes.c_size_t, wintypes.UINT, c_void_p)
KillTimer = _proto(user32, "KillTimer", wintypes.BOOL, wintypes.HWND, ctypes.c_size_t)
CreatePopupMenu = _proto(user32, "CreatePopupMenu", wintypes.HMENU)
DestroyMenu = _proto(user32, "DestroyMenu", wintypes.BOOL, wintypes.HMENU)
InsertMenuItemW = _proto(user32, "InsertMenuItemW", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, wintypes.BOOL,
                         POINTER(MENUITEMINFOW))
SetMenuItemInfoW = _proto(user32, "SetMenuItemInfoW", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, wintypes.BOOL,
                          POINTER(MENUITEMINFOW))
TrackPopupMenuEx = _proto(user32, "TrackPopupMenuEx", wintypes.BOOL, wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                          ctypes.c_int, wintypes.HWND, c_void_p)
EndMenu = _proto(user32, "EndMenu", wintypes.BOOL)
CreateIconIndirect = _proto(user32, "CreateIconIndirect", wintypes.HICON, POINTER(ICONINFO))
DestroyIcon = _proto(user32, "DestroyIcon", wintypes.BOOL, wintypes.HICON)
Shell_NotifyIconW = _proto(shell32, "Shell_NotifyIconW", wintypes.BOOL, wintypes.DWORD, POINTER(NOTIFYICONDATAW))
Shell_NotifyIconGetRect = _proto(shell32, "Shell_NotifyIconGetRect", HRESULT, POINTER(NOTIFYICONIDENTIFIER),
                                 POINTER(wintypes.RECT))
CreateDIBSection = _proto(gdi32, "CreateDIBSection", wintypes.HBITMAP, wintypes.HDC, c_void_p, wintypes.UINT,
                          POINTER(c_void_p), wintypes.HANDLE, wintypes.DWORD)
CreateBitmap = _proto(gdi32, "CreateBitmap", wintypes.HBITMAP, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT,
                      c_void_p)
DeleteObject = _proto(gdi32, "DeleteObject", wintypes.BOOL, wintypes.HGDIOBJ)
GetModuleHandleW = _proto(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)

def _optional(dll, name, restype, *argtypes):
    """A function that only exists on newer Windows builds, or None."""
    try:
        return _proto(dll, name, restype, *argtypes)
    except AttributeError:
        return None

SetThreadDpiAwarenessContext = _optional(user32, "SetThreadDpiAwarenessContext", c_void_p, c_void_p)
GetDpiForWindow = _optional(user32, "GetDpiForWindow", wintypes.UINT, wintypes.HWND)
GetSystemMetricsForDpi = _optional(user32, "GetSystemMetricsForDpi", ctypes.c_int, ctypes.c_int, wintypes.UINT)

def windows_build():
    return sys.getwindowsversion().build

def icon_size(hwnd, large=False):
    """Pixel size the shell wants for a small (tray) or large (balloon) icon at this window's DPI."""
    metric = SM_CXICON if large else SM_CXSMICON
    if GetDpiForWindow and GetSystemMetricsForDpi:
        dpi = GetDpiForWindow(hwnd) if hwnd else 0
        if dpi:
            return GetSystemMetricsForDpi(metric, dpi)
    return GetSystemMetrics(metric)

# ---- uxtheme dark menus (undocumented ordinals, Windows 10 1809+) -----------------------------------------------
APP_MODES = {"auto": 1, "dark": 2, "light": 3}

class DarkMenus:
    """SetPreferredAppMode (#135), AllowDarkModeForWindow (#133), RefreshImmersiveColorPolicyState (#104) and
    FlushMenuThemes (#136). Everything fails silently: on older Windows the menus are simply light."""
    def __init__(self):
        self.ok = False
        if windows_build() < 17763:
            return
        try:
            ux = ctypes.WinDLL("uxtheme")
            self._set_mode = ux[135]
            self._set_mode.restype, self._set_mode.argtypes = ctypes.c_int, [ctypes.c_int]
            self._allow_window = ux[133]
            self._allow_window.restype, self._allow_window.argtypes = wintypes.BOOL, [wintypes.HWND, wintypes.BOOL]
            self._refresh = ux[104]
            self._refresh.restype, self._refresh.argtypes = None, []
            self._flush = ux[136]
            self._flush.restype, self._flush.argtypes = None, []
            self.ok = True
        except (OSError, AttributeError):
            pass

    def apply(self, hwnd, theme="auto"):
        if not self.ok or theme not in APP_MODES:
            return False
        try:
            mode = APP_MODES[theme]
            if windows_build() < 18362:               # 1809: ordinal 135 is AllowDarkModeForApp(BOOL)
                mode = int(theme != "light")
            self._set_mode(mode)
            self._allow_window(hwnd, theme != "light")
            self._refresh()
            self._flush()
            return True
        except OSError:
            return False

    def refresh(self):
        if self.ok:
            try:
                self._refresh()
                self._flush()
            except OSError:
                pass

def system_uses_dark_apps():
    """True when Settings > Personalization > Colors has apps in dark mode."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False

# ---- COM / WinRT -----------------------------------------------------------------------------------------------
def com(obj, index, *argtypes):
    """Bind vtable slot `index` of COM object `obj` (a c_void_p) to a callable returning the raw HRESULT."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtbl[index])
    return lambda *args: fn(obj, *args)

def release(obj):
    if obj:
        com(obj, 2)()

def query(obj, iid):
    """QueryInterface; returns a new c_void_p or None."""
    out = c_void_p()
    if com(obj, 0, POINTER(GUID), POINTER(c_void_p))(byref(iid), byref(out)) == 0 and out:
        return out
    return None

def hresult(value):
    return value & 0xFFFFFFFF
