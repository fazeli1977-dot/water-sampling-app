# -*- coding: utf-8 -*-
"""
تولید گزارش‌های PDF فارسی (راست‌به‌چپ) با fpdf2.

* متن فارسی با arabic_reshaper شکل‌دهی و با python-bidi به ترتیب نمایشی تبدیل می‌شود.
* شکستن سطرها پیش از bidi و سطربه‌سطر انجام می‌شود تا ترتیب کلمات در متن چندسطری
  درست بماند و کدهای لاتین (مثل WS-14030803-001) چپ‌به‌راست بمانند.
* جدول‌ها دستی و از راست به چپ رسم می‌شوند (ستون اول در سمت راست).
* تصویر ماهواره‌ای با چسباندن ۳×۳ کاشی ساخته می‌شود؛ اگر اینترنت در دسترس نباشد
  گزارش بدون تصویر تولید می‌شود.

توابع اصلی:
    build_sample_report(sample, user, map_image=None) -> bytes
    build_lab_report(sample, result, user, map_image=None) -> bytes
    fetch_satellite_image(lat, lon) -> (jpeg_bytes, provider, width_m) | None
"""
from __future__ import annotations

import io
import math
import os
import re
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF

import standards as S
from utils import fa, fmt_coord, fmt_num, jalali_long, jalali_now_str

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "fonts")
FONT_FILES = {"": "Vazirmatn-Regular.ttf", "B": "Vazirmatn-Bold.ttf"}
FONT_URLS = [
    "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/{name}",
    "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@master/fonts/ttf/{name}",
]
FONT = "Vazirmatn"
APP_NAME = "سامانه‌ی پایش کیفیت آب و پساب"

C_PRIMARY = (14, 116, 144)
C_PRIMARY_LIGHT = (224, 242, 254)
C_TEXT = (30, 41, 59)
C_MUTED = (100, 116, 139)
C_BORDER = (203, 213, 225)
C_HEAD_BG = (226, 232, 240)
C_ZEBRA = (248, 250, 252)
C_LABEL_BG = (241, 245, 249)
PAGE_BOTTOM = 17  # فاصله‌ی امن از پایین صفحه (میلی‌متر)

_RTL_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
_UNSUPPORTED = str.maketrans({"✔": "", "✖": "", "→": "-", "←": "-", "₅": "5", "≤": "", "≥": ""})


def _rgb(color) -> tuple[int, int, int]:
    if isinstance(color, str):
        c = color.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return tuple(color)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# فونت
