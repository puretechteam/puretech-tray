# puretech-tray - (C) 2025 Pure Tech
# Licensed under the MIT License

import struct

import pytest

from puretech_tray import icon as I


def solid(rgba, w, h):
    return bytes(rgba) * (w * h)


class FakeImage:
    """Quacks like a Pillow image without being one."""
    def __init__(self, data, size, mode="RGBA"):
        self._data, self.size, self.mode = data, size, mode

    def tobytes(self):
        return self._data

    def convert(self, mode):
        assert self.mode == "RGB" and mode == "RGBA"
        rgb = self._data
        return FakeImage(b"".join(rgb[i:i + 3] + b"\xff" for i in range(0, len(rgb), 3)), self.size)


def test_as_rgba_accepts_all_forms():
    data = solid((1, 2, 3, 4), 2, 2)
    assert I.as_rgba((data, (2, 2))) == (data, 2, 2)
    assert I.as_rgba((data, 2, 2)) == (data, 2, 2)
    assert I.as_rgba(I.RGBA(data, 2, 2)) == (data, 2, 2)
    assert I.as_rgba(FakeImage(data, (2, 2))) == (data, 2, 2)
    assert I.as_rgba(FakeImage(b"\x01\x02\x03" * 4, (2, 2), "RGB"))[0] == b"\x01\x02\x03\xff" * 4


def test_as_rgba_rejects_bad_input():
    with pytest.raises(ValueError):
        I.as_rgba((b"\x00" * 15, (2, 2)))
    with pytest.raises(TypeError):
        I.as_rgba(b"\x00" * 16)
    with pytest.raises(ValueError):
        I.as_rgba((b"", (0, 0)))


def test_rgba_to_bgra_swaps_red_and_blue():
    assert I.rgba_to_bgra(bytes([1, 2, 3, 4, 5, 6, 7, 8])) == bytes([3, 2, 1, 4, 7, 6, 5, 8])


def test_resize_identity_and_solid_colour():
    data = solid((10, 20, 30, 255), 8, 8)
    assert I.resize_rgba(data, 8, 8, 8, 8) == data
    assert I.resize_rgba(data, 8, 8, 3, 3) == solid((10, 20, 30, 255), 3, 3)
    assert I.resize_rgba(data, 8, 8, 20, 20) == solid((10, 20, 30, 255), 20, 20)


def test_resize_averages_area():
    # 2x2 -> 1x1: alpha averages, colour is the alpha-weighted mean
    data = bytes([255, 0, 0, 255, 0, 0, 255, 255, 255, 0, 0, 255, 0, 0, 255, 255])
    assert I.resize_rgba(data, 2, 2, 1, 1) == bytes([128, 0, 128, 255])


def test_resize_premultiplied_no_dark_fringe():
    # white opaque next to fully transparent black: the result must stay white, half transparent
    data = bytes([255, 255, 255, 255, 0, 0, 0, 0])
    assert I.resize_rgba(data, 2, 1, 1, 1) == bytes([255, 255, 255, 128])


def test_prepare_is_cached_by_content():
    data = solid((9, 8, 7, 255), 64, 64)
    a = I.prepare((data, 64, 64), 16)
    b = I.prepare(I.RGBA(bytes(data), 64, 64), 16)
    assert a is b and len(a) == 16 * 16 * 4 and a[:4] == bytes([7, 8, 9, 255])


def test_ico_bytes_structure():
    blob = I.ico_bytes((solid((0, 0, 0, 255), 4, 4), 4, 4), sizes=(16, 32))
    reserved, kind, count = struct.unpack_from("<HHH", blob)
    assert (reserved, kind, count) == (0, 1, 2)
    for n, size in enumerate((16, 32)):
        w, h, _, _, planes, bpp, length, offset = struct.unpack_from("<BBBBHHII", blob, 6 + 16 * n)
        assert (w, h, planes, bpp) == (size, size, 1, 32)
        header = struct.unpack_from("<IiiHH", blob, offset)
        assert header == (40, size, size * 2, 1, 32)
        assert length == 40 + size * size * 4 + ((size + 31) // 32) * 4 * size
    assert offset + length == len(blob)


def test_make_hicon_real_handle():
    from puretech_tray import _win32 as W
    h = I.make_hicon(I.prepare((solid((255, 0, 0, 255), 32, 32), 32, 32), 20), 20, 20)
    assert h
    assert W.DestroyIcon(h)


def test_pillow_image_if_available():
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGB", (8, 8), (0, 128, 255))
    data, w, h = I.as_rgba(img)
    assert (w, h) == (8, 8) and data[:4] == bytes([0, 128, 255, 255])


def test_pillow_resize_path_matches_pure_path():
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    img.paste((255, 77, 94, 255), (16, 16, 48, 48))
    via_pillow = I.prepare(img, 16)
    pure = I.rgba_to_bgra(I.resize_rgba(img.tobytes(), 64, 64, 16, 16))
    assert len(via_pillow) == len(pure)
    assert max(abs(a - b) for a, b in zip(via_pillow, pure)) <= 1


def test_object_resize_failure_falls_back_to_pure():
    class Broken(FakeImage):
        def resize(self, size, resample):
            raise RuntimeError("no")
    data = solid((5, 6, 7, 255), 8, 8)
    assert I.prepare(Broken(data, (8, 8)), 4) == solid((7, 6, 5, 255), 4, 4)
