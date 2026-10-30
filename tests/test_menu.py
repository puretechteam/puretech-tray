# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

from puretech_tray.menu import SEPARATOR, Item, Menu, call_with, find_default, resolve, walk


def texts(entries):
    return ["---" if e.separator else e.text for e in entries]


def test_static_items_and_ids():
    entries = resolve(Menu(Item("A", None), Item("B", None), Item("Sub", Menu(Item("C", None)))))
    assert texts(entries) == ["A", "B", "Sub"]
    ids = [e.id for e in walk(entries) if e.children is None]
    assert ids == [1, 2, 3] and len(set(ids)) == 3
    assert entries[2].children[0].text == "C" and entries[2].id == 0


def test_callables_get_item_only_when_they_ask_for_it():
    seen = []
    item = Item(lambda it: seen.append(it) or "one-arg", None)
    resolve(Menu(item))
    assert seen == [item]
    assert texts(resolve(Menu(Item(lambda: "no-arg", None)))) == ["no-arg"]


def test_default_argument_is_not_clobbered():
    """pystray passes the item into `lambda r=rec:`; we only pass required arguments."""
    rec = {"name": "cam"}
    entries = resolve(Menu(Item(lambda r=rec: r["name"], None, checked=lambda _, r=rec: r is rec)))
    assert entries[0].text == "cam" and entries[0].checked is True


def test_bound_methods_and_varargs():
    class Box:
        label = "bound"

        def text(self):
            return self.label

        def checked(self, item):
            return isinstance(item, Item)
    b = Box()
    e = resolve(Menu(Item(b.text, None, checked=b.checked)))[0]
    assert (e.text, e.checked) == ("bound", True)
    assert call_with(lambda *a: len(a), "x", "y") == 2


def test_action_arity_matches_pystray():
    assert call_with(lambda: "none", "tray", "item") == "none"
    assert call_with(lambda t: t, "tray", "item") == "tray"
    assert call_with(lambda t, i: (t, i), "tray", "item") == ("tray", "item")


def test_hidden_items_and_separator_collapse():
    m = Menu(SEPARATOR, Item("A", None), SEPARATOR, SEPARATOR, Item("hidden", None, visible=False), SEPARATOR,
             Item("B", None, visible=lambda: True), SEPARATOR, Item("gone", None, visible=lambda: False), SEPARATOR)
    assert texts(resolve(m)) == ["A", "---", "B"]


def test_states_checkbox_radio_default_enabled():
    m = Menu(Item("plain", None), Item("check", None, checked=True), Item("radio", None, checked=lambda: False, radio=True),
             Item("bold", None, default=True), Item("off", None, enabled=False))
    plain, check, radio, bold, off = resolve(m)
    assert not plain.checkable and check.checkable and check.checked
    assert radio.radio and radio.checkable and not radio.checked
    assert bold.default and not off.enabled
    assert find_default([plain, check, radio, bold, off]) is bold


def test_find_default_skips_disabled():
    assert find_default(resolve(Menu(Item("x", None, default=True, enabled=False)))) is None


def test_dynamic_menu_and_submenu_forms():
    state = {"n": 2}
    dyn = Menu(lambda: [Item(f"cam {i}", None) for i in range(state["n"])])
    m = Menu(Item("Cameras", dyn), Item("List", [Item("x", None)]), Item("Kw", None, submenu=Menu(Item("y", None))))
    first = resolve(m)
    assert texts(first[0].children) == ["cam 0", "cam 1"]
    assert texts(first[1].children) == ["x"] and texts(first[2].children) == ["y"]
    state["n"] = 3
    assert texts(resolve(m)[0].children) == ["cam 0", "cam 1", "cam 2"]


def test_menu_from_list_and_compat_separator_alias():
    assert Menu.SEPARATOR is SEPARATOR
    assert len(Menu(Item("a", None), SEPARATOR, Item("b", None))) == 3
    assert texts(resolve([Item("a", None)])) == ["a"]


def test_shape_tracks_structure_only():
    flag = {"on": False}
    m = Menu(Item(lambda: "on" if flag["on"] else "off", None, checked=lambda: flag["on"]), SEPARATOR, Item("x", None))
    before = [e.shape() for e in resolve(m)]
    flag["on"] = True
    assert [e.shape() for e in resolve(m)] == before
