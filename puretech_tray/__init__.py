# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""A native Windows tray icon in pure ctypes: menus, dark mode, toasts. No dependencies."""

__version__ = "0.1.0"

from .icon import RGBA, ico_bytes
from .menu import SEPARATOR, Item, Menu
from .tray import Tray


def register_app_id(app_id, display_name, icon_path=None, *, shortcut=True, target=None, arguments=None):
    """Register an AppUserModelID for toasts for the current user: an HKCU entry plus, by default, a Start menu
    shortcut carrying the id (see puretech_tray.toast.register_app_id). Returns True if anything changed."""
    from .toast import register_app_id as register
    return register(app_id, display_name, icon_path, shortcut=shortcut, target=target, arguments=arguments)


def unregister_app_id(app_id):
    """Remove an AppUserModelID registered with register_app_id, and its shortcut (for uninstallers)."""
    from .toast import unregister_app_id as unregister
    return unregister(app_id)

__all__ = ["Tray", "Item", "Menu", "SEPARATOR", "RGBA", "ico_bytes", "register_app_id", "unregister_app_id",
           "__version__"]
