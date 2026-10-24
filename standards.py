# -*- coding: utf-8 -*-
"""
حدود مجاز خروجی فاضلاب (بر اساس «ضوابط و استانداردهای زیست‌محیطی خروجی فاضلاب»
سازمان حفاظت محیط زیست ایران) و منطق ارزیابی انطباق نتایج آزمایشگاه.

سه ستون استاندارد:
    surface      → تخلیه به آب‌های سطحی
    well         → تخلیه به چاه جاذب
    agriculture  → مصارف کشاورزی و آبیاری

توجه: برخی مقادیر (جیوه، EC و TDS) تقریبی یا برگرفته از رهنمودهای FAO هستند؛
پیش از استفاده‌ی رسمی، با آخرین ویرایش ابلاغی سازمان تطبیق داده شوند.
"""
from __future__ import annotations

from typing import Any

from utils import fmt_num

# ---------------------------------------------------------------------------
# دسته‌های استاندارد و منابع
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, str] = {
    "surface": "تخلیه به آب‌های سطحی",
    "well": "تخلیه به چاه جاذب",
    "agriculture": "مصارف کشاورزی و آبیاری",
}

SOURCES: dict[str, str] = {
    "doe": "سازمان حفاظت محیط زیست ایران — ضوابط و استانداردهای خروجی فاضلاب",
    "fao": "رهنمود FAO برای کیفیت آب آبیاری (Ayers & Westcot, 1985) — جنبه‌ی راهنما",
    "info": "اطلاعاتی — حد عددی مستقیم در استاندارد تعریف نشده است",
}

DISCLAIMER = (
    "حدود مجاز این سامانه بر اساس ضوابط سازمان حفاظت محیط زیست ایران تنظیم شده است؛ "
    "مقادیر جیوه، هدایت الکتریکی و کل جامدات محلول تقریبی یا راهنما هستند. "
    "برای استفاده‌ی رسمی، با آخرین ویرایش ابلاغی سازمان تطبیق دهید."
)

SAMPLE_TYPES: list[str] = [
    "پساب خروجی تصفیه‌خانه",
    "فاضلاب خام ورودی",
    "پساب صنعتی",
    "آب سطحی (رودخانه)",
    "مسیل / آبراهه",
    "دریاچه / تالاب / مخزن سد",
    "آب زیرزمینی (چاه)",
    "زهاب کشاورزی",
    "سایر",
]
RAW_SEWAGE_TYPES = {"فاضلاب خام ورودی"}

WEATHER_OPTIONS: list[str] = ["آفتابی", "نیمه‌ابری", "ابری", "بارانی", "برفی", "طوفانی / گردوغبار"]

SAMPLING_METHODS: list[str] = [
    "لحظه‌ای (Grab)",
    "مرکب زمانی (Composite)",
    "مرکب متناسب با دبی",
    "نمونه‌بردار خودکار",
    "سایر",
]

# ---------------------------------------------------------------------------
# وضعیت‌ها
# ---------------------------------------------------------------------------
STATUS_META: dict[str, dict[str, str]] = {
    "pass": {"label": "مطابق", "color": "#16a34a", "bg": "#dcfce7", "icon": "✔"},
    "warn": {"label": "نزدیک به حد", "color": "#b45309", "bg": "#fef3c7", "icon": "!"},
    "fail": {"label": "غیرمطابق", "color": "#dc2626", "bg": "#fee2e2", "icon": "✖"},
    "info": {"label": "اطلاعاتی", "color": "#475569", "bg": "#e2e8f0", "icon": "i"},
    "na": {"label": "اندازه‌گیری نشده", "color": "#94a3b8", "bg": "#f1f5f9", "icon": "—"},
}

OVERALL_META: dict[str, dict[str, str]] = {
    "compliant": {"label": "مطابق با استاندارد", "color": "#16a34a", "bg": "#dcfce7"},
    "non_compliant": {"label": "غیرمطابق با استاندارد", "color": "#dc2626", "bg": "#fee2e2"},
    "insufficient": {"label": "داده‌ی ناکافی برای قضاوت", "color": "#475569", "bg": "#e2e8f0"},
}

