# -*- coding: utf-8 -*-
"""سامانه نمونه‌برداری و ثبت نتایج آزمایشگاهی آب و پساب — اجرا: streamlit run app.py"""
from __future__ import annotations

import html
import time

import folium
import streamlit as st
from streamlit_folium import st_folium

import database as db
import pdf_generator as pdfgen
import standards as S
from utils import (JALALI_MONTHS, days_in_jalali_month, fa, fmt_coord, fmt_num,
                   jalali_long, jalali_now, jalali_now_str, jalali_today, now_tehran)

st.set_page_config(page_title="سامانه نمونه‌برداری آب و پساب", page_icon="💧",
                   layout="wide", initial_sidebar_state="expanded")

TEHRAN = (35.6892, 51.3890)
SAT_TILES = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"

NAV_ITEMS = ["داشبورد", "ثبت نمونه جدید", "فهرست نمونه‌ها", "ثبت نتایج آزمایش",
             "گزارش‌ها", "استانداردها", "حساب کاربری"]

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css');
html, body, .stApp, [data-testid="stSidebar"], [data-testid="stMain"] { direction: rtl; }
.stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li,
.stApp input, .stApp textarea, .stApp button, .stApp th, .stApp td, .stApp a,
.stApp [data-baseweb="select"] div, .stApp [data-testid="stMarkdownContainer"] {
    font-family: 'Vazirmatn', Tahoma, sans-serif; }
