# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""The menu model. Pure Python: no Windows calls, so it can be tested anywhere.

Text, checked, enabled and visible can be plain values or callables. Callables are evaluated each time the menu
opens and receive the Item if they take a required argument (so pystray-style `lambda item: ...` works), or nothing
if they take none (so `lambda r=rec: ...` keeps its default)."""

def _required_args(fn):
    """How many positional arguments `fn` needs; -1 when it takes *args. Reads the code object directly (fast,
    and avoids importing inspect) and falls back to inspect for other callables."""
    bound = 0
    target = fn
    if hasattr(target, "__func__") and hasattr(target, "__self__"):
        target, bound = target.__func__, 1
    code = getattr(target, "__code__", None)
    if code is not None:
        if code.co_flags & 0x04:                       # CO_VARARGS
            return -1
        return max(0, code.co_argcount - len(getattr(target, "__defaults__", None) or ()) - bound)
    import inspect
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 0
    n = 0
    for p in params:
        if p.kind == p.VAR_POSITIONAL:
            return -1
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty:
            n += 1
    return n

def call_with(fn, *args):
    """Call `fn` with as many of `args` as it requires (all of them for *args)."""
    n = _required_args(fn)
    return fn(*(args if n < 0 else args[:n]))

def _value(v, item):
    return call_with(v, item) if callable(v) else v


class Item:
    """One menu entry.

    Item(text, action=None, checked=None, enabled=True, visible=True, default=False, radio=False, submenu=None)

    - `text`: str or callable returning str.
    - `action`: callable run on the tray thread when chosen; gets (tray, item) if it takes arguments.
      A Menu (or list) passed as `action` is treated as `submenu`, matching pystray's MenuItem.
    - `checked`: None for a plain item, else bool or callable. With `radio=True` the check shows as a dot.
    - `default`: shown bold; it is also what a left click on the icon runs when Tray has no on_click.
    """
    __slots__ = ("text", "action", "checked", "enabled", "visible", "default", "radio", "submenu")
    separator = False

    def __init__(self, text, action=None, checked=None, enabled=True, visible=True, default=False, radio=False,
                 submenu=None):
        if submenu is None and isinstance(action, (Menu, list, tuple)):
            action, submenu = None, action
        if isinstance(submenu, (list, tuple)):
            submenu = Menu(*submenu)
        self.text, self.action, self.checked = text, action, checked
        self.enabled, self.visible, self.default, self.radio, self.submenu = enabled, visible, default, radio, submenu

    def __repr__(self):
        return f"Item({self.text!r})" if not callable(self.text) else "Item(<dynamic>)"


class _Separator(Item):
    separator = True

    def __init__(self):
        super().__init__("")

    def __repr__(self):
        return "SEPARATOR"


class Menu:
    """Menu(*items), or Menu(fn) where fn returns the items each time the menu opens (pystray-compatible)."""

    def __init__(self, *items):
        if len(items) == 1 and callable(items[0]) and not isinstance(items[0], (Item, Menu)):
            self._source = items[0]
            self._items = ()
        else:
            self._source = None
            self._items = items

    @property
    def items(self):
        if self._source is None:
            return tuple(self._items)
        got = call_with(self._source)
        if isinstance(got, Menu):
            return got.items
        return tuple(got or ())

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


SEPARATOR = Menu.SEPARATOR = _Separator()


class Entry:
    """A resolved menu entry: what is on screen right now."""
    __slots__ = ("text", "separator", "enabled", "checked", "checkable", "radio", "default", "item", "children", "id")

    def __init__(self, text="", separator=False, enabled=True, checked=False, checkable=False, radio=False,
                 default=False, item=None, children=None, id=0):
        self.text, self.separator, self.enabled, self.checked, self.checkable = text, separator, enabled, checked, checkable
        self.radio, self.default, self.item, self.children, self.id = radio, default, item, children, id

    def __repr__(self):
        return "Entry(---)" if self.separator else f"Entry({self.text!r}, id={self.id})"

    def shape(self):
        """Structure only (used to decide whether an open menu can be refreshed in place)."""
        return ("-" if self.separator else ">" if self.children is not None else "."), \
               tuple(c.shape() for c in self.children or ())


def resolve(menu, start_id=1):
    """Evaluate every callable in `menu` and return a list of Entry trees with ids assigned depth first.
    Hidden items are dropped, and separators are collapsed (no leading, trailing or doubled ones)."""
    counter = [start_id]
    return _resolve(menu, counter)

def _resolve(menu, counter):
    out = []
    for item in (menu.items if isinstance(menu, Menu) else tuple(menu or ())):
        if item is None:
            continue
        if item.separator:
            if out and not out[-1].separator:
                out.append(Entry(separator=True))
            continue
        if not _value(item.visible, item):
            continue
        checked = _value(item.checked, item)
        e = Entry(text=str(_value(item.text, item) or ""), enabled=bool(_value(item.enabled, item)),
                  checked=bool(checked), checkable=item.checked is not None, radio=bool(item.radio),
                  default=bool(_value(item.default, item)), item=item)
        if item.submenu is not None:
            e.children = _resolve(item.submenu, counter)
        else:
            e.id = counter[0]
            counter[0] += 1
        out.append(e)
    while out and out[-1].separator:
        out.pop()
    return out

def walk(entries):
    for e in entries:
        yield e
        if e.children:
            yield from walk(e.children)

def find_default(entries):
    """The first enabled default item at the top level, or None."""
    for e in entries:
        if e.default and e.enabled and not e.separator and e.children is None:
            return e
    return None