WARN_MARGIN = 0.10   # فاصله‌ی ۱۰٪ از حد → «نزدیک به حد»
SEVERE_RATIO = 2.0   # بیش از دو برابر حد → «تخطی شدید»

GROUPS: list[str] = [
    "پارامترهای فیزیکی و عمومی",
    "مواد آلی و اکسیژن",
    "مواد مغذی (ترکیبات نیتروژن و فسفر)",
    "املاح و سایر ترکیبات",
    "فلزات سنگین",
    "شاخص‌های میکروبی",
]


# ---------------------------------------------------------------------------
# تعریف پارامترها
#   limits[cat] = None                → بدون حد (اطلاعاتی)
#              = {"max": x}            → حداکثر
#              = {"min": x}            → حداقل
#              = {"min": a, "max": b}  → بازه
#              = {"negligible": True}  → «ناچیز»: هر مقدار قابل اندازه‌گیری غیرمطابق است
#   source[cat]: doe | fao | info
#   guide=True  → رهنمود؛ تجاوز از آن فقط «نزدیک به حد/هشدار» است، نه «غیرمطابق»
# ---------------------------------------------------------------------------
def _p(key, name, unit, group, decimals, limits, source=None, guide=None, note="",
       symbol="", max_value=None):
    return {
        "key": key, "name": name, "unit": unit, "group": group, "decimals": decimals,
        "limits": limits,
        "source": source or {c: "doe" for c in CATEGORIES},
        "guide": guide or {c: False for c in CATEGORIES},
        "note": note, "symbol": symbol, "max_value": max_value,
    }


_G1, _G2, _G3, _G4, _G5, _G6 = GROUPS

