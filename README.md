# puretech-tray

A native Windows tray icon for Python, written in pure ctypes. No dependencies.

Menus with checkboxes, radio items and submenus, dark mode that follows Windows, live icon updates, and toast
notifications whose buttons call your Python code. A drop-in style replacement for pystray on Windows that is
smaller, lighter and does more (numbers below).

## Features

- **Zero dependencies.** Standard library only. Pillow images work as icons, but Pillow is never imported.
- **Its own thread.** A hidden window and message loop on a daemon thread; `start()` returns once the icon shows.
  Or call `run()` to block the current thread.
- **Modern notification area API.** `Shell_NotifyIconW` with NOTIFYICON_VERSION_4, keyboard selection included.
- **Survives Explorer restarts.** The icon re-adds itself on `TaskbarCreated`, and keeps retrying for up to a minute
  when an app starts at logon before the taskbar exists.
- **Sharp on high-DPI screens.** Icons are rendered at the exact size the shell asks for at the current DPI, and
  redrawn when the DPI changes. Menus are per-monitor DPI aware.
- **Live updates.** `update(icon=..., tooltip=...)` from any thread. Converted icons are cached by content, so cycling
  through a few state icons costs a fraction of a millisecond.
- **Real native menus.** Checkboxes, radio items, submenus, separators, a bold default item. Text, checked, enabled
  and visible can be values or functions, evaluated each time the menu opens. Hidden items vanish and stray
  separators collapse. Left click runs the default item, right click opens the menu.
- **Dark mode.** Menus follow Windows' app theme (dark or light), or can be forced either way. Falls back silently
  on Windows versions without dark menus.
- **Toasts with buttons.** Windows toast notifications through WinRT, with up to five buttons and a body click that
  run Python callbacks while your app is running. Falls back to a classic balloon (its click runs one action) when
  toasts are unavailable, for example when notifications are switched off.
- **pystray-friendly API.** `Item(text, action, checked=..., enabled=..., visible=..., default=..., radio=...)`,
  `Menu(*items)`, `Menu(callable)` for dynamic menus, `SEPARATOR`, and callables that take the item or nothing.

## Requirements

- Windows 10 or 11 (tested on Windows 11 build 26200; Windows 10 is supported by the APIs used but untested). Dark menus need Windows 10 1809 or newer; toasts need notifications switched on in Settings.
- Python 3.10 or newer (tested on 3.10, 3.11, 3.12, 3.13 and 3.14)

## Install

```bash
pip install puretech-tray
```

Or from a checkout:

```bash
pip install .
```

## Usage

```python
from puretech_tray import Tray, Menu, Item, SEPARATOR, RGBA

state = {"muted": False, "quality": "high"}

def set_quality(q):
    return lambda: state.update(quality=q)

tray = Tray(
    icon=RGBA(pixels, 64, 64),            # or a Pillow image, or (pixels, (64, 64))
    tooltip="My app",
    menu=Menu(
        Item("Open", lambda: print("open"), default=True),       # bold; also what a left click runs
        SEPARATOR,
        Item("Mute", lambda: state.update(muted=not state["muted"]), checked=lambda item: state["muted"]),
        Item("Quality", Menu(
            Item("High", set_quality("high"), checked=lambda: state["quality"] == "high", radio=True),
            Item("Low", set_quality("low"), checked=lambda: state["quality"] == "low", radio=True),
        )),
        Item(lambda item: f"Muted: {state['muted']}", None, enabled=False),
        SEPARATOR,
        Item("Quit", lambda tray: tray.stop()),
    ),
    app_id="MyCompany.MyApp",            # optional: needed for real toasts (adds a Start menu shortcut)
    app_name="My App",                    # shown as the toast's app name
)
tray.start()                              # or tray.run() to block

tray.update(icon=other_icon, tooltip="My app: busy")
tray.notify("Export finished", "clip.mkv, 12 MB",
            actions=[("Open folder", open_folder), ("Dismiss", lambda: None)],
            on_click=show_window)         # returns "toast" or "balloon"
tray.stop()
```

### API

| Call | What it does |
| --- | --- |
| `Tray(icon, tooltip="", menu=None, on_click=None, app_id=None, *, app_name=None, app_icon=None, app_shortcut=True, theme="auto")` | Create a tray icon. `theme` is `"auto"`, `"dark"`, `"light"` or `None` (leave menus alone; the setting is process-wide). See Toasts for `app_*`. |
| `.start()` / `.run()` | Run on a daemon thread and return, or block the calling thread until `stop()`. |
| `.update(icon=None, tooltip=None)` | Change the icon and/or tooltip (also `tray.icon = ...`, `tray.tooltip = ...`). Any thread. |
| `.notify(title, text="", actions=(), on_click=None, *, silent=False, prefer="toast")` | Show a toast (or a balloon) and return which one was used: `"toast"` or `"balloon"`, or `"queued"` if a menu action has kept the tray thread busy for over 10 seconds (it is shown when the thread is free). `prefer="balloon"` forces a balloon. Any thread. |
| `.refresh_menu()` | Menus are rebuilt on every open; this also refreshes one that is open right now. |
| `.stop()` | Remove the icon and end the thread. Safe from any thread, including a menu action. |
| `.visible`, `.icon_rect()` | Whether the icon is in the notification area, and its screen rectangle (handy for placing a popup). |
| `Item(text, action=None, checked=None, enabled=True, visible=True, default=False, radio=False, submenu=None)` | A menu entry. A `Menu` passed as `action` becomes the submenu, as in pystray. Use `&&` for a literal `&`. |
| `Menu(*items)` / `Menu(fn)` | A menu, or one whose items `fn()` returns each time it opens. |
| `SEPARATOR` | A separator line (also `Menu.SEPARATOR`). |
| `RGBA(data, width, height)` | Raw RGBA pixels as an icon. |
| `ico_bytes(icon, sizes=...)` | A multi-size .ico file as bytes, e.g. for `app_icon`. |
| `register_app_id(id, name, icon_path=None, *, shortcut=True, target=None, arguments=None)` / `unregister_app_id(id)` | Add or remove the per-user toast registration: the `HKCU\Software\Classes\AppUserModelId\<id>` key and the Start menu shortcut carrying the id. `Tray` does this for you. |

