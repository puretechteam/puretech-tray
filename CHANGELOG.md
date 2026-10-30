# Changelog

All notable changes to puretech-tray are listed here.

## Unreleased

## 0.1.0 - 2026-10-30

- First version: a native Windows tray icon in pure ctypes with zero dependencies (Python 3.10+, Windows 10/11).
- Tray icon on its own thread using `Shell_NotifyIconW` with NOTIFYICON_VERSION_4; comes back on its own after Explorer restarts (`TaskbarCreated`) and retries while Explorer is still starting at logon.
- Icons from RGBA bytes or any image with `.tobytes()`/`.size` (Pillow works, but is not required), sized for the screen's DPI and redrawn when the DPI changes. Live icon and tooltip updates from any thread.
- Native popup menu: checkboxes, radio items, submenus, separators, a bold default item, and text/checked/enabled/visible as values or functions evaluated each time the menu opens. Left click runs the default item, right click opens the menu.
- Menus follow Windows dark or light mode (or can be forced either way), with a silent fallback on older Windows.
- Toast notifications with up to five buttons that call back into Python while the app runs; falls back to a classic balloon (clickable) when toasts are unavailable.
- Toasts show under your app's own name: on the first notification the tray registers its AppUserModelID for the current user with a Start menu shortcut that carries it (Windows 11 drops toasts for ids without one), in the background, waiting the ~2.5 s Windows needs to index a new shortcut. Later runs check the registration without COM. `app_shortcut=False` skips the shortcut.
- Light on memory: toast support loads nothing until the first notification, so a tray with an app id starts as small as one without (+3.6 MB working set), and Windows' notification components are unloaded again once no toast can be clicked (about 6 MB of working set back).
- `register_app_id()` / `unregister_app_id()` helpers for the toast registration (registry key and shortcut), and `ico_bytes()` to write a .ico for it.
- Compared with pystray 0.19.5 on the same machine: imports 2.1x faster (53 to 26 ms), shows its icon 4.2x sooner (114 to 27 ms), adds 2.6x less private memory (5,668 to 2,216 KB), updates the icon 12x faster (2.59 to 0.21 ms) and installs 1.7x smaller (176.5 to 101.3 KB) with no Pillow or six needed. Full numbers in the README and `docs/perf.json`.