PARAMETERS: list[dict[str, Any]] = [
    # --- فیزیکی و عمومی ---
    _p("ph", "pH", "—", _G1, 2,
       {"surface": {"min": 6.5, "max": 8.5}, "well": {"min": 5.0, "max": 9.0},
        "agriculture": {"min": 6.0, "max": 8.5}}, symbol="pH", max_value=14.0),
    _p("temp", "دمای آب", "°C", _G1, 1,
       {"surface": None, "well": None, "agriculture": None},
       source={c: "info" for c in CATEGORIES},
       note="در تخلیه به آب سطحی، دمای پساب نباید دمای آب پذیرنده را در شعاع ۲۰۰ متری "
            "بیش از ۳ درجه‌ی سلسیوس تغییر دهد.", symbol="T"),
    _p("ec", "هدایت الکتریکی", "µS/cm", _G1, 0,
       {"surface": None, "well": None, "agriculture": {"max": 3000.0}},
       source={"surface": "info", "well": "info", "agriculture": "fao"},
       guide={"surface": False, "well": False, "agriculture": True},
       note="در رهنمود FAO، مقدار بیش از ۳۰۰۰ میکروزیمنس بر سانتی‌متر محدودیت شدید برای آبیاری است.",
       symbol="EC"),
    _p("tds", "کل جامدات محلول", "mg/L", _G1, 0,
       {"surface": None, "well": None, "agriculture": {"max": 2000.0}},
       source={"surface": "info", "well": "info", "agriculture": "fao"},
       guide={"surface": False, "well": False, "agriculture": True},
       note="در استاندارد سازمان، افزایش املاح نسبت به آب مصرفی نباید از حد معینی بیشتر شود؛ "
            "حد ۲۰۰۰ میلی‌گرم بر لیتر از رهنمود FAO است.", symbol="TDS"),
    _p("tss", "کل جامدات معلق", "mg/L", _G1, 1,
       {"surface": {"max": 40.0}, "well": None, "agriculture": {"max": 100.0}},
       source={"surface": "doe", "well": "info", "agriculture": "doe"},
       note="حد لحظه‌ای برای تخلیه به آب سطحی ۶۰ میلی‌گرم بر لیتر است.", symbol="TSS"),
    _p("turbidity", "کدورت", "NTU", _G1, 1,
       {"surface": {"max": 50.0}, "well": None, "agriculture": {"max": 50.0}},
       source={"surface": "doe", "well": "info", "agriculture": "doe"}, symbol="Turb."),

    # --- مواد آلی و اکسیژن ---
    _p("bod5", "اکسیژن مورد نیاز بیوشیمیایی (BOD5)", "mg/L", _G2, 1,
       {"surface": {"max": 30.0}, "well": {"max": 30.0}, "agriculture": {"max": 100.0}},
       note="حد لحظه‌ای برای آب سطحی و چاه جاذب ۵۰ میلی‌گرم بر لیتر است.", symbol="BOD5"),
    _p("cod", "اکسیژن مورد نیاز شیمیایی (COD)", "mg/L", _G2, 1,
       {"surface": {"max": 60.0}, "well": {"max": 60.0}, "agriculture": {"max": 200.0}},
       note="حد لحظه‌ای برای آب سطحی و چاه جاذب ۱۰۰ میلی‌گرم بر لیتر است.", symbol="COD"),
    _p("do", "اکسیژن محلول", "mg/L", _G2, 2,
       {"surface": {"min": 2.0}, "well": None, "agriculture": {"min": 2.0}},
       source={"surface": "doe", "well": "info", "agriculture": "doe"}, symbol="DO",
       max_value=25.0),
    _p("oil", "روغن و چربی", "mg/L", _G2, 2,
       {"surface": {"max": 10.0}, "well": {"max": 10.0}, "agriculture": {"max": 10.0}},
       symbol="O&G"),

    # --- مواد مغذی ---
    _p("nitrate", "نیترات (NO3)", "mg/L", _G3, 2,
       {"surface": {"max": 50.0}, "well": {"max": 10.0}, "agriculture": None},
       source={"surface": "doe", "well": "doe", "agriculture": "info"}, symbol="NO3"),
    _p("nitrite", "نیتریت (NO2)", "mg/L", _G3, 3,
       {"surface": {"max": 10.0}, "well": {"max": 10.0}, "agriculture": None},
       source={"surface": "doe", "well": "doe", "agriculture": "info"}, symbol="NO2"),
    _p("ammonium", "آمونیوم (NH4)", "mg/L", _G3, 2,
       {"surface": {"max": 2.5}, "well": {"max": 1.0}, "agriculture": None},
       source={"surface": "doe", "well": "doe", "agriculture": "info"}, symbol="NH4"),
    _p("phosphate", "فسفات (بر حسب فسفر)", "mg/L", _G3, 2,
       {"surface": {"max": 6.0}, "well": {"max": 6.0}, "agriculture": None},
       source={"surface": "doe", "well": "doe", "agriculture": "info"}, symbol="PO4-P"),

    # --- املاح و سایر ---
    _p("chloride", "کلرید", "mg/L", _G4, 1,
       {"surface": {"max": 600.0}, "well": {"max": 600.0}, "agriculture": {"max": 600.0}},
       symbol="Cl"),
    _p("sulfate", "سولفات", "mg/L", _G4, 1,
       {"surface": {"max": 400.0}, "well": {"max": 400.0}, "agriculture": {"max": 500.0}},
       symbol="SO4"),

    # --- فلزات سنگین ---
    _p("pb", "سرب", "mg/L", _G5, 4,
       {"surface": {"max": 1.0}, "well": {"max": 1.0}, "agriculture": {"max": 1.0}}, symbol="Pb"),
    _p("cd", "کادمیوم", "mg/L", _G5, 4,
       {"surface": {"max": 0.1}, "well": {"max": 0.1}, "agriculture": {"max": 0.05}}, symbol="Cd"),
    _p("cr6", "کروم شش‌ظرفیتی", "mg/L", _G5, 4,
       {"surface": {"max": 0.5}, "well": {"max": 1.0}, "agriculture": {"max": 1.0}}, symbol="Cr6+"),
    _p("hg", "جیوه", "mg/L", _G5, 4,
       {"surface": {"negligible": True}, "well": {"negligible": True},
        "agriculture": {"negligible": True}},
       note="در استاندارد سازمان «ناچیز» تعریف شده است؛ هر مقدار قابل اندازه‌گیری غیرمطابق است.",
       symbol="Hg"),
    _p("as", "آرسنیک", "mg/L", _G5, 4,
       {"surface": {"max": 0.1}, "well": {"max": 0.1}, "agriculture": {"max": 0.1}}, symbol="As"),
    _p("cu", "مس", "mg/L", _G5, 4,
       {"surface": {"max": 1.0}, "well": {"max": 1.0}, "agriculture": {"max": 0.2}}, symbol="Cu"),
    _p("zn", "روی", "mg/L", _G5, 4,
       {"surface": {"max": 2.0}, "well": {"max": 2.0}, "agriculture": {"max": 2.0}}, symbol="Zn"),
    _p("ni", "نیکل", "mg/L", _G5, 4,
       {"surface": {"max": 2.0}, "well": {"max": 2.0}, "agriculture": {"max": 2.0}}, symbol="Ni"),
    _p("fe", "آهن", "mg/L", _G5, 4,
       {"surface": {"max": 3.0}, "well": {"max": 3.0}, "agriculture": {"max": 3.0}}, symbol="Fe"),
    _p("mn", "منگنز", "mg/L", _G5, 4,
       {"surface": {"max": 1.0}, "well": {"max": 1.0}, "agriculture": {"max": 1.0}}, symbol="Mn"),

    # --- میکروبی ---
    _p("fecal_coliform", "کلیفرم گوارشی", "MPN/100mL", _G6, 0,
       {"surface": {"max": 400.0}, "well": {"max": 400.0}, "agriculture": {"max": 400.0}},
       symbol="FC"),
    _p("total_coliform", "کلیفرم کل", "MPN/100mL", _G6, 0,
       {"surface": {"max": 1000.0}, "well": {"max": 1000.0}, "agriculture": {"max": 1000.0}},
       symbol="TC"),
]

