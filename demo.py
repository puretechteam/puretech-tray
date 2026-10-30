# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Try every feature: run `python demo.py`, then left click, right click and pick things from the menu.

The demo registers the toast id PureTech.TrayDemo for the current user (an HKCU key and a "Pure Tech Tray Demo"
Start menu shortcut) and removes both again on Quit."""

import math
import os
import tempfile

from puretech_tray import RGBA, SEPARATOR, Item, Menu, Tray, ico_bytes, unregister_app_id

APP_ID = "PureTech.TrayDemo"
COLORS = {"red": (255, 77, 94), "amber": (251, 191, 36), "violet": (167, 139, 250), "grey": (140, 147, 161)}


def dot_icon(color, size=64):
    """A dark ring with a coloured dot, drawn without Pillow (anti-aliased by distance)."""
    px = bytearray(size * size * 4)
    c = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            o = (y * size + x) * 4
            outer = max(0.0, min(1.0, size * 0.47 - d))
            inner = max(0.0, min(1.0, size * 0.22 - d))
            if outer:
                ring = 1.0 if d > size * 0.47 - 3 else 0.0
                base = (42, 47, 56) if ring else (14, 16, 20)
                r, g, b = (int(base[i] * (1 - inner) + color[i] * inner) for i in range(3))
                px[o:o + 4] = bytes((r, g, b, int(255 * outer)))
    return RGBA(px, size, size)


class Demo:
    def __init__(self):
        self.color = "red"
        self.muted = False
        self.count = 0
        self.icons = {name: dot_icon(rgb) for name, rgb in COLORS.items()}
        self.ico_path = os.path.join(tempfile.gettempdir(), "puretech-tray-demo.ico")
        with open(self.ico_path, "wb") as f:
            f.write(ico_bytes(self.icons["red"]))
        self.tray = Tray(self.icons["red"], "Pure Tech tray demo", Menu(
            Item("Show a notification", self.toast, default=True),
            Item("Show a balloon", self.balloon),
            SEPARATOR,
            Item("Mute sounds", self.toggle_mute, checked=lambda item: self.muted),
            Item("Colour", Menu(*[Item(name.title(), self.pick(name), checked=self.is_color(name), radio=True)
                                  for name in COLORS])),
            Item(lambda item: f"Clicked {self.count} times", None, enabled=False),
            Item("Only when muted", None, visible=lambda: self.muted, enabled=False),
            SEPARATOR,
            Item("Quit", self.quit),
        ), app_id=APP_ID, app_name="Pure Tech Tray Demo", app_icon=self.ico_path)

    def pick(self, name):
        def choose():
            self.color = name
            self.tray.update(icon=self.icons[name], tooltip=f"Pure Tech tray demo: {name}")
        return choose

    def is_color(self, name):
        return lambda: self.color == name

    def toggle_mute(self):
        self.muted = not self.muted

    def clicked(self, what):
        def run():
            self.count += 1
            self.tray.update(tooltip=f"Pure Tech tray demo: {what}")
            print("clicked:", what)
        return run

    def toast(self):
        how = self.tray.notify("Recording saved", "clip-0042.mkv, 12 MB",
                               actions=[("Open folder", self.clicked("Open folder")), ("Dismiss", self.clicked("Dismiss"))],
                               on_click=self.clicked("toast body"), silent=self.muted)
        print("notification shown as a", how)

    def balloon(self):
        self.tray.notify("Balloon", "Click me", on_click=self.clicked("balloon"), silent=self.muted, prefer="balloon")

    def quit(self):
        self.tray.stop()


if __name__ == "__main__":
    demo = Demo()
    try:
        demo.tray.run()
    finally:
        if unregister_app_id(APP_ID):
            print("removed", APP_ID, "from HKCU")
        try:
            os.remove(demo.ico_path)
        except OSError:
            pass
