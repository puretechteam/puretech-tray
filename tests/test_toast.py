# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

import os
import time
import uuid
import winreg
import xml.etree.ElementTree as ET

import pytest

from puretech_tray import toast as T


def test_xml_basic_and_escaping():
    xml = T.build_toast_xml('Saved <"clip">', "A & B", launch="ptt:1:click")
    root = ET.fromstring(xml)
    assert root.tag == "toast" and root.get("launch") == "ptt:1:click" and root.get("activationType") == "foreground"
    texts = [t.text for t in root.iter("text")]
    assert texts == ['Saved <"clip">', "A & B"]
    assert root.find("visual/binding").get("template") == "ToastGeneric"
    assert root.find("actions") is None and root.find("audio") is None


def test_xml_actions_capped_at_five_and_silent():
    xml = T.build_toast_xml("t", actions=[(f"b{i}", f"ptt:k:{i}") for i in range(7)], silent=True)
    root = ET.fromstring(xml)
    acts = root.findall("actions/action")
    assert [a.get("content") for a in acts] == ["b0", "b1", "b2", "b3", "b4"]
    assert acts[2].get("arguments") == "ptt:k:2" and acts[0].get("activationType") == "foreground"
    assert root.find("audio").get("silent") == "true"
    assert root.get("launch") is None and len(root.findall("visual/binding/text")) == 1


def test_xml_image_and_quotes_in_labels():
    root = ET.fromstring(T.build_toast_xml("t", "x", actions=[('Say "hi"', "a")], image="C:\\a b\\i.png"))
    assert root.find("actions/action").get("content") == 'Say "hi"'
    assert root.find("visual/binding/image").get("src") == "C:\\a b\\i.png"


def test_parameterized_iids_match_windows_sdk():
    # values from windows.ui.notifications.h (Windows SDK 10.0.22621)
    assert T.pinterface_iid(T.ACTIVATED_SIGNATURE) == "ab54de2d-97d9-5528-b6ad-105afe156530"
    assert T.pinterface_iid(T.DISMISSED_SIGNATURE) == "61c2402f-0ed0-5a18-ab69-59f4aa99a368"
    assert T.pinterface_iid(T.FAILED_SIGNATURE) == "95e3e803-c969-5e3a-9753-ea2ad22a9a33"
    assert (T.ACTIVATED_IID, T.DISMISSED_IID, T.FAILED_IID) == tuple(
        T.pinterface_iid(sig) for sig in (T.ACTIVATED_SIGNATURE, T.DISMISSED_SIGNATURE, T.FAILED_SIGNATURE))


@pytest.fixture
def temp_base():
    base = rf"Software\PureTechTrayTest-{uuid.uuid4().hex[:8]}"
    yield base
    T._delete_tree(winreg.HKEY_CURRENT_USER, base)
    with pytest.raises(FileNotFoundError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, base)


def test_registry_register_update_unregister(temp_base):
    path = temp_base + r"\PureTech.Test"
    assert T.register_app_id("PureTech.Test", "Test App", r"C:\x\icon.ico", shortcut=False, base=temp_base) is True
    assert T.app_id_info("PureTech.Test", base=temp_base) == {"DisplayName": "Test App", "IconUri": r"C:\x\icon.ico"}
    assert T.register_app_id("PureTech.Test", "Test App", r"C:\x\icon.ico", shortcut=False, base=temp_base) is False
    T.register_app_id("PureTech.Test", "Renamed", shortcut=False, base=temp_base)    # no icon: IconUri is removed
    assert T.app_id_info("PureTech.Test", base=temp_base) == {"DisplayName": "Renamed"}
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, path + r"\Child")          # subkeys are removed too
    assert T.unregister_app_id("PureTech.Test", base=temp_base) is True
    assert T.app_id_info("PureTech.Test", base=temp_base) is None
    assert T.unregister_app_id("PureTech.Test", base=temp_base) is False