PARAM_BY_KEY: dict[str, dict[str, Any]] = {p["key"]: p for p in PARAMETERS}


def params_in_group(group: str) -> list[dict[str, Any]]:
    return [p for p in PARAMETERS if p["group"] == group]


def input_format(param: dict[str, Any]) -> str:
    """قالب ورودی st.number_input: فلزات کمیاب ۴ رقم اعشار، بقیه ۲ رقم."""
    return "%.4f" if param["decimals"] >= 4 else ("%.3f" if param["decimals"] == 3 else "%.2f")


def input_step(param: dict[str, Any]) -> float:
    return {4: 0.0001, 3: 0.001}.get(param["decimals"], 0.01 if param["decimals"] >= 1 else 1.0)


# ---------------------------------------------------------------------------
# متن حد مجاز
# ---------------------------------------------------------------------------
def fmt_value(param: dict[str, Any], value) -> str:
    return fmt_num(value, max(param["decimals"], 0) if param["decimals"] else 0)


def limit_text(param: dict[str, Any], category: str) -> str:
    lim = param["limits"].get(category)
    if not lim:
        return "تعریف نشده"
    if lim.get("negligible"):
        return "ناچیز"
    mn, mx = lim.get("min"), lim.get("max")
    if mn is not None and mx is not None:
        return f"{fmt_num(mn)} تا {fmt_num(mx)}"
    if mx is not None:
        txt = f"حداکثر {fmt_num(mx)}"
    else:
        txt = f"حداقل {fmt_num(mn)}"
    if param["guide"].get(category):
        txt += " (راهنما)"
    return txt


def source_label(param: dict[str, Any], category: str) -> str:
    return SOURCES[param["source"].get(category, "info")]


def source_short(param: dict[str, Any], category: str) -> str:
    return {"doe": "سازمان محیط زیست", "fao": "FAO (راهنما)", "info": "اطلاعاتی"}[
        param["source"].get(category, "info")]


