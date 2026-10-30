# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

import pytest

from puretech_tray import shortcut


@pytest.fixture(autouse=True)
def no_real_start_menu(tmp_path, monkeypatch):
    """No test may write to the real Start menu: shortcuts go to a temp folder."""
    folder = tmp_path / "Programs"
    monkeypatch.setattr(shortcut, "start_menu_folder", lambda: str(folder))
    return folder