def test_register_creates_shortcut_and_unregister_removes_it(temp_base, no_real_start_menu):
    from puretech_tray import shortcut as S
    assert T.register_app_id("PureTech.Test", "Test: App", r"C:\x\icon.ico", target=r"C:\Apps\test.exe",
                             arguments="--tray", base=temp_base) is True
    lnk = str(no_real_start_menu / "Test_ App.lnk")
    assert T.app_id_info("PureTech.Test", base=temp_base)["Shortcut"] == lnk
    info = S.read_shortcut(lnk)
    assert info == {"app_id": "PureTech.Test", "target": r"C:\Apps\test.exe", "arguments": "--tray",
                    "icon": r"C:\x\icon.ico"}
    stamp = os.path.getmtime(lnk)
    assert T.register_app_id("PureTech.Test", "Test: App", r"C:\x\icon.ico", target=r"C:\Apps\test.exe",
                             arguments="--tray", base=temp_base) is False            # nothing rewritten
    assert os.path.getmtime(lnk) == stamp
    T.register_app_id("PureTech.Test", "New Name", target=r"C:\Apps\test.exe", base=temp_base)   # renamed: old .lnk goes
    assert not os.path.exists(lnk) and os.path.exists(str(no_real_start_menu / "New Name.lnk"))
    assert T.unregister_app_id("PureTech.Test", base=temp_base) is True
    assert os.listdir(no_real_start_menu) == []


def test_register_never_takes_over_someone_elses_shortcut(temp_base, no_real_start_menu):
    from puretech_tray import shortcut as S
    other = str(no_real_start_menu / "Shared.lnk")
    S.create_shortcut(other, "Someone.Else", r"C:\Apps\other.exe")
    with pytest.raises(FileExistsError):
        T.register_app_id("PureTech.Test", "Shared", target=r"C:\Apps\test.exe", base=temp_base)
    assert not S.remove_shortcut(other, "PureTech.Test")
    assert S.read_shortcut(other)["app_id"] == "Someone.Else"


def test_shortcut_names_and_default_target(no_real_start_menu):
    from puretech_tray import shortcut as S
    assert S.shortcut_path('a<b>:c"d/e\\f|g?h*', "X") == os.path.join("X", "a_b__c_d_e_f_g_h_.lnk")
    assert S.shortcut_path(" . ", "X") == os.path.join("X", "App.lnk")
    exe, args, workdir = S.default_target()
    assert os.path.isfile(exe) and exe.lower().endswith(("pythonw.exe", "python.exe", ".exe"))
    assert os.path.isdir(workdir)


def test_default_target_for_python_dash_m(monkeypatch, tmp_path):
    """`python -m framekeep` must give `pythonw -m framekeep` from the same folder, not the __main__.py path
    (running __main__.py directly breaks the package's relative imports)."""
    import sys
    import types
    from puretech_tray import shortcut as S
    monkeypatch.chdir(tmp_path)
    main = types.SimpleNamespace(__spec__=types.SimpleNamespace(name="framekeep.__main__"))
    monkeypatch.setitem(sys.modules, "__main__", main)
    exe, args, workdir = S.default_target()
    assert args == "-m framekeep" and workdir == str(tmp_path)
    main.__spec__.name = "tool"                              # python -m tool (a plain module)
    assert S.default_target()[1] == "-m tool"
    script = tmp_path / "app.pyw"
    script.write_text("")
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(__spec__=None))
    monkeypatch.setattr(sys, "argv", [str(script)])
    exe, args, workdir = S.default_target()
    assert args == f'"{script}"' and workdir == str(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert S.default_target() == (sys.executable, "", os.path.dirname(sys.executable))


def test_registered_shortcut_gets_the_working_folder(temp_base, no_real_start_menu, monkeypatch, tmp_path):
    import sys
    import types
    from puretech_tray import shortcut as S
    seen = {}
    real = S.create_shortcut

    def spy(path, app_id, target, arguments="", description="", icon_path=None, working_dir=None):
        seen["working_dir"] = working_dir
        return real(path, app_id, target, arguments, description, icon_path, working_dir)
    monkeypatch.setattr(S, "create_shortcut", spy)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(__spec__=types.SimpleNamespace(name="pkg.__main__")))
    T.register_app_id("PureTech.Test", "Dash M", base=temp_base)
    assert seen["working_dir"] == str(tmp_path)
    assert S.read_shortcut(T.app_id_info("PureTech.Test", base=temp_base)["Shortcut"])["arguments"] == "-m pkg"
    T.unregister_app_id("PureTech.Test", base=temp_base)