# ---------------------------------------------------------------------------
# ارزیابی یک پارامتر
# ---------------------------------------------------------------------------
def _clean(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def evaluate_parameter(param: dict[str, Any], value, category: str) -> dict[str, Any]:
    """خروجی: status (pass/warn/fail/info/na)، ratio (برای نوار پیشرفت، ٪)، severe، message."""
    v = _clean(value)
    res = {
        "key": param["key"], "name": param["name"], "unit": param["unit"],
        "symbol": param["symbol"], "group": param["group"], "value": v,
        "value_text": fmt_value(param, v) if v is not None else "—",
        "limit_text": limit_text(param, category), "source": source_short(param, category),
        "status": "na", "ratio": None, "severe": False, "message": "",
    }
    if v is None:
        return res

    lim = param["limits"].get(category)
    guide = bool(param["guide"].get(category))
    if not lim:
        res["status"] = "info"
        res["message"] = "برای این کاربری حد عددی تعریف نشده است."
        return res

    # «ناچیز» (جیوه)
    if lim.get("negligible"):
        if v <= 0:
            res.update(status="pass", ratio=0.0, message="مقدار قابل اندازه‌گیری مشاهده نشد.")
        else:
            res.update(status="fail", ratio=200.0, severe=True,
                       message="حد مجاز «ناچیز» است؛ وجود هر مقدار قابل اندازه‌گیری غیرمطابق است.")
        return res

    mn, mx = lim.get("min"), lim.get("max")

    # بازه (pH)
    if mn is not None and mx is not None:
        width = mx - mn
        margin = width * WARN_MARGIN
        mid = (mn + mx) / 2
        res["ratio"] = min(abs(v - mid) / (width / 2) * 100, 200.0) if width else 0.0
        if v < mn or v > mx:
            res["status"] = "warn" if guide else "fail"
            dev = (mn - v) if v < mn else (v - mx)
            res["severe"] = dev > width / 2
            res["message"] = ("کمتر از حد پایین بازه‌ی مجاز (اسیدی)." if v < mn
                              else "بیشتر از حد بالای بازه‌ی مجاز (قلیایی).")
        elif v < mn + margin or v > mx - margin:
            res.update(status="warn", message="در بازه‌ی مجاز ولی نزدیک به مرز.")
        else:
            res.update(status="pass", message="در بازه‌ی مجاز.")
        return res

    # حداکثر
    if mx is not None:
        ratio = (v / mx * 100) if mx > 0 else (0.0 if v <= 0 else 200.0)
        res["ratio"] = ratio
        if v > mx:
            res["status"] = "warn" if guide else "fail"
            res["severe"] = (v / mx) > SEVERE_RATIO if mx > 0 else True
            times = v / mx if mx > 0 else 0
            res["message"] = (f"{fmt_num(times, 1)} برابر حد مجاز."
                              + (" (رهنمود، غیرالزامی)" if guide else ""))
        elif v > mx * (1 - WARN_MARGIN):
            res.update(status="warn", message="کمتر از حد مجاز ولی نزدیک به آن.")
        else:
            res.update(status="pass", message="کمتر از حد مجاز.")
        return res

    # حداقل (اکسیژن محلول)
    if mn is not None:
        res["ratio"] = (mn / v * 100) if v > 0 else 200.0
        if v < mn:
            res["status"] = "warn" if guide else "fail"
            res["severe"] = v < mn / SEVERE_RATIO
            res["message"] = "کمتر از حداقل مقدار لازم."
        elif v < mn * (1 + WARN_MARGIN):
            res.update(status="warn", message="بیشتر از حداقل ولی نزدیک به آن.")
        else:
            res.update(status="pass", message="بیشتر از حداقل مقدار لازم.")
        return res

    res["status"] = "info"
    return res


# ---------------------------------------------------------------------------
# ارزیابی کل نمونه
# ---------------------------------------------------------------------------
def evaluate_all(values: dict[str, Any], category: str) -> dict[str, Any]:
    results = [evaluate_parameter(p, values.get(p["key"]), category) for p in PARAMETERS]
    measured = [r for r in results if r["status"] != "na"]
    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUS_META}
    evaluated = counts["pass"] + counts["warn"] + counts["fail"]
    if counts["fail"]:
        overall = "non_compliant"
    elif evaluated:
        overall = "compliant"
    else:
        overall = "insufficient"
    return {
        "category": category,
        "category_label": CATEGORIES[category],
        "results": results,
        "measured": measured,
        "counts": counts,
        "evaluated": evaluated,
        "overall": overall,
        "overall_label": OVERALL_META[overall]["label"],
        "failed": [r for r in results if r["status"] == "fail"],
        "severe": [r for r in results if r["severe"]],
    }


