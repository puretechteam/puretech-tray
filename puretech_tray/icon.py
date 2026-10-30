# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

"""RGBA pixels to Windows icons. Accepts raw bytes plus a size, or anything with .tobytes() and .size in RGBA
(a Pillow image works; Pillow itself is never imported)."""

import ctypes
import struct
from collections import OrderedDict

_CACHE = OrderedDict()          # (rgba, w, h, tw, th) -> BGRA bytes; tray icons cycle through a few states
_CACHE_SIZE = 16


class RGBA:
    """Raw RGBA pixels: RGBA(data, width, height)."""
    __slots__ = ("data", "width", "height")

    def __init__(self, data, width, height):
        self.data, self.width, self.height = bytes(data), int(width), int(height)

    @property
    def size(self):
        return self.width, self.height

    def tobytes(self):
        return self.data


def as_rgba(icon):
    """Normalize an icon to (bytes, width, height). Accepts RGBA(...), (data, (w, h)), (data, w, h) or an object
    with .tobytes() and .size (converted with .convert('RGBA') first if it has another .mode)."""
    if isinstance(icon, (tuple, list)):
        if len(icon) == 2:
            data, (w, h) = icon
        elif len(icon) == 3:
            data, w, h = icon
        else:
            raise ValueError("icon tuple must be (data, (width, height)) or (data, width, height)")
    elif hasattr(icon, "tobytes") and hasattr(icon, "size"):
        mode = getattr(icon, "mode", "RGBA")
        if mode != "RGBA":
            if not hasattr(icon, "convert"):
                raise ValueError(f"icon mode is {mode!r}, expected 'RGBA'")
            icon = icon.convert("RGBA")
        data, (w, h) = icon.tobytes(), icon.size
    else:
        raise TypeError("icon must be RGBA bytes with a size, or an object with .tobytes() and .size")
    data, w, h = bytes(data), int(w), int(h)
    if w <= 0 or h <= 0 or len(data) != w * h * 4:
        raise ValueError(f"expected {w}x{h}x4 = {max(w * h * 4, 0)} bytes of RGBA, got {len(data)}")
    return data, w, h


def _taps(src, dst):
    """For each destination pixel, the (source index, weight) pairs of an area-average filter."""
    scale = src / dst
    out = []
    for i in range(dst):
        lo, hi = i * scale, (i + 1) * scale
        taps = []
        j = int(lo)
        while j < hi and j < src:
            w = min(hi, j + 1) - max(lo, j)
            if w > 1e-9:
                taps.append((j, w / scale))
            j += 1
        out.append(taps)
    return out


def resize_rgba(data, w, h, tw, th):
    """Area-average resample with premultiplied alpha, so transparent pixels do not bleed dark fringes."""
    if (w, h) == (tw, th):
        return bytes(data)
    a = data[3::4]
    chans = [[c * al for c, al in zip(data[k::4], a)] for k in range(3)] + [list(a)]
    xt, yt = _taps(w, tw), _taps(h, th)
    out_chans = []
    for c in chans:
        rows = [[sum(c[base + j] * wt for j, wt in taps) for taps in xt] for base in range(0, w * h, w)]
        out_chans.append([sum(rows[j][x] * wt for j, wt in taps) for taps in yt for x in range(tw)])
    pr, pg, pb, pa = out_chans
    out = bytearray(tw * th * 4)
    for i, al in enumerate(pa):
        if al >= 0.5:
            o = i * 4
            out[o] = min(255, int(pr[i] / al + 0.5))
            out[o + 1] = min(255, int(pg[i] / al + 0.5))
            out[o + 2] = min(255, int(pb[i] / al + 0.5))
            out[o + 3] = min(255, int(al + 0.5))
    return bytes(out)


def rgba_to_bgra(data):
    """Swap R and B (Windows DIBs are BGRA)."""
    out = bytearray(data)
    out[0::4], out[2::4] = data[2::4], data[0::4]
    return bytes(out)


def prepare(icon, size):
    """Icon -> BGRA bytes at size x size, cached by content."""
    data, w, h = as_rgba(icon)
    key = (data, w, h, size)
    got = _CACHE.get(key)
    if got is not None:
        _CACHE.move_to_end(key)
        return got
    small = None
    if (w, h) != (size, size) and callable(getattr(icon, "resize", None)) and hasattr(icon, "tobytes"):
        try:                      # the image's own resampler (Pillow's is C, premultiplied); 4 = BOX, an area average
            small = as_rgba(icon.resize((size, size), 4))[0]
        except Exception:
            small = None
    got = rgba_to_bgra(small if small is not None else resize_rgba(data, w, h, size, size))
    _CACHE[key] = got
    if len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return got


def make_hicon(bgra, w, h):
    """CreateIconIndirect from straight-alpha BGRA pixels. Caller owns the HICON (DestroyIcon)."""
    from . import _win32 as W
    bmi = W.BITMAPINFOHEADER(ctypes.sizeof(W.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    color = W.CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not color:
        raise OSError(ctypes.get_last_error(), "CreateDIBSection failed")
    try:
        ctypes.memmove(bits, bgra, w * h * 4)
        mask_bytes = ctypes.create_string_buffer(((w + 15) // 16) * 2 * h)
        mask = W.CreateBitmap(w, h, 1, 1, mask_bytes)
        try:
            info = W.ICONINFO(True, 0, 0, mask, color)
            hicon = W.CreateIconIndirect(ctypes.byref(info))
        finally:
            W.DeleteObject(mask)
    finally:
        W.DeleteObject(color)
    if not hicon:
        raise OSError(ctypes.get_last_error(), "CreateIconIndirect failed")
    return hicon


def ico_bytes(icon, sizes=(16, 24, 32, 48, 256)):
    """A .ico file (32-bit BMP entries) with the given sizes, e.g. for a toast IconUri."""
    data, w, h = as_rgba(icon)
    images = []
    for s in sizes:
        bgra = rgba_to_bgra(resize_rgba(data, w, h, s, s))
        stride = s * 4
        pixels = b"".join(bgra[y * stride:(y + 1) * stride] for y in range(s - 1, -1, -1))     # bottom-up
        mask = bytes(((s + 31) // 32) * 4 * s)
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
        images.append((s, header + pixels + mask))
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, blob in images:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return out + b"".join(blob for _, blob in images)