# ---------------------------------------------------------------------------
def _font_path(name: str) -> str:
    """مسیر فونت محلی؛ در صورت نبود، تلاش برای دانلود از GitHub."""
    candidates = [os.path.join(FONT_DIR, name), os.path.join(tempfile.gettempdir(), name)]
    for path in candidates:
        if os.path.exists(path) and os.path.getsize(path) > 10_000:
            return path
    last_err: Exception | None = None
    for tpl in FONT_URLS:
        try:
            req = urllib.request.Request(tpl.format(name=name), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if len(data) < 10_000:
                continue
            for path in candidates:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as fh:
                        fh.write(data)
                    return path
                except OSError:
                    continue
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(
        f"فونت «{name}» یافت نشد. فایل‌های Vazirmatn-Regular.ttf و Vazirmatn-Bold.ttf را "
        f"در پوشه‌ی fonts کنار app.py قرار دهید. (جزئیات: {last_err})")


def check_fonts() -> tuple[bool, str]:
    try:
        for name in FONT_FILES.values():
            _font_path(name)
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# متن راست‌به‌چپ
# ---------------------------------------------------------------------------
def clean_text(text: Any) -> str:
    return ("" if text is None else str(text)).translate(_UNSUPPORTED)


def vis(text: Any) -> str:
    """تبدیل متن منطقی به ترتیب نمایشی؛ متن بدون نویسه‌ی فارسی دست‌نخورده می‌ماند."""
    text = clean_text(text)
    if not _RTL_RE.search(text):
        return text
    return get_display(arabic_reshaper.reshape(text), base_dir="R")


# ---------------------------------------------------------------------------
# تصویر ماهواره‌ای
# ---------------------------------------------------------------------------
TILE_PROVIDERS = [
    ("Esri World Imagery",
     "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    ("Google Satellite", "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"),
]


def _fetch_tile(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EnvLabApp)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 300:
        raise ValueError("کاشی نامعتبر")
    return data


def fetch_satellite_image(lat: float, lon: float, zoom: int = 16, size: int = 512,
                          timeout: float = 6.0) -> tuple[bytes, str, float] | None:
    """تصویر ماهواره‌ای به مرکز مختصات با نشانگر قرمز.

    خروجی: (بایت‌های JPEG، نام سرویس، عرض تقریبی تصویر به متر) یا None.
    """
    try:
        from PIL import Image, ImageDraw
        lat = max(min(float(lat), 85.0), -85.0)
        lon = float(lon)
    except Exception:  # noqa: BLE001
        return None
    n = 2 ** zoom
    xf = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    yf = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    tx, ty = int(xf), int(yf)
    offsets = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]

    for provider, tpl in TILE_PROVIDERS:
        try:
            urls = [tpl.format(z=zoom, x=(tx + dx) % n, y=min(max(ty + dy, 0), n - 1))
                    for dx, dy in offsets]
            with ThreadPoolExecutor(max_workers=9) as ex:
                tiles = list(ex.map(lambda u: _fetch_tile(u, timeout), urls))
            canvas = Image.new("RGB", (768, 768))
            for (dx, dy), data in zip(offsets, tiles):
                canvas.paste(Image.open(io.BytesIO(data)).convert("RGB"),
                             ((dx + 1) * 256, (dy + 1) * 256))
            px, py = (xf - tx + 1) * 256, (yf - ty + 1) * 256
            half = size // 2
            left = int(min(max(round(px - half), 0), 768 - size))
            top = int(min(max(round(py - half), 0), 768 - size))
            img = canvas.crop((left, top, left + size, top + size))
            cx, cy = px - left, py - top
            draw = ImageDraw.Draw(img)
            for a, b in (((-24, 0), (-10, 0)), ((10, 0), (24, 0)), ((0, -24), (0, -10)), ((0, 10), (0, 24))):
                draw.line((cx + a[0], cy + a[1], cx + b[0], cy + b[1]), fill=(255, 255, 255), width=3)
            draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(220, 38, 38),
                         outline=(255, 255, 255), width=3)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            width_m = size * 156543.03392 * math.cos(lat_r) / n
            return buf.getvalue(), provider, width_m
        except Exception:  # noqa: BLE001
            continue
    return None


def google_maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={float(lat):.6f},{float(lon):.6f}"


