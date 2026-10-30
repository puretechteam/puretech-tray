# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""Manual toast check: shows a toast with two buttons and waits for you to click one.

    python tools/toast_check.py

Registers the test id PureTech.TrayDemo under HKCU, with a "Pure Tech Tray Demo" Start menu shortcut, for the run
and always removes both again."""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from puretech_tray import RGBA, Tray, unregister_app_id  # noqa: E402
from puretech_tray.toast import app_id_info  # noqa: E402

APP_ID = "PureTech.TrayDemo"


def main():
    clicked = threading.Event()
    result = {}

    def pressed(what):
        def run():
            result["button"], result["thread"] = what, threading.current_thread().name
            clicked.set()
        return run

    tray = Tray(RGBA(bytes((255, 77, 94, 255)) * (32 * 32), 32, 32), "puretech-tray toast check",
                app_id=APP_ID, app_name="Pure Tech Tray Demo").start()
    try:
        how = tray.notify("puretech-tray toast check", "Click a button (60 s)",
                          actions=[("Button A", pressed("Button A")), ("Button B", pressed("Button B"))],
                          on_click=pressed("toast body"))
        print("shown as:", how, "| Windows setting:", tray._toaster.setting() if tray._toaster else "n/a")
        print("Start menu shortcut:", (app_id_info(APP_ID) or {}).get("Shortcut"), flush=True)
        if clicked.wait(60):
            print(f"callback ran: {result['button']} (on thread {result['thread']})")
        else:
            print("no click within 60 s")
    finally:
        tray.stop()
        lnk = (app_id_info(APP_ID) or {}).get("Shortcut")
        removed = unregister_app_id(APP_ID)
        print("test app id removed:", removed, "| still registered:", app_id_info(APP_ID) is not None,
              "| shortcut still on disk:", bool(lnk and os.path.exists(lnk)))


if __name__ == "__main__":
    main()