def test_toast_keys_never_repeat():
    keys = {T._next_key() for _ in range(1000)}
    assert len(keys) == 1000


def test_registry_rejects_bad_ids(temp_base):
    for bad in ("", "a\\b"):
        with pytest.raises(ValueError):
            T.register_app_id(bad, "x", base=temp_base)
        with pytest.raises(ValueError):
            T.unregister_app_id(bad, base=temp_base)


def test_hstring_round_trip():
    with T.HString("Pure Tech ✓") as h:
        assert T.hstring_text(h) == "Pure Tech ✓"


def test_winrt_notifier_opens_without_registration():
    """The WinRT chain (factories, notifier, setting) works through ctypes; no registry write needed."""
    t = T.Toaster("PureTech.UnitTest." + uuid.uuid4().hex[:6], post=lambda fn: fn())
    try:
        status = t.open()
        assert t.notifier and t.factory
        # Windows reports "unknown" for an id it has never seen while notifications are on
        assert status in (*T.NOTIFICATION_SETTINGS.values(), "unknown")
    finally:
        t.close()


def test_unknown_app_is_not_indexed():
    from puretech_tray import shortcut as S
    app = "PureTech.NeverRegistered" + uuid.uuid4().hex[:8]
    assert S.app_indexed(app) is False
    start = time.monotonic()
    assert S.wait_indexed(app, timeout=0.2) is False
    assert time.monotonic() - start < 2


def test_app_id_ready_is_a_cheap_exact_check(temp_base, no_real_start_menu):
    kw = dict(target=r"C:\Apps\test.exe", arguments="--tray", base=temp_base)
    assert not T.app_id_ready("PureTech.Test", "Test App", **kw)
    T.register_app_id("PureTech.Test", "Test App", **kw)
    assert T.app_id_ready("PureTech.Test", "Test App", **kw)
    assert T.register_app_id("PureTech.Test", "Test App", **kw) is False
    assert not T.app_id_ready("PureTech.Test", "Other Name", **kw)
    assert not T.app_id_ready("PureTech.Test", "Test App", **{**kw, "arguments": "--other"})
    lnk = T.app_id_info("PureTech.Test", base=temp_base)["Shortcut"]
    st = os.stat(lnk)
    os.utime(lnk, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))      # someone touched the shortcut
    assert not T.app_id_ready("PureTech.Test", "Test App", **kw)
    assert T.register_app_id("PureTech.Test", "Test App", **kw) is True  # re-verified through COM, marker updated
    assert T.app_id_ready("PureTech.Test", "Test App", **kw)
    os.remove(lnk)
    assert not T.app_id_ready("PureTech.Test", "Test App", **kw)
    T.unregister_app_id("PureTech.Test", base=temp_base)


def test_light_imports():
    """Importing the package and the toast module must not pull in heavy stdlib modules (ssl alone is megabytes)."""
    import subprocess, sys
    code = ("import sys, puretech_tray, puretech_tray.toast, puretech_tray.shortcut; "
            "print(sorted(m for m in ('ssl', 'socket', 'urllib.request', 'hashlib', 'uuid', 'xml.sax.saxutils', "
            "'bz2', 'lzma', 'inspect', 'logging') if m in sys.modules))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=60)
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