# ---------------------------------------------------------------------------
# کلاس پایه‌ی PDF راست‌به‌چپ
# ---------------------------------------------------------------------------
class RtlPDF(FPDF):
    def __init__(self, title: str, organization: str = ""):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.report_title = title
        self.organization = organization or ""
        self.generated_at = jalali_now_str()
        for style, name in FONT_FILES.items():
            self.add_font(FONT, style, _font_path(name))
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(False)
        self.set_title(title)
        self.set_creator(APP_NAME)
        self.content_w = self.w - self.l_margin - self.r_margin
        self.x_right = self.w - self.r_margin
        self._repeat_header = None

    # ---------- ابزار پایه ----------
    def font(self, size: float = 10, bold: bool = False):
        self.set_font(FONT, "B" if bold else "", size)

    def color(self, rgb):
        self.set_text_color(*_rgb(rgb))

    def text_w(self, text: str) -> float:
        return self.get_string_width(vis(text))

    def wrap(self, text: Any, width: float) -> list[str]:
        """شکستن متن منطقی به سطرها بر اساس عرض نمایشی با فونت فعلی."""
        out: list[str] = []
        for para in clean_text(text).split("\n"):
            words = para.split()
            if not words:
                out.append("")
                continue
            line = ""
            for word in words:
                cand = f"{line} {word}" if line else word
                if self.text_w(cand) <= width:
                    line = cand
                    continue
                if line:
                    out.append(line)
                line = ""
                if self.text_w(word) <= width:
                    line = word
                    continue
                for ch in word:  # کلمه‌ی خیلی بلند → شکستن نویسه‌ای
                    if line and self.text_w(line + ch) > width:
                        out.append(line)
                        line = ch
                    else:
                        line += ch
            out.append(line)
        return out or [""]

    def put(self, x: float, y: float, w: float, h: float, text: Any, align: str = "R",
            link: str = ""):
        self.set_xy(x, y)
        self.cell(w, h, vis(text), align=align, link=link)

    def ensure_space(self, h: float) -> bool:
        """اگر جا نباشد صفحه‌ی جدید؛ True یعنی صفحه عوض شد."""
        if self.get_y() + h > self.h - PAGE_BOTTOM:
            self.add_page()
            return True
        return False

    # ---------- سربرگ و پاورقی ----------
    def header(self):
        self.set_fill_color(*C_PRIMARY)
        self.rect(0, 0, self.w, 21, style="F")
        self.color((255, 255, 255))
        self.font(14, True)
        self.put(self.l_margin, 4, self.content_w, 7, self.report_title, "R")
        self.font(9)
        sub = APP_NAME + (f" — {self.organization}" if self.organization else "")
        self.put(self.l_margin, 12, self.content_w, 5, sub, "R")
        self.put(self.l_margin, 4.5, 70, 6, "تاریخ تهیه: " + fa(self.generated_at), "L")
        self.color(C_TEXT)
        self.set_y(27)

    def footer(self):
        y = self.h - 12
        self.set_draw_color(*C_BORDER)
        self.set_line_width(0.2)
        self.line(self.l_margin, y, self.x_right, y)
        self.font(8)
        self.color(C_MUTED)
        self.put(self.l_margin, y + 1.5, self.content_w, 5, "صفحه " + fa(self.page_no()), "R")
        self.put(self.l_margin, y + 1.5, self.content_w, 5,
                 "این گزارش به‌صورت خودکار تولید شده است", "L")
        self.color(C_TEXT)

    # ---------- اجزای محتوا ----------
    def section(self, title: str, min_after: float = 22):
        self.ensure_space(12 + min_after)
        y = self.get_y() + 1.5
        self.set_fill_color(*C_PRIMARY_LIGHT)
        self.rect(self.l_margin, y, self.content_w, 8, style="F")
        self.set_fill_color(*C_PRIMARY)
        self.rect(self.x_right - 1.5, y, 1.5, 8, style="F")
        self.font(11, True)
        self.color(C_PRIMARY)
        self.put(self.l_margin, y + 0.4, self.content_w - 4, 7.2, title, "R")
        self.color(C_TEXT)
        self.set_y(y + 10.5)

    def paragraph(self, text: str, size: float = 10, bold: bool = False, rgb=C_TEXT,
                  line_h: float = 5.8, bullet: bool = False, indent: float = 0):
        self.font(size, bold)
        bw = 5 if bullet else 0
        width = self.content_w - indent - bw
        for i, line in enumerate(self.wrap(text, width - 1)):
            self.ensure_space(line_h)
            y = self.get_y()
            if bullet and i == 0:
                self.set_fill_color(*C_PRIMARY)
                self.ellipse(self.x_right - indent - 3.2, y + line_h / 2 - 0.9, 1.8, 1.8, style="F")
            self.color(rgb)
            self.put(self.l_margin, y, width, line_h, line, "R")
            self.set_y(y + line_h)
        self.color(C_TEXT)

    def table(self, columns: list[tuple[str, float, str]], rows: list[Any],
              font_size: float = 8.8, line_h: float = 4.6, pad: float = 1.5,
              zebra: bool = True, header: bool = True):
        """جدول راست‌به‌چپ.

        columns: [(عنوان، عرض نسبی، تراز)] — ستون اول سمت راست قرار می‌گیرد.
        rows: هر سطر فهرستی از سلول‌ها (رشته یا dict با کلیدهای text, fill, color, bold, align)؛
              یا {"span": "عنوان"} برای سطر عنوان گروه در کل عرض.
        """
        total = sum(c[1] for c in columns)
        widths = [c[1] * self.content_w / total for c in columns]
        self.set_draw_color(*C_BORDER)
        self.set_line_width(0.2)

        def measure(cells):
            wrapped = []
            for cell, w in zip(cells, widths):
                self.font(font_size, cell.get("bold", False))
                wrapped.append(self.wrap(cell.get("text", ""), w - 2 * pad))
            return wrapped, max(len(x) for x in wrapped) * line_h + 2 * pad

        def draw(cells, wrapped, row_h, fill_default):
            y = self.get_y()
            x = self.x_right
            for cell, w, lines, col in zip(cells, widths, wrapped, columns):
                x -= w
                fill = cell.get("fill") or fill_default
                if fill:
                    self.set_fill_color(*_rgb(fill))
                self.rect(x, y, w, row_h, style="DF" if fill else "D")
                self.font(font_size, cell.get("bold", False))
                self.color(cell.get("color") or C_TEXT)
                ty = y + (row_h - len(lines) * line_h) / 2
                for line in lines:
                    self.put(x + pad, ty, w - 2 * pad, line_h, line, cell.get("align", col[2]))
                    ty += line_h
            self.color(C_TEXT)
            self.set_y(y + row_h)

        head_cells = [{"text": c[0], "bold": True, "align": "C"} for c in columns]
        head_wrapped, head_h = measure(head_cells)

        def draw_header():
            if header:
                draw(head_cells, head_wrapped, head_h, C_HEAD_BG)

        self.ensure_space((head_h if header else 0) + line_h + 2 * pad)
        draw_header()
        zi = 0
        for row in rows:
            if isinstance(row, dict) and "span" in row:
                h = line_h + 2 * pad
                if self.ensure_space(h + line_h + 2 * pad):
                    draw_header()
                y = self.get_y()
                self.set_fill_color(*C_PRIMARY_LIGHT)
                self.rect(self.l_margin, y, self.content_w, h, style="DF")
                self.font(font_size, True)
                self.color(C_PRIMARY)
                self.put(self.l_margin + pad, y + pad, self.content_w - 2 * pad, line_h, row["span"], "R")
                self.color(C_TEXT)
                self.set_y(y + h)
                zi = 0
                continue
            cells = [c if isinstance(c, dict) else {"text": c} for c in row]
            wrapped, row_h = measure(cells)
            if self.ensure_space(row_h):
                draw_header()
            draw(cells, wrapped, row_h, C_ZEBRA if zebra and zi % 2 else None)
            zi += 1
        self.set_y(self.get_y() + 3)

    def kv_grid(self, pairs: list[tuple[str, Any]], per_row: int = 2):
        """جدول «عنوان | مقدار» با چند جفت در هر سطر."""
        cols: list[tuple[str, float, str]] = []
        for _ in range(per_row):
            cols += [("", 17, "R"), ("", 33, "R")]
        rows = []
        for i in range(0, len(pairs), per_row):
            row: list[Any] = []
            for label, value in pairs[i:i + per_row]:
                row.append({"text": label, "fill": C_LABEL_BG, "bold": True, "color": (71, 85, 105)})
                if isinstance(value, dict):
                    row.append(value)
                else:
                    row.append({"text": value if value not in (None, "") else "—"})
            while len(row) < per_row * 2:
                row += [{"text": "", "fill": C_LABEL_BG}, {"text": ""}]
            rows.append(row)
        self.table(cols, rows, header=False, zebra=False, font_size=9.2, line_h=5)

    def badge(self, label: str, fg, bg, sub: str = ""):
        """کادر رنگی وضعیت کلی."""
        h = 14 if sub else 10
        self.ensure_space(h + 4)
        y = self.get_y()
        self.set_fill_color(*_rgb(bg))
        self.set_draw_color(*_rgb(fg))
        self.set_line_width(0.5)
        self.rect(self.l_margin, y, self.content_w, h, style="DF")
        self.set_fill_color(*_rgb(fg))
        self.rect(self.x_right - 3, y, 3, h, style="F")
        self.font(13, True)
        self.color(fg)
        self.put(self.l_margin + 3, y + 1.6, self.content_w - 8, 7, label, "R")
        if sub:
            self.font(9)
            self.color(C_TEXT)
            self.put(self.l_margin + 3, y + 8, self.content_w - 8, 5, sub, "R")
        self.set_line_width(0.2)
        self.color(C_TEXT)
        self.set_y(y + h + 4)

    def image_block(self, img: tuple[bytes, str, float] | None, lat, lon, height: float = 78):
        """تصویر ماهواره‌ای (در صورت وجود) به‌همراه پیوند گوگل‌مپ."""
        link = google_maps_link(lat, lon)
        if img:
            data, provider, width_m = img
            self.ensure_space(height + 14)
            y = self.get_y()
            x = self.l_margin + (self.content_w - height) / 2
            self.image(io.BytesIO(data), x=x, y=y, w=height, h=height)
            self.set_draw_color(*C_BORDER)
            self.rect(x, y, height, height, style="D")
            self.set_y(y + height + 1.5)
            self.font(8)
            self.color(C_MUTED)
            self.put(self.l_margin, self.get_y(), self.content_w, 4.5,
                     f"تصویر ماهواره‌ای — منبع: {provider} — پهنای تقریبی تصویر "
                     f"{fmt_num(round(width_m, -1))} متر — نقطه‌ی قرمز محل نمونه‌برداری است", "C")
            self.set_y(self.get_y() + 5)
        else:
            self.paragraph("تصویر ماهواره‌ای در زمان تهیه‌ی گزارش در دسترس نبود "
                           "(اتصال اینترنت یا سرویس نقشه).", size=9, rgb=C_MUTED)
        self.font(8.5)
        self.color(C_MUTED)
        self.ensure_space(6)
        y = self.get_y()
        self.put(self.l_margin, y, self.content_w, 5, link, "C", link=link)
        self.color(C_TEXT)
        self.set_y(y + 7)

    def output_bytes(self) -> bytes:
        return bytes(self.output())