.stApp [data-testid="stIconMaterial"], .stApp .material-symbols-rounded,
.stApp span[class*="material"] { font-family: 'Material Symbols Rounded' !important; direction: ltr; }
.stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp h4 { text-align: right; }
input[type="number"], input[dir="ltr"] { direction: ltr; text-align: left; }
.ltr { direction: ltr; unicode-bidi: embed; display: inline-block; }
table.t { width: 100%; border-collapse: collapse; margin: .5rem 0 1rem; font-size: .9rem; }
table.t th { background: #e2e8f0; padding: 8px; text-align: right; border: 1px solid #cbd5e1; }
table.t td { padding: 7px 8px; border: 1px solid #e2e8f0; text-align: right; vertical-align: middle; }
table.t tr.grp td { background: #f1f5f9; font-weight: 700; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: .8rem; white-space: nowrap; }
.banner { padding: 14px 18px; border-radius: 10px; font-weight: 700; margin: .5rem 0; font-size: 1.1rem; }
.card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 18px; }
.muted { color: #64748b; font-size: .85rem; }
/* ---- ظاهر کلی ---- */
.stApp { background: linear-gradient(180deg, #f0f9ff 0%, #f8fafc 45%, #ffffff 100%); }
.block-container { padding-top: 2rem; max-width: 1200px; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0c4a6e 0%, #075985 100%); }
[data-testid="stSidebar"] * { color: #e0f2fe; }
[data-testid="stSidebar"] h3 { color: #ffffff !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #bae6fd !important; }
[data-testid="stSidebar"] button { background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.3); color: #fff; }
h1, h2, h3 { color: #0c4a6e; }
[data-testid="stMetric"] { background: #ffffff; border: 1px solid #e0f2fe; border-radius: 14px; padding: 16px 18px;
    box-shadow: 0 4px 14px rgba(2,132,199,.08); }
[data-testid="stMetricValue"] { color: #0369a1; }
.stButton > button, .stFormSubmitButton > button { border-radius: 10px; font-weight: 600; transition: all .2s ease; }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(90deg, #0284c7, #0369a1); border: none; box-shadow: 0 4px 12px rgba(2,132,199,.3); }
[data-testid="stForm"], [data-testid="stExpander"] { background: #ffffff; border-radius: 14px; border: 1px solid #e0f2fe;
    box-shadow: 0 4px 14px rgba(2,132,199,.06); }
table.t { background: #fff; border-radius: 10px; overflow: hidden; }
table.t th { background: #e0f2fe; color: #0c4a6e; }
.hero { background: linear-gradient(120deg, #0369a1 0%, #0ea5e9 60%, #38bdf8 100%); color: #fff;
    border-radius: 18px; padding: 26px 30px; margin-bottom: 1.2rem; box-shadow: 0 10px 30px rgba(3,105,161,.25); }
.hero h2 { color: #fff !important; margin: 0 0 6px 0; font-size: 1.7rem; }
.hero p { color: #e0f2fe !important; margin: 0; }
.app-footer { margin-top: 3rem; padding: 14px; text-align: center; color: #475569; font-size: .9rem;
    border-top: 1px solid #e2e8f0; }
.app-footer b { color: #0c4a6e; }
</style>
"""


# ---------------------------------------------------------------------------
# ابزارهای نمایش
# ---------------------------------------------------------------------------
def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def badge(status: str) -> str:
    m = S.STATUS_META[status]
    return f'<span class="badge" style="color:{m["color"]};background:{m["bg"]}">{esc(m["label"])}</span>'


def banner(overall: str, extra: str = "") -> None:
    m = S.OVERALL_META[overall]
    st.markdown(f'<div class="banner" style="color:{m["color"]};background:{m["bg"]}">'
                f'{esc(m["label"])}<div class="muted" style="color:{m["color"]}">{esc(extra)}</div></div>',
                unsafe_allow_html=True)


def html_table(headers: list[str], rows: list[list[str]], raw_cols: set[int] | None = None) -> None:
    """جدول HTML؛ ستون‌های raw_cols بدون escape درج می‌شوند (فقط برای HTML داخلی)."""
    raw_cols = raw_cols or set()
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f"<td>{c if i in raw_cols else esc(c)}</td>" for i, c in enumerate(r)) + "</tr>"
    st.markdown(f'<table class="t"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>',
                unsafe_allow_html=True)


def evaluation_table(ev: dict) -> None:
    rows = []
    for r in ev["measured"]:
        ratio = "—" if r["ratio"] is None else fa(f'{r["ratio"]:.0f}٪')
        rows.append([esc(r["name"]), esc(r["unit"]), esc(fa(r["value_text"])), esc(r["limit_text"]),
                     esc(r["source"]), ratio, badge(r["status"]), esc(r["message"])])
    html_table(["پارامتر", "واحد", "مقدار", "حد مجاز", "منبع", "درصد از حد", "وضعیت", "توضیح"],
               rows, raw_cols={0, 1, 2, 3, 4, 5, 6, 7})


def sample_label(s: dict) -> str:
    return f'{s["sample_code"]} — {s["location_name"]} — {fa(s["sample_date"])}'


def sample_map(lat: float, lon: float, key: str, height: int = 300) -> None:
    m = folium.Map(location=[lat, lon], zoom_start=16, tiles=SAT_TILES, attr="Google")
    folium.Marker([lat, lon]).add_to(m)
    st_folium(m, height=height, use_container_width=True, key=key, returned_objects=[])


def goto(page: str) -> None:
    st.session_state["pending_nav"] = page
    st.rerun()


# ---------------------------------------------------------------------------
# ورود و ثبت‌نام
# ---------------------------------------------------------------------------
def auth_page() -> None:
    st.markdown('<div class="hero"><h2>💧 سامانه نمونه‌برداری و آزمایش آب و پساب</h2>'
                '<p>ثبت نمونه، ثبت نتایج آزمایشگاه و بررسی انطباق با ضوابط سازمان حفاظت محیط زیست</p></div>',
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        tab_in, tab_up = st.tabs(["ورود", "ثبت‌نام"])
        with tab_in:
            with st.form("login"):
                u = st.text_input("نام کاربری", key="li_u")
                p = st.text_input("رمز عبور", type="password", key="li_p")
                go = st.form_submit_button("ورود", type="primary", use_container_width=True)
            if go:
                wait = st.session_state.get("lock_until", 0) - time.time()
                if wait > 0:
                    st.error(f"تلاش‌های ناموفق زیاد بود؛ {fa(int(wait) + 1)} ثانیه صبر کنید.")
                else:
                    user = db.authenticate(u, p)
                    if user:
                        st.session_state.update(user=user, fails=0)
                        st.rerun()
                    st.session_state["fails"] = st.session_state.get("fails", 0) + 1
                    if st.session_state["fails"] >= 5:
                        st.session_state.update(fails=0, lock_until=time.time() + 60)
                    st.error("نام کاربری یا رمز عبور اشتباه است.")
        with tab_up:
            with st.form("signup"):
                fn = st.text_input("نام و نام خانوادگی")
                org = st.text_input("سازمان / شرکت (اختیاری)")
                un = st.text_input("نام کاربری (حروف انگلیسی، عدد، _ . -)")
                p1 = st.text_input("رمز عبور (حداقل ۶ کاراکتر)", type="password")
                p2 = st.text_input("تکرار رمز عبور", type="password")
                go = st.form_submit_button("ثبت‌نام", type="primary", use_container_width=True)
            if go:
                if p1 != p2:
                    st.error("رمز عبور و تکرار آن یکسان نیست.")
                else:
                    ok, msg = db.create_user(un, fn, p1, org)
                    (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------------------
# داشبورد
# ---------------------------------------------------------------------------
def page_dashboard(user: dict) -> None:
    st.markdown(f'<div class="hero"><h2>خوش آمدید، {esc(user["full_name"])}</h2>'
                f'<p>وضعیت کلی نمونه‌ها و نتایج آزمایشگاه شما</p></div>', unsafe_allow_html=True)
    stats = db.get_stats(user["id"])
    cols = st.columns(6)
    for col, (label, key) in zip(cols, [("کل نمونه‌ها", "total"), ("آنالیز شده", "analyzed"),
                                         ("در انتظار آزمایش", "pending"), ("مطابق", "compliant"),
                                         ("غیرمطابق", "non_compliant"), ("نمونه‌های این ماه", "this_month")]):
        col.metric(label, fa(stats[key]))
    st.subheader("آخرین نمونه‌ها")
    samples = db.get_samples(user["id"])[:8]
    if not samples:
        st.info("هنوز نمونه‌ای ثبت نکرده‌اید.")
        if st.button("ثبت اولین نمونه", type="primary"):
            goto("ثبت نمونه جدید")
        return
    rows = []
    for s in samples:
        res = db.get_lab_result(s["id"], user["id"])
        if res:
            status = '<span class="badge" style="color:{color};background:{bg}">{label}</span>'.format(
                **S.OVERALL_META[res["overall_status"]])
        else:
            status = '<span class="badge" style="color:#94a3b8;background:#f1f5f9">بدون نتیجه</span>'
        rows.append([esc(s["sample_code"]), esc(s["location_name"]), esc(s["sample_type"]),
                     esc(fa(s["sample_date"])), status])
    html_table(["کد نمونه", "محل", "نوع نمونه", "تاریخ", "وضعیت"], rows, raw_cols={0, 1, 2, 3, 4})


# ---------------------------------------------------------------------------
# ثبت نمونه
# ---------------------------------------------------------------------------
def page_new_sample(user: dict) -> None:
    st.header("ثبت نمونه جدید")
    ver = st.session_state.setdefault("form_ver", 0)

    st.subheader("۱. موقعیت نمونه‌برداری")
    st.caption("روی نقشه‌ی ماهواره‌ای کلیک کنید تا مختصات ثبت شود، یا مختصات را دستی وارد کنید.")
    lat_k, lon_k = f"lat_{ver}", f"lon_{ver}"
    center = st.session_state.get("map_center", TEHRAN)
    zoom = st.session_state.get("map_zoom", 6)
    m = folium.Map(location=list(center), zoom_start=zoom, tiles=SAT_TILES, attr="Google")
    cur_lat, cur_lon = st.session_state.get(lat_k), st.session_state.get(lon_k)
    if cur_lat is not None and cur_lon is not None:
        folium.Marker([cur_lat, cur_lon]).add_to(m)
    out = st_folium(m, height=420, use_container_width=True, key=f"map_{ver}",
                    returned_objects=["last_clicked"])
    click = (out or {}).get("last_clicked")
    if click:
        new = (round(click["lat"], 6), round(click["lng"], 6))
        if new != st.session_state.get("last_click"):
            st.session_state.update(last_click=new, map_center=new, map_zoom=16)
            st.session_state[lat_k], st.session_state[lon_k] = new
            st.rerun()
    c1, c2 = st.columns(2)
    lat = c1.number_input("عرض جغرافیایی (Latitude)", min_value=-90.0, max_value=90.0, value=None,
                          format="%.6f", key=lat_k)
    lon = c2.number_input("طول جغرافیایی (Longitude)", min_value=-180.0, max_value=180.0, value=None,
                          format="%.6f", key=lon_k)

    st.subheader("۲. تاریخ نمونه‌برداری (شمسی)")
    today = jalali_today()
    d1, d2, d3 = st.columns(3)
    years = list(range(1390, today.year + 2))
    year = d3.selectbox("سال", years, index=years.index(today.year), format_func=fa, key=f"y_{ver}")
    month = d2.selectbox("ماه", list(range(1, 13)), index=today.month - 1,
                         format_func=lambda i: JALALI_MONTHS[i - 1], key=f"m_{ver}")
    ndays = days_in_jalali_month(year, month)
    day = d1.selectbox("روز", list(range(1, ndays + 1)), index=min(today.day, ndays) - 1,
                       format_func=fa, key=f"d_{ver}")
    sample_date = f"{year:04d}/{month:02d}/{day:02d}"

    st.subheader("۳. مشخصات نمونه")
    with st.form(f"sample_form_{ver}"):
        a, b = st.columns(2)
        code = a.text_input("کد نمونه (اختیاری)", placeholder=db.suggest_sample_code(user["id"], sample_date),
                            help="اگر خالی بماند، کد به‌صورت خودکار ساخته می‌شود.")
        stype = b.selectbox("نوع نمونه", S.SAMPLE_TYPES)
        loc = st.text_input("نام محل نمونه‌برداری")
        a, b = st.columns(2)
        sampler = a.text_input("نام نمونه‌بردار", value=user["full_name"])
        stime = b.time_input("ساعت نمونه‌برداری", value=now_tehran().time().replace(second=0, microsecond=0))
        a, b = st.columns(2)
        method = a.selectbox("روش نمونه‌برداری", S.SAMPLING_METHODS)
        lab = b.text_input("آزمایشگاه مقصد (اختیاری)")
        a, b = st.columns(2)
        weather = a.selectbox("وضعیت جوی", S.WEATHER_OPTIONS)
        air = b.number_input("دمای هوا (°C)", value=None, step=0.5, format="%.1f")
        notes = st.text_area("توضیحات")
        go = st.form_submit_button("ثبت نمونه", type="primary", use_container_width=True)

    if go:
        if lat is None or lon is None:
            st.error("موقعیت نمونه را روی نقشه مشخص کنید یا مختصات را وارد کنید.")
        elif not loc.strip() or not sampler.strip():
            st.error("نام محل و نام نمونه‌بردار الزامی است.")
        else:
            try:
                _, final = db.add_sample(user["id"], {
                    "sample_code": code, "sample_date": sample_date,
                    "sample_time": stime.strftime("%H:%M"), "sample_type": stype,
                    "location_name": loc.strip(), "latitude": lat, "longitude": lon,
                    "sampler_name": sampler.strip(), "sampling_method": method,
                    "lab_name": lab.strip(), "weather": weather, "air_temp": air,
                    "notes": notes.strip()})
            except ValueError as e:
                st.error(str(e))
            else:
                for k in ("last_click", "map_center", "map_zoom"):
                    st.session_state.pop(k, None)
                st.session_state["form_ver"] = ver + 1
                st.session_state["flash"] = f"نمونه با کد {final} ثبت شد."
                goto("فهرست نمونه‌ها")


# ---------------------------------------------------------------------------
# فهرست نمونه‌ها
# ---------------------------------------------------------------------------
def page_samples(user: dict) -> None:
    st.header("فهرست نمونه‌ها")
    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    samples = db.get_samples(user["id"])
    if not samples:
        st.info("نمونه‌ای ثبت نشده است.")
        return
    q = st.text_input("جستجو (کد، محل یا نوع نمونه)")
    if q.strip():
        qq = q.strip().lower()
        samples = [s for s in samples if qq in f'{s["sample_code"]} {s["location_name"]} {s["sample_type"]}'.lower()]
    rows = [[esc(s["sample_code"]), esc(s["location_name"]), esc(s["sample_type"]),
             esc(fa(s["sample_date"])), esc(s["sampler_name"])] for s in samples]
    html_table(["کد نمونه", "محل", "نوع نمونه", "تاریخ", "نمونه‌بردار"], rows, raw_cols=set(range(5)))
    if not samples:
        return
    st.subheader("جزئیات")
    sel = st.selectbox("نمونه", samples, format_func=sample_label)
    s = db.get_sample(sel["id"], user["id"])
    c1, c2 = st.columns([3, 2])
    with c1:
        pairs = [("کد نمونه", s["sample_code"]), ("نوع", s["sample_type"]), ("محل", s["location_name"]),
                 ("تاریخ", jalali_long(s["sample_date"])), ("ساعت", fa(s.get("sample_time") or "—")),
                 ("نمونه‌بردار", s["sampler_name"]), ("روش", s.get("sampling_method") or "—"),
                 ("آزمایشگاه", s.get("lab_name") or "—"), ("وضعیت جوی", s.get("weather") or "—"),
                 ("دمای هوا", "—" if s.get("air_temp") is None else fa(fmt_num(s["air_temp"], 1)) + " °C"),
                 ("مختصات", f'{fmt_coord(s["latitude"])}, {fmt_coord(s["longitude"])}'),
                 ("توضیحات", s.get("notes") or "—")]
        html_table(["مشخصه", "مقدار"], [[esc(k), esc(v)] for k, v in pairs], raw_cols={0, 1})
    with c2:
        sample_map(s["latitude"], s["longitude"], key=f"detail_map_{s['id']}")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("ثبت / ویرایش نتایج آزمایش", key="to_lab"):
        st.session_state["lab_sample_id"] = s["id"]
        goto("ثبت نتایج آزمایش")
    with b2.popover("حذف نمونه"):
        st.warning("نمونه و نتایج آزمایش آن برای همیشه حذف می‌شود.")
        if st.button("بله، حذف شود", key="del_yes", type="primary"):
            db.delete_sample(s["id"], user["id"])
            st.session_state["flash"] = "نمونه حذف شد."
            st.rerun()


# ---------------------------------------------------------------------------
# ثبت نتایج آزمایش
# ---------------------------------------------------------------------------
def page_lab(user: dict) -> None:
    st.header("ثبت نتایج آزمایش")
    samples = db.get_samples(user["id"])
    if not samples:
        st.info("ابتدا یک نمونه ثبت کنید.")
        return
    ids = [s["id"] for s in samples]
    pre = st.session_state.pop("lab_sample_id", None)
    if pre in ids:
        st.session_state["lab_sel"] = pre
    if st.session_state.get("lab_sel") not in ids:
        st.session_state["lab_sel"] = ids[0]
    by_id = {s["id"]: s for s in samples}
    sid = st.selectbox("نمونه", ids, format_func=lambda i: sample_label(by_id[i]), key="lab_sel")
    sample = by_id[sid]
    existing = db.get_lab_result(sid, user["id"])
    old = (existing or {}).get("parameters") or {}

    cats = list(S.CATEGORIES)
    default_cat = (existing or {}).get("standard_category", "surface")
    category = st.selectbox("نوع کاربری / مقصد تخلیه", cats, index=cats.index(default_cat) if default_cat in cats else 0,
                            format_func=lambda c: S.CATEGORIES[c], key=f"cat_{sid}")
    st.caption(S.DISCLAIMER)
    if existing:
        st.info("برای این نمونه نتیجه ثبت شده است؛ ذخیره‌ی دوباره آن را به‌روزرسانی می‌کند.")

    today = jalali_today()
    ad_default = (existing or {}).get("analysis_date") or f"{today.year:04d}/{today.month:02d}/{today.day:02d}"
    with st.form(f"lab_form_{sid}"):
        a, b = st.columns(2)
        adate = a.text_input("تاریخ آزمایش (شمسی، مانند ۱۴۰۵/۰۸/۰۲)", value=fa(ad_default))
        analyst = b.text_input("نام تحلیلگر / آزمایشگاه", value=(existing or {}).get("analyst_name", ""))
        values: dict = {}
        for g in S.GROUPS:
            with st.expander(g, expanded=g == S.GROUPS[0]):
                ps = S.params_in_group(g)
                cols = st.columns(3)
                for i, p in enumerate(ps):
                    unit = "" if p["unit"] == "—" else f' ({p["unit"]})'
                    values[p["key"]] = cols[i % 3].number_input(
                        f'{p["name"]}{unit}', value=old.get(p["key"]), step=S.input_step(p),
                        format=S.input_format(p), key=f"v_{sid}_{p['key']}",
                        help="حد مجاز: " + S.limit_text(p, category))
        notes = st.text_area("توضیحات", value=(existing or {}).get("notes", "") or "")
        go = st.form_submit_button("ذخیره و ارزیابی", type="primary", use_container_width=True)

    if go:
        from utils import str_to_jdate, to_en_digits
        jd = str_to_jdate(to_en_digits(adate).strip())
        errs = S.validate_values(values)
        if jd is None:
            errs.append("تاریخ آزمایش معتبر نیست (قالب: سال/ماه/روز).")
        if not analyst.strip():
            errs.append("نام تحلیلگر را وارد کنید.")
        if not S.clean_values(values):
            errs.append("حداقل یک پارامتر را وارد کنید.")
        if errs:
            for e in errs:
                st.error(e)
        else:
            clean = S.clean_values(values)
            ev = S.evaluate_all(clean, category)
            db.save_lab_result(user["id"], sid, f"{jd.year:04d}/{jd.month:02d}/{jd.day:02d}",
                               analyst.strip(), category, clean, ev["overall"], notes.strip())
            st.success("نتایج ذخیره شد.")
            existing = db.get_lab_result(sid, user["id"])

    if existing:
        show_evaluation(sample, existing)


def show_evaluation(sample: dict, result: dict) -> None:
    values = result["parameters"]
    cat = result["standard_category"]
    ev = S.evaluate_all(values, cat)
    st.subheader("نتیجه‌ی ارزیابی")
    c = ev["counts"]
    banner(ev["overall"], f'مطابق: {fa(c["pass"])} | نزدیک به حد: {fa(c["warn"])} | '
                          f'غیرمطابق: {fa(c["fail"])} | استاندارد: {ev["category_label"]}')
    evaluation_table(ev)
    for note in S.interpret(values, ev, sample.get("sample_type", "")):
        st.markdown(f"- {note}")
    with st.expander("مقایسه با هر سه کاربری"):
        rows = []
        for k, e in S.compare_all_categories(values).items():
            rows.append([esc(S.CATEGORIES[k]), badge_overall(e["overall"]), esc(fa(len(e["failed"])))])
        html_table(["کاربری", "وضعیت", "تعداد پارامتر غیرمطابق"], rows, raw_cols={0, 1, 2})


def badge_overall(o: str) -> str:
    m = S.OVERALL_META[o]
    return f'<span class="badge" style="color:{m["color"]};background:{m["bg"]}">{esc(m["label"])}</span>'


# ---------------------------------------------------------------------------
# گزارش‌ها
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def cached_image(lat: float, lon: float):
    return pdfgen.fetch_satellite_image(lat, lon)


def page_reports(user: dict) -> None:
    st.header("گزارش‌ها")
    samples = db.get_samples(user["id"])
    if not samples:
        st.info("نمونه‌ای برای تهیه‌ی گزارش وجود ندارد.")
        return
    ok, msg = pdfgen.check_fonts()
    if not ok:
        st.error(msg)
        return
    sample = st.selectbox("نمونه", samples, format_func=sample_label, key="rep_sel")
    sample = db.get_sample(sample["id"], user["id"])
    result = db.get_lab_result(sample["id"], user["id"])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### گزارش نمونه‌برداری")
        if st.button("تهیه گزارش نمونه‌برداری", key="mk_s", use_container_width=True):
            with st.spinner("در حال تهیه‌ی گزارش..."):
                img = cached_image(sample["latitude"], sample["longitude"])
                st.session_state["pdf_s"] = (sample["id"], pdfgen.build_sample_report(sample, user, img), img is not None)
        d = st.session_state.get("pdf_s")
        if d and d[0] == sample["id"]:
            if not d[2]:
                st.caption("تصویر ماهواره‌ای در دسترس نبود؛ پیوند نقشه در گزارش درج شد.")
            st.download_button("دانلود PDF", d[1], f'sample_{sample["sample_code"]}.pdf',
                               "application/pdf", key="dl_s", use_container_width=True)
    with c2:
        st.markdown("#### گزارش نتایج آزمایش")
        if not result:
            st.info("برای این نمونه هنوز نتیجه‌ی آزمایش ثبت نشده است.")
        else:
            if st.button("تهیه گزارش آزمایش", key="mk_l", use_container_width=True):
                with st.spinner("در حال تهیه‌ی گزارش..."):
                    img = cached_image(sample["latitude"], sample["longitude"])
                    st.session_state["pdf_l"] = (sample["id"], pdfgen.build_lab_report(sample, result, user, img))
            d = st.session_state.get("pdf_l")
            if d and d[0] == sample["id"]:
                st.download_button("دانلود PDF", d[1], f'lab_{sample["sample_code"]}.pdf',
                                   "application/pdf", key="dl_l", use_container_width=True)


# ---------------------------------------------------------------------------
# استانداردها و حساب کاربری
# ---------------------------------------------------------------------------
def page_standards() -> None:
    st.header("استانداردها")
    st.caption(S.DISCLAIMER)
    cat = st.selectbox("کاربری", list(S.CATEGORIES), format_func=lambda c: S.CATEGORIES[c])
    for g in S.GROUPS:
        st.subheader(g)
        rows = [[esc(p["name"]), esc(p["unit"]), esc(S.limit_text(p, cat)), esc(S.source_short(p, cat))]
                for p in S.params_in_group(g)]
        html_table(["پارامتر", "واحد", "حد مجاز", "منبع"], rows, raw_cols=set(range(4)))


def page_account(user: dict) -> None:
    st.header("حساب کاربری")
    with st.form("profile"):
        fn = st.text_input("نام و نام خانوادگی", value=user["full_name"])
        org = st.text_input("سازمان", value=user.get("organization") or "")
        go = st.form_submit_button("ذخیره", type="primary")
    if go:
        ok, msg = db.update_profile(user["id"], fn, org)
        if ok:
            st.session_state["user"] = db.get_user(user["id"])
        (st.success if ok else st.error)(msg)
    st.subheader("تغییر رمز عبور")
    with st.form("pw"):
        o = st.text_input("رمز فعلی", type="password")
        n = st.text_input("رمز جدید", type="password")
        n2 = st.text_input("تکرار رمز جدید", type="password")
        go = st.form_submit_button("تغییر رمز")
    if go:
        if n != n2:
            st.error("رمز جدید و تکرار آن یکسان نیست.")
        else:
            ok, msg = db.change_password(user["id"], o, n)
            (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def main() -> None:
    db.init_db()
    st.markdown(CSS, unsafe_allow_html=True)
    user = st.session_state.get("user")
    if not user:
        auth_page()
        return
    if "pending_nav" in st.session_state:
        st.session_state["nav"] = st.session_state.pop("pending_nav")
    with st.sidebar:
        st.markdown(f"### 💧 {esc(user['full_name'])}")
        st.caption(jalali_long(jalali_now_str()[:10]))
        page = st.radio("منو", NAV_ITEMS, key="nav", label_visibility="collapsed")
        if st.button("خروج", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    {"داشبورد": lambda: page_dashboard(user),
     "ثبت نمونه جدید": lambda: page_new_sample(user),
     "فهرست نمونه‌ها": lambda: page_samples(user),
     "ثبت نتایج آزمایش": lambda: page_lab(user),
     "گزارش‌ها": lambda: page_reports(user),
     "استانداردها": page_standards,
     "حساب کاربری": lambda: page_account(user)}[page]()


def footer() -> None:
    st.markdown('<div class="app-footer">توسعه‌دهنده: <b>علیرضا فاضلی ثانی</b></div>',
                unsafe_allow_html=True)


try:
    main()
finally:
    footer()