Callbacks run on the tray thread. Functions used for text, checked, enabled and visible receive the `Item` if they
take a required argument and nothing otherwise (so `lambda r=rec: ...` keeps its default). Actions receive
`(tray, item)`, `(tray)` or nothing, depending on how many arguments they take.

### Toasts

Windows only shows toasts from a desktop (unpackaged) app when its AppUserModelID belongs to a Start menu
shortcut. When you pass `app_id`, the tray registers it for the current user on the first `notify()`:

- `HKCU\Software\Classes\AppUserModelId\<app_id>` with `DisplayName` (`app_name`) and, if given, `IconUri`
  (`app_icon`, a path to a .ico or .png);
- a Start menu shortcut named after `app_name` that carries the id and starts your app (the frozen .exe, or
  `pythonw.exe` with your main script). A .ico `app_icon` is also the shortcut's icon.

Once registered, later runs only read the registry and check the shortcut file's size and date (no COM, no
extra thread). The first registration runs on a background thread, because Windows takes about 2.5 seconds to
index a new shortcut and drops toasts sent before that: it waits until the id appears in the Apps folder, then
shows the notification, so the tray stays responsive. An existing shortcut that carries another id is never
overwritten.
Pass `app_shortcut=False` if your installer already makes a shortcut with the id. Call
`unregister_app_id(app_id)` from your uninstaller: it removes the key and the shortcut (only if the shortcut still
carries that id).

Buttons and the body click reach your callbacks while the app is running. If Windows reports toasts as disabled
or a toast fails, `notify()` shows a balloon instead; Windows shows balloons as notifications too, so neither
appears while notifications are switched off in Settings.

Memory: nothing toast-related loads until the first `notify()`. A toast loads Windows' notification components
(about 9 MB of working set); once no shown toast can be clicked any more (each was clicked, dismissed or failed),
the tray releases them and Windows unloads them again (about 6 MB back). Toasts that timed out into the
notification center keep their buttons working until they are used or dismissed.

## Compared with pystray

Measured on one machine with `python tools/measure.py --runs 7` against pystray 0.19.5 (with six 1.17.0 and
Pillow 10.4.0), Python 3.13.2, Windows 11 (10.0.26200). Fresh subprocess per sample, libraries alternated,
medians. Raw data: [docs/perf.json](docs/perf.json).

| Metric (median) | pystray 0.19.5 | puretech-tray 0.1.0 | Difference |
| --- | --- | --- | --- |
| Import, cold | 53.2 ms | 25.9 ms | 2.1x faster |
| Import, Pillow already loaded | 21.4 ms | 12.1 ms | 1.8x faster |
| Start to icon visible | 114.0 ms | 27.4 ms | 4.2x faster |
| Private memory added | 5,668 KB | 2,216 KB | 2.6x less |
| Working set added | 9,500 KB | 5,324 KB | 1.8x less |
| Threads added | 1 | 1 | same |
| Icon update, cycling 4 state icons | 2.59 ms | 0.21 ms | 12.2x faster |
| Icon update, cycling 4 state icons (p95) | 3.50 ms | 0.73 ms | 4.8x faster |
| Icon update, never-seen icon | 2.57 ms | 0.24 ms | 10.7x faster |
| Installed size | 176.5 KB (pystray 139.3 + six 37.2) | 101.3 KB | 1.7x smaller |
| Required dependencies | Pillow (5.8 MB installed), six | none | |

Memory and threads are what the tray adds once its icon is visible, after Pillow drew the same test icons for both. Icons were Pillow images for both libraries (pystray only accepts those). Raw RGBA bytes skip Pillow and use a pure-Python area-average resampler instead: about 2.5 ms for 64 to 16 px and 4 ms for 64 to 32 px the first time, then cached.

Feature differences on Windows:

| | pystray 0.19.5 | puretech-tray |
| --- | --- | --- |
| Dependencies | Pillow, six | none |
| Checkboxes, radio items, bold default item, submenus | yes | yes |
| Notification area API | legacy (version 0) | NOTIFYICON_VERSION_4 (keyboard select, anchor coordinates) |
| Dark menus following Windows | no | yes |
| Notifications | balloon only, no callback | toasts with up to 5 buttons and body click, balloon fallback with click |
| Icon sized for the screen DPI | loads one size via a temp .ico file | renders the exact size, redraws on DPI change |
| Explorer restart | re-adds icon | re-adds icon, plus retries while Explorer starts at logon |
| Icon position for popups | no | `icon_rect()` |

## Demo

```bash
python demo.py
```

Left click shows a notification, right click opens a menu with every item type. The demo registers the toast id
`PureTech.TrayDemo` for the current user (an HKCU key and a Start menu shortcut) and removes both when you pick Quit.

## Tests

```bash
pip install pytest
python -m pytest
```

Some tests add a real tray icon for a moment. Set `PURETECH_TRAY_NO_GUI=1` to skip those.

## License

MIT, (C) 2025 Pure Tech. See [LICENSE](LICENSE).