# ---------------------------------------------------------------------------
# ابزار مشترک گزارش‌ها
# ---------------------------------------------------------------------------
def _txt(value, default: str = "—") -> str:
    if value is None:
        return default
    s = str(value).strip()
    return fa(s) if s else default


def _ltr(value) -> dict:
    """سلول لاتین (مثل کد نمونه یا مختصات)."""
    return {"text": _txt(value) if value in (None, "") else str(value)}


def _sample_pairs(sample: dict) -> list[tuple[str, Any]]:
    air = sample.get("air_temp")
    return [
        ("کد نمونه", _ltr(sample.get("sample_code"))),
        ("تاریخ نمونه‌برداری", jalali_long(sample.get("sample_date") or "")),
        ("ساعت نمونه‌برداری", _txt(sample.get("sample_time"))),
        ("نوع نمونه", _txt(sample.get("sample_type"))),
        ("روش نمونه‌برداری", _txt(sample.get("sampling_method"))),
        ("نام نمونه‌بردار", _txt(sample.get("sampler_name"))),
        ("آزمایشگاه مقصد", _txt(sample.get("lab_name"))),
        ("شرایط جوی", _txt(sample.get("weather"))),
        ("دمای هوا", (fmt_num(air, 1) + " درجه‌ی سانتی‌گراد") if air not in (None, "") else "—"),
        ("تاریخ ثبت در سامانه", _txt(sample.get("created_at"))),
    ]


