"""cairo(Frame の SteamOS に入っている libcairo.so.2)を ctypes で使う最小の描画部品。標準ライブラリだけ。"""
import ctypes
import ctypes.util
import math

FONT = "Noto Sans CJK JP"


def _load():
    for name in ("libcairo.so.2", ctypes.util.find_library("cairo") or ""):
        if name:
            try:
                return ctypes.CDLL(name)
            except OSError:
                continue
    raise OSError("libcairo.so.2 が見つかりません")


_c = None


def lib():
    global _c
    if _c is None:
        c = _load()
        vp, d, i = ctypes.c_void_p, ctypes.c_double, ctypes.c_int
        sigs = {
            "cairo_image_surface_create": (vp, [i, i, i]),
            "cairo_image_surface_create_from_png": (vp, [ctypes.c_char_p]),
            "cairo_image_surface_get_data": (ctypes.POINTER(ctypes.c_ubyte), [vp]),
            "cairo_image_surface_get_stride": (i, [vp]),
            "cairo_image_surface_get_width": (i, [vp]),
            "cairo_image_surface_get_height": (i, [vp]),
            "cairo_surface_status": (i, [vp]),
            "cairo_surface_flush": (None, [vp]),
            "cairo_surface_destroy": (None, [vp]),
            "cairo_surface_write_to_png": (i, [vp, ctypes.c_char_p]),
            "cairo_create": (vp, [vp]),
            "cairo_destroy": (None, [vp]),
            "cairo_save": (None, [vp]),
            "cairo_restore": (None, [vp]),
            "cairo_translate": (None, [vp, d, d]),
            "cairo_scale": (None, [vp, d, d]),
            "cairo_set_source_rgba": (None, [vp, d, d, d, d]),
            "cairo_set_source": (None, [vp, vp]),
            "cairo_set_source_surface": (None, [vp, vp, d, d]),
            "cairo_pattern_create_linear": (vp, [d, d, d, d]),
            "cairo_pattern_add_color_stop_rgba": (None, [vp, d, d, d, d, d]),
            "cairo_pattern_destroy": (None, [vp]),
            "cairo_new_path": (None, [vp]),
            "cairo_new_sub_path": (None, [vp]),
            "cairo_close_path": (None, [vp]),
            "cairo_arc": (None, [vp, d, d, d, d, d]),
            "cairo_rectangle": (None, [vp, d, d, d, d]),
            "cairo_fill": (None, [vp]),
            "cairo_fill_preserve": (None, [vp]),
            "cairo_clip": (None, [vp]),
            "cairo_paint": (None, [vp]),
            "cairo_set_line_width": (None, [vp, d]),
            "cairo_stroke": (None, [vp]),
            "cairo_select_font_face": (None, [vp, ctypes.c_char_p, i, i]),
            "cairo_set_font_size": (None, [vp, d]),
            "cairo_move_to": (None, [vp, d, d]),
            "cairo_show_text": (None, [vp, ctypes.c_char_p]),
            "cairo_text_extents": (None, [vp, ctypes.c_char_p, vp]),
        }
        for n, (res, args) in sigs.items():
            f = getattr(c, n)
            f.restype, f.argtypes = res, args
        _c = c
    return _c


class _Extents(ctypes.Structure):
    _fields_ = [("x_bearing", ctypes.c_double), ("y_bearing", ctypes.c_double), ("width", ctypes.c_double),
                ("height", ctypes.c_double), ("x_advance", ctypes.c_double), ("y_advance", ctypes.c_double)]


def hexcolor(h, a=1.0):
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, a


