# -*- coding: utf-8 -*-
"""
ابزارهای کمکی مشترک: تاریخ شمسی (منطقه زمانی تهران)، تبدیل ارقام، قالب‌بندی اعداد.
"""
from __future__ import annotations

import datetime as _dt
import math

import jdatetime

# ---------------------------------------------------------------------------
# منطقه زمانی تهران (سرورهای Streamlit Cloud روی UTC هستند)
# ---------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo

    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:  # pragma: no cover - در صورت نبود پایگاه داده‌ی tz
    TEHRAN_TZ = _dt.timezone(_dt.timedelta(hours=3, minutes=30))


JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_EN_DIGITS = "0123456789"
_TO_FA = str.maketrans(_EN_DIGITS, _FA_DIGITS)
_TO_EN = str.maketrans(_FA_DIGITS + _AR_DIGITS, _EN_DIGITS * 2)


def now_tehran() -> _dt.datetime:
    return _dt.datetime.now(TEHRAN_TZ)


def jalali_now() -> jdatetime.datetime:
    return jdatetime.datetime.fromgregorian(datetime=now_tehran().replace(tzinfo=None))


def jalali_today() -> jdatetime.date:
    return jalali_now().date()


def jalali_now_str() -> str:
    """زمان فعلی به صورت YYYY/MM/DD HH:MM (ارقام لاتین برای ذخیره‌سازی)."""
    return jalali_now().strftime("%Y/%m/%d %H:%M")


def days_in_jalali_month(year: int, month: int) -> int:
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    return 30 if jdatetime.date(year, 1, 1).isleap() else 29


def jdate_to_str(d: jdatetime.date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def str_to_jdate(s: str) -> jdatetime.date | None:
    try:
        y, m, d = (int(x) for x in to_en_digits(s).split("/")[:3])
        return jdatetime.date(y, m, d)
    except Exception:
        return None


def jalali_long(s: str) -> str:
    """'1403/08/03' → '۳ آبان ۱۴۰۳'"""
    d = str_to_jdate(s)
    if d is None:
        return fa(s or "")
    return fa(f"{d.day} {JALALI_MONTHS[d.month - 1]} {d.year}")


# ---------------------------------------------------------------------------
# ارقام و اعداد
# ---------------------------------------------------------------------------
def fa(value) -> str:
    """تبدیل ارقام لاتین به فارسی."""
    if value is None:
        return ""
    return str(value).translate(_TO_FA)


def to_en_digits(value) -> str:
    if value is None:
        return ""
    return str(value).translate(_TO_EN)


def fmt_num(value, max_decimals: int = 4, persian: bool = True) -> str:
    """نمایش عدد بدون صفرهای اضافی اعشار؛ جداکننده‌ی اعشار فارسی «٫»."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fa(value) if persian else str(value)
    if math.isnan(v) or math.isinf(v):
        return "—"
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        s = f"{int(round(v)):,}"
    else:
        s = f"{v:,.{max(int(max_decimals), 0)}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s in ("", "-0"):
            s = "0"
    if persian:
        s = s.replace(",", "٬").replace(".", "٫")
        return fa(s)
    return s


def fmt_coord(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.6f}"