def _location_pairs(sample: dict) -> list[tuple[str, Any]]:
    return [
        ("نام محل", _txt(sample.get("location_name"))),
        ("سیستم مختصات", "WGS84 (درجه‌ی اعشاری)"),
        ("عرض جغرافیایی", _ltr(fmt_coord(sample.get("latitude")))),
        ("طول جغرافیایی", _ltr(fmt_coord(sample.get("longitude")))),
    ]


def _signatures(pdf: RtlPDF, roles: list[str]):
    h = 26
    pdf.ensure_space(h + 6)
    y = pdf.get_y() + 2
    gap = 6
    w = (pdf.content_w - gap * (len(roles) - 1)) / len(roles)
    pdf.set_draw_color(*C_BORDER)
    x = pdf.x_right
    for role in roles:
        x -= w
        pdf.rect(x, y, w, h, style="D")
        pdf.font(9.5, True)
        pdf.color(C_TEXT)
        pdf.put(x + 2, y + 2, w - 4, 6, role, "R")
        pdf.font(8.5)
        pdf.color(C_MUTED)
        pdf.put(x + 2, y + 9, w - 4, 5, "نام و نام خانوادگی:", "R")
        pdf.put(x + 2, y + 18, w - 4, 5, "امضا و تاریخ:", "R")
        x -= gap
    pdf.color(C_TEXT)
    pdf.set_y(y + h + 4)


def _notes_block(pdf: RtlPDF, title: str, notes):
    if notes and str(notes).strip():
        pdf.section(title, min_after=8)
        pdf.paragraph(_txt(notes), size=9.5)
        pdf.set_y(pdf.get_y() + 2)