def compare_all_categories(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c: evaluate_all(values, c) for c in CATEGORIES}


def clean_values(values: dict[str, Any]) -> dict[str, float]:
    """فقط مقادیر عددی معتبر و کلیدهای شناخته‌شده (برای ذخیره در JSON)."""
    out = {}
    for k, v in (values or {}).items():
        if k in PARAM_BY_KEY:
            cv = _clean(v)
            if cv is not None:
                out[k] = cv
    return out


def validate_values(values: dict[str, Any]) -> list[str]:
    """بررسی مقادیر غیرمنطقی (منفی، pH خارج از ۰ تا ۱۴ و ...)."""
    errors = []
    for k, v in clean_values(values).items():
        p = PARAM_BY_KEY[k]
        if k != "temp" and v < 0:
            errors.append(f"مقدار «{p['name']}» نمی‌تواند منفی باشد.")
        if p["max_value"] is not None and v > p["max_value"]:
            errors.append(f"مقدار «{p['name']}» باید حداکثر {fmt_num(p['max_value'])} باشد.")
    return errors


# ---------------------------------------------------------------------------
# تفسیر و نتیجه‌گیری
# ---------------------------------------------------------------------------
def interpret(values: dict[str, Any], evaluation: dict[str, Any], sample_type: str = "") -> list[str]:
    v = clean_values(values)
    by_key = {r["key"]: r for r in evaluation["results"]}
    cat = evaluation["category"]
    notes: list[str] = []

    def failed(key):
        return by_key.get(key, {}).get("status") == "fail"

    # جمع‌بندی کلی
    ov = evaluation["overall"]
    if ov == "insufficient":
        notes.append("هیچ پارامتری با حد عددی برای این کاربری اندازه‌گیری نشده است؛ "
                     "قضاوت درباره‌ی انطباق ممکن نیست.")
    elif ov == "compliant":
        warn_n = evaluation["counts"]["warn"]
        msg = (f"تمام {fmt_num(evaluation['evaluated'])} پارامتر ارزیابی‌شده در حد مجاز "
               f"«{evaluation['category_label']}» قرار دارند.")
        if warn_n:
            msg += f" {fmt_num(warn_n)} پارامتر نزدیک به حد مجاز است و پایش مستمر آن توصیه می‌شود."
        notes.append(msg)
    else:
        names = "، ".join(r["name"] for r in evaluation["failed"])
        notes.append(f"نمونه برای «{evaluation['category_label']}» غیرمطابق است. "
                     f"پارامترهای خارج از حد: {names}.")
        if evaluation["severe"]:
            sev = "، ".join(r["name"] for r in evaluation["severe"])
            notes.append(f"تخطی شدید (بیش از دو برابر حد مجاز یا انحراف زیاد) در: {sev}.")

    # نسبت BOD/COD
    bod, cod = v.get("bod5"), v.get("cod")
    if bod is not None and cod:
        r = bod / cod
        if r >= 0.5:
            t = "مواد آلی عمدتاً تجزیه‌پذیر زیستی هستند (فاضلاب با منشأ غالب شهری)؛ تصفیه‌ی زیستی مؤثر است."
        elif r >= 0.3:
            t = "تجزیه‌پذیری زیستی متوسط است؛ ممکن است بخشی از بار آلی منشأ صنعتی یا مقاوم داشته باشد."
        else:
            t = ("تجزیه‌پذیری زیستی پایین است؛ احتمال وجود ترکیبات مقاوم/صنعتی یا پساب کاملاً "
                 "تصفیه‌شده (در صورت پایین بودن مقادیر) وجود دارد.")
        notes.append(f"نسبت BOD5 به COD برابر {fmt_num(r, 2)} است: {t}")
    if failed("bod5") or failed("cod"):
        notes.append("بالا بودن بار آلی نشان‌دهنده‌ی عملکرد ناکافی واحد تصفیه‌ی زیستی "
                     "(هوادهی، زمان ماند یا غلظت لجن) است.")

    # اکسیژن محلول
    do = v.get("do")
    if do is not None and do < 2:
        notes.append("اکسیژن محلول بسیار پایین است؛ خطر شرایط بی‌هوازی، ایجاد بو و آسیب به آبزیان وجود دارد.")
    elif do is not None and do < 4:
        notes.append("اکسیژن محلول پایین است و ممکن است برای حیات آبزیان حساس کافی نباشد.")

    # مواد مغذی
    nutr = [k for k in ("nitrate", "ammonium", "phosphate", "nitrite") if failed(k)]
    high_p = v.get("phosphate") is not None and v["phosphate"] > 1
    if nutr or (high_p and cat == "surface"):
        notes.append("غلظت بالای مواد مغذی (نیتروژن/فسفر) خطر پرغذایی (اوتروفیکاسیون) و "
                     "شکوفایی جلبکی در آب پذیرنده را افزایش می‌دهد.")
    if failed("ammonium") or failed("nitrite"):
        notes.append("بالا بودن آمونیوم یا نیتریت نشان‌دهنده‌ی نیتریفیکاسیون ناقص است.")
    if cat == "well" and failed("nitrate"):
        notes.append("نیترات بالا در تخلیه به چاه جاذب، خطر آلودگی آب زیرزمینی و شرب را در پی دارد.")

    # میکروبی
    if failed("fecal_coliform") or failed("total_coliform"):
        notes.append("شاخص‌های میکروبی بیش از حد مجاز است؛ گندزدایی (کلرزنی یا پرتو فرابنفش) "
                     "ناکافی است یا انجام نشده است.")

    # فلزات
    metals = [r["name"] for r in evaluation["failed"] if r["group"] == GROUPS[4]]
    if metals:
        notes.append(f"تجاوز فلزات سنگین ({'، '.join(metals)}) احتمالاً منشأ صنعتی دارد؛ "
                     "شناسایی منبع و پیش‌تصفیه‌ی پساب صنعتی ضروری است.")

    # pH
    if failed("ph"):
        notes.append("pH " + ("اسیدی" if v["ph"] < 7 else "قلیایی")
                     + " و خارج از بازه است؛ احتمال ورود پساب صنعتی یا اختلال در فرایند تصفیه وجود دارد.")

    # جامدات معلق
    if failed("tss") or failed("turbidity"):
        notes.append("جامدات معلق یا کدورت بالاست؛ عملکرد ته‌نشینی ثانویه (زلال‌ساز) یا فیلتراسیون بررسی شود.")

    if failed("oil"):
        notes.append("روغن و چربی بیش از حد است؛ عملکرد واحد چربی‌گیر بررسی شود.")

    # شوری (راهنما)
    if by_key.get("ec", {}).get("status") == "warn" or by_key.get("tds", {}).get("status") == "warn":
        if cat == "agriculture":
            notes.append("شوری آب نسبت به رهنمود FAO بالاست و ممکن است برای گیاهان حساس محدودیت ایجاد کند.")

    if sample_type in RAW_SEWAGE_TYPES:
        notes.append("نمونه از نوع فاضلاب خام است و انتظار انطباق آن با حدود خروجی وجود ندارد؛ "
                     "مقایسه فقط جنبه‌ی شاخص و برآورد بار ورودی دارد.")
    return notes