class Canvas:
    """幅 w・高さ h の画像に描く。座標は左上が原点の px。"""

    def __init__(self, w, h):
        self.c = lib()
        self.w, self.h = w, h
        self.surf = self.c.cairo_image_surface_create(0, w, h)  # CAIRO_FORMAT_ARGB32
        if self.c.cairo_surface_status(self.surf) != 0:
            raise OSError("cairo の画像が作れません")
        self.cr = self.c.cairo_create(self.surf)
        self._logos = {}

    def close(self):
        for s in self._logos.values():
            self.c.cairo_surface_destroy(s)
        self._logos = {}
        self.c.cairo_destroy(self.cr)
        self.c.cairo_surface_destroy(self.surf)

    # ---- 図形
    def _rrect_path(self, x, y, w, h, r):
        c, cr = self.c, self.cr
        r = min(r, w / 2.0, h / 2.0)
        c.cairo_new_sub_path(cr)
        c.cairo_arc(cr, x + w - r, y + r, r, -math.pi / 2, 0)
        c.cairo_arc(cr, x + w - r, y + h - r, r, 0, math.pi / 2)
        c.cairo_arc(cr, x + r, y + h - r, r, math.pi / 2, math.pi)
        c.cairo_arc(cr, x + r, y + r, r, math.pi, 3 * math.pi / 2)
        c.cairo_close_path(cr)

    def rrect(self, x, y, w, h, r, color=None, gradient=None, alpha=1.0):
        """角丸の四角。color は #RRGGBB、gradient は (上の色, 下の色)。"""
        c, cr = self.c, self.cr
        self._rrect_path(x, y, w, h, r)
        if gradient:
            pat = c.cairo_pattern_create_linear(0, y, 0, y + h)
            c.cairo_pattern_add_color_stop_rgba(pat, 0, *hexcolor(gradient[0], alpha))
            c.cairo_pattern_add_color_stop_rgba(pat, 1, *hexcolor(gradient[1], alpha))
            c.cairo_set_source(cr, pat)
            c.cairo_fill(cr)
            c.cairo_pattern_destroy(pat)
        else:
            c.cairo_set_source_rgba(cr, *hexcolor(color or "#ffffff", alpha))
            c.cairo_fill(cr)

    def rect_gradient(self, x, y, w, h, top, bottom):
        c, cr = self.c, self.cr
        pat = c.cairo_pattern_create_linear(0, y, 0, y + h)
        c.cairo_pattern_add_color_stop_rgba(pat, 0, *hexcolor(top))
        c.cairo_pattern_add_color_stop_rgba(pat, 1, *hexcolor(bottom))
        c.cairo_new_path(cr)
        c.cairo_rectangle(cr, x, y, w, h)
        c.cairo_set_source(cr, pat)
        c.cairo_fill(cr)
        c.cairo_pattern_destroy(pat)

    def circle(self, cx, cy, r, color, alpha=1.0):
        c, cr = self.c, self.cr
        c.cairo_new_path(cr)
        c.cairo_arc(cr, cx, cy, r, 0, 2 * math.pi)
        c.cairo_set_source_rgba(cr, *hexcolor(color, alpha))
        c.cairo_fill(cr)

    # ---- 文字
    def _font(self, size, bold):
        self.c.cairo_select_font_face(self.cr, FONT.encode(), 0, 1 if bold else 0)
        self.c.cairo_set_font_size(self.cr, size)

    def text_width(self, s, size, bold=False):
        self._font(size, bold)
        e = _Extents()
        self.c.cairo_text_extents(self.cr, s.encode(), ctypes.byref(e))
        return e.x_advance

    def text(self, s, x, y, size, color="#ffffff", bold=False, align="left", alpha=1.0):
        """y は文字のベースライン。align: left / center / right(x が左端 / 中心 / 右端)。"""
        if not s:
            return 0
        w = self.text_width(s, size, bold)
        if align == "center":
            x -= w / 2.0
        elif align == "right":
            x -= w
        self.c.cairo_set_source_rgba(self.cr, *hexcolor(color, alpha))
        self.c.cairo_move_to(self.cr, x, y)
        self.c.cairo_show_text(self.cr, s.encode())
        return w

    def wrap(self, s, size, maxw, bold=False):
        """日本語は 1 文字ずつ、改行文字では必ず改行して、maxw に収まる行のリストにする。"""
        lines = []
        for para in s.split("\n"):
            cur = ""
            for ch in para:
                if cur and self.text_width(cur + ch, size, bold) > maxw:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
        return lines

    def paragraph(self, s, x, y, size, maxw, color="#ffffff", bold=False, align="left", line_h=None, max_lines=None):
        """折り返して描き、次の行の y を返す。y は最初の行のベースライン。"""
        line_h = line_h or size * 1.45
        lines = self.wrap(s, size, maxw, bold)
        if max_lines:
            lines = lines[:max_lines]
        ax = {"left": x, "center": x + maxw / 2.0, "right": x + maxw}[align]
        for ln in lines:
            self.text(ln, ax, y, size, color, bold, align)
            y += line_h
        return y

    def image(self, path, x, y, size):
        """正方形の PNG(ロゴ)を size px で描く。読めなければ何もしない。"""
        c, cr = self.c, self.cr
        s = self._logos.get(path)
        if s is None:
            s = c.cairo_image_surface_create_from_png(path.encode())
            if c.cairo_surface_status(s) != 0:
                c.cairo_surface_destroy(s)
                self._logos[path] = 0
                return
            self._logos[path] = s
        if not s:
            return
        w = c.cairo_image_surface_get_width(s)
        c.cairo_save(cr)
        c.cairo_translate(cr, x, y)
        c.cairo_scale(cr, size / float(w), size / float(c.cairo_image_surface_get_height(s)))
        c.cairo_set_source_surface(cr, s, 0, 0)
        c.cairo_paint(cr)
        c.cairo_restore(cr)

    # ---- 出力
    def _raw(self):
        """cairo の画像データ(ARGB32 = リトルエンディアンでは B,G,R,A の順・隙間なし)の bytearray。"""
        c = self.c
        c.cairo_surface_flush(self.surf)
        stride = c.cairo_image_surface_get_stride(self.surf)
        n = stride * self.h
        raw = bytearray(ctypes.string_at(c.cairo_image_surface_get_data(self.surf), n))
        if stride != self.w * 4:
            rows = [raw[r * stride:r * stride + self.w * 4] for r in range(self.h)]
            raw = bytearray(b"".join(rows))
        return raw

    def rgba_bytes(self):
        """OpenVR に渡す RGBA(上の行から、隙間なし)の bytearray。全面を不透明で塗っておくこと(premultiplied を気にしないため)。"""
        raw = self._raw()
        # cairo の ARGB32(リトルエンディアンでは B,G,R,A の順)→ RGBA
        raw[0::4], raw[2::4] = raw[2::4], raw[0::4]
        return raw

    def rgba_solid(self, color):
        """単色(color)だけで描いた半透明の図形・文字を、OpenVR に渡せる RGBA(色は color のまま、透明度だけ変わる)にする。

        cairo の画像は「色×透明度」を掛けた形(premultiplied)なので、そのまま渡すと縁が黒ずむ。
        単色なら、透明度(A)だけ取り出して、色は全部の画素で color にすればよい。
        """
        a = self._raw()[3::4]
        r, g, b, _ = hexcolor(color)
        n = len(a)
        out = bytearray(n * 4)
        out[0::4] = bytes([round(r * 255)]) * n
        out[1::4] = bytes([round(g * 255)]) * n
        out[2::4] = bytes([round(b * 255)]) * n
        out[3::4] = a
        return out

    def save_png(self, path):
        self.c.cairo_surface_flush(self.surf)
        return self.c.cairo_surface_write_to_png(self.surf, path.encode()) == 0