# ---------------------------------------------------------------------------
# گزارش نمونه‌برداری
# ---------------------------------------------------------------------------
def build_sample_report(sample: dict, user: dict | None = None,
                        map_image: tuple[bytes, str, float] | None = None,
                        result: dict | None = None) -> bytes:
    user = user or {}
    pdf = RtlPDF("گزارش نمونه‌برداری", user.get("organization") or "")
    pdf.add_page()

    pdf.font(10)
    pdf.color(C_MUTED)
    y = pdf.get_y()
    pdf.put(pdf.l_margin, y, pdf.content_w, 6,
            f"کد نمونه: {sample.get('sample_code', '')}   |   تهیه‌کننده: "
            f"{_txt(user.get('full_name'))}", "R")
    pdf.color(C_TEXT)
    pdf.set_y(y + 8)

    pdf.section("مشخصات نمونه")
    pdf.kv_grid(_sample_pairs(sample))

    pdf.section("موقعیت نمونه‌برداری", min_after=40)
    pdf.kv_grid(_location_pairs(sample))
    pdf.image_block(map_image, sample.get("latitude"), sample.get("longitude"))

    pdf.section("وضعیت آزمایش", min_after=12)
    if result:
        meta = S.OVERALL_META.get(result.get("overall_status"), S.OVERALL_META["insufficient"])
        cat = S.CATEGORIES.get(result.get("standard_category"), "—")
        pdf.badge(meta["label"], meta["color"], meta["bg"],
                  f"تاریخ آزمایش: {jalali_long(result.get('analysis_date') or '')} — "
                  f"استاندارد مبنا: {cat}")
        pdf.paragraph("جزئیات نتایج در «گزارش نتایج آزمایش» همین نمونه آمده است.",
                      size=9, rgb=C_MUTED)
    else:
        pdf.paragraph("نتیجه‌ی آزمایشگاهی برای این نمونه هنوز ثبت نشده است.", size=10)
    pdf.set_y(pdf.get_y() + 2)

    _notes_block(pdf, "توضیحات", sample.get("notes"))
    pdf.section("تأیید", min_after=30)
    _signatures(pdf, ["نمونه‌بردار", "تحویل‌گیرنده‌ی آزمایشگاه"])
    return pdf.output_bytes()


# ---------------------------------------------------------------------------
# گزارش نتایج آزمایش
# ---------------------------------------------------------------------------
def _status_cell(r: dict) -> dict:
    meta = S.STATUS_META[r["status"]]
    label = meta["label"] + (" (شدید)" if r.get("severe") else "")
    return {"text": label, "fill": meta["bg"], "color": meta["color"], "bold": True, "align": "C"}


def _ratio_text(r: dict) -> str:
    ratio = r.get("ratio")
    if ratio is None or r["status"] in ("info", "na"):
        return "—"
    return fa(f"{min(ratio, 999):.0f}") + "٪"


def build_lab_report(sample: dict, result: dict, user: dict | None = None,
                     map_image: tuple[bytes, str, float] | None = None) -> bytes:
    user = user or {}
    values = result.get("parameters") or {}
    category = result.get("standard_category") or "surface"
    if category not in S.CATEGORIES:
        category = "surface"
    ev = S.evaluate_all(values, category)
    meta = S.OVERALL_META[ev["overall"]]
    c = ev["counts"]

    pdf = RtlPDF("گزارش نتایج آزمایش کیفیت آب و پساب", user.get("organization") or "")
    pdf.add_page()

    pdf.section("مشخصات نمونه و آزمایش")
    pdf.kv_grid([
        ("کد نمونه", _ltr(sample.get("sample_code"))),
        ("نوع نمونه", _txt(sample.get("sample_type"))),
        ("نام محل", _txt(sample.get("location_name"))),
        ("مختصات", _ltr(f"{fmt_coord(sample.get('latitude'))}, {fmt_coord(sample.get('longitude'))}")),
        ("تاریخ نمونه‌برداری", jalali_long(sample.get("sample_date") or "")),
        ("نام نمونه‌بردار", _txt(sample.get("sampler_name"))),
        ("تاریخ آزمایش", jalali_long(result.get("analysis_date") or "")),
        ("نام آزمایشگر", _txt(result.get("analyst_name"))),
        ("آزمایشگاه", _txt(sample.get("lab_name"))),
        ("استاندارد مبنا", S.CATEGORIES[category]),
    ])

    pdf.section("نتیجه‌ی کلی", min_after=16)
    sub = (f"{fa(len(ev['measured']))} پارامتر اندازه‌گیری شده — مطابق: {fa(c['pass'])}، "
           f"نزدیک به حد: {fa(c['warn'])}، غیرمطابق: {fa(c['fail'])}، اطلاعاتی: {fa(c['info'])}")
    pdf.badge(meta["label"], meta["color"], meta["bg"], sub)

    pdf.section("نتایج پارامترها", min_after=30)
    if ev["measured"]:
        cols = [("پارامتر", 30, "R"), ("واحد", 15, "C"), ("مقدار", 14, "C"),
                ("حد مجاز", 21, "C"), ("منبع حد", 18, "C"), ("درصد از حد", 12, "C"),
                ("وضعیت", 20, "C")]
        rows: list[Any] = []
        for group in S.GROUPS:
            items = [r for r in ev["measured"] if r["group"] == group]
            if not items:
                continue
            rows.append({"span": group})
            for r in items:
                rows.append([
                    {"text": r["name"], "bold": True},
                    {"text": r["unit"]},
                    {"text": r["value_text"], "bold": True},
                    {"text": r["limit_text"]},
                    {"text": r["source"]},
                    {"text": _ratio_text(r)},
                    _status_cell(r),
                ])
        pdf.table(cols, rows)
        pdf.paragraph("«درصد از حد» برای حد بیشینه برابر نسبت مقدار به حد است؛ برای pH فاصله از "
                      "میانه‌ی بازه نسبت به نیم‌بازه، و برای اکسیژن محلول نسبت حداقل لازم به مقدار است. "
                      "بیش از ۱۰۰٪ یعنی خارج از حد.", size=8, rgb=C_MUTED, line_h=4.6)
        pdf.set_y(pdf.get_y() + 2)

        # پیام‌های پارامترهای غیرمطابق یا نزدیک به حد
        flagged = [r for r in ev["measured"] if r["status"] in ("fail", "warn") and r["message"]]
        if flagged:
            pdf.section("پارامترهای نیازمند توجه", min_after=12)
            for r in flagged:
                label = S.STATUS_META[r["status"]]["label"]
                pdf.paragraph(f"{r['name']} ({label}): مقدار {r['value_text']} {r['unit']} — "
                              f"{r['message']}", size=9.5, bullet=True,
                              rgb=_rgb(S.STATUS_META[r["status"]]["color"]))
            pdf.set_y(pdf.get_y() + 2)
    else:
        pdf.paragraph("هیچ مقداری برای پارامترها ثبت نشده است.")

    pdf.section("مقایسه با سه کاربری استاندارد", min_after=26)
    comp_rows = []
    for cat, e in S.compare_all_categories(values).items():
        m = S.OVERALL_META[e["overall"]]
        name = S.CATEGORIES[cat] + (" (مبنا)" if cat == category else "")
        comp_rows.append([
            {"text": name, "bold": cat == category},
            {"text": m["label"], "fill": m["bg"], "color": m["color"], "bold": True, "align": "C"},
            fa(e["counts"]["pass"]), fa(e["counts"]["warn"]), fa(e["counts"]["fail"]),
        ])
    pdf.table([("کاربری", 34, "R"), ("وضعیت کلی", 30, "C"), ("مطابق", 12, "C"),
               ("نزدیک به حد", 12, "C"), ("غیرمطابق", 12, "C")], comp_rows)

    pdf.section("تفسیر و نتیجه‌گیری", min_after=14)
    for note in S.interpret(values, ev, sample.get("sample_type") or ""):
        pdf.paragraph(note, size=9.8, bullet=True)
    pdf.set_y(pdf.get_y() + 2)

    _notes_block(pdf, "توضیحات آزمایشگاه", result.get("notes"))

    if map_image is not None:
        pdf.section("موقعیت نمونه‌برداری", min_after=60)
        pdf.image_block(map_image, sample.get("latitude"), sample.get("longitude"), height=62)

    pdf.section("منابع و تذکر", min_after=14)
    used = sorted({p["source"].get(category, "info") for p in S.PARAMETERS
                   if p["key"] in S.clean_values(values)})
    for src in used or ["doe"]:
        pdf.paragraph(S.SOURCES[src], size=8.8, bullet=True, line_h=5)
    pdf.paragraph(S.DISCLAIMER, size=8.8, rgb=C_MUTED, line_h=5)
    pdf.set_y(pdf.get_y() + 3)

    _signatures(pdf, ["آزمایشگر", "مسئول فنی آزمایشگاه"])
    return pdf.output_bytes()
