# -*- coding: utf-8 -*-
"""
لایه‌ی پایگاه داده (SQLite) — جداول Users، Samples و LabResults.

* رمز عبور با PBKDF2-HMAC-SHA256 و نمک (salt) تصادفی برای هر کاربر هش می‌شود.
* تمام توابع خواندن/حذف/ویرایش بر اساس user_id محدود شده‌اند تا هر کاربر
  فقط به داده‌های خودش دسترسی داشته باشد.
* تاریخ‌ها به صورت رشته‌ی شمسی YYYY/MM/DD ذخیره می‌شوند (قابل مرتب‌سازی).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Any

from utils import jalali_now_str, jalali_today, to_en_digits

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ENV_LAB_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "env_lab.db")

PBKDF2_ITERATIONS = 200_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


# ---------------------------------------------------------------------------
# اتصال (PostgreSQL/Supabase در صورت وجود DATABASE_URL، وگرنه SQLite محلی)
# ---------------------------------------------------------------------------
def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    try:
        import streamlit as st
        return str(st.secrets.get("DATABASE_URL", "")).strip()
    except Exception:
        return ""


DATABASE_URL = _database_url()
USE_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

if USE_PG:
    import psycopg2
    import psycopg2.extras
    IntegrityError = psycopg2.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


class _PgConn:
    """پوششی نازک تا همان SQL با جای‌نگهدار ? روی PostgreSQL هم کار کند."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=()):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return cur


@contextmanager
def get_conn():
    if USE_PG:
        raw = psycopg2.connect(DATABASE_URL, connect_timeout=15, sslmode="require")
        try:
            yield _PgConn(raw)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

_PG_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS Users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,
        full_name TEXT NOT NULL,
        organization TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON Users (LOWER(username))",
    """CREATE TABLE IF NOT EXISTS Samples (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
        sample_code TEXT NOT NULL,
        sample_date TEXT NOT NULL,
        sample_time TEXT,
        sample_type TEXT NOT NULL,
        location_name TEXT NOT NULL,
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        sampler_name TEXT NOT NULL,
        sampling_method TEXT,
        lab_name TEXT,
        weather TEXT,
        air_temp DOUBLE PRECISION,
        notes TEXT,
        created_at TEXT NOT NULL)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_samples_code ON Samples (user_id, LOWER(sample_code))",
    """CREATE TABLE IF NOT EXISTS LabResults (
        id SERIAL PRIMARY KEY,
        sample_id INTEGER NOT NULL UNIQUE REFERENCES Samples(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
        analysis_date TEXT NOT NULL,
        analyst_name TEXT,
        standard_category TEXT NOT NULL,
        parameters_json TEXT NOT NULL,
        overall_status TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_samples_user ON Samples(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_user ON LabResults(user_id)",
]


def init_db() -> None:
    if USE_PG:
        with get_conn() as conn:
            for stmt in _PG_SCHEMA:
                conn.execute(stmt)
        return
    _init_sqlite()


def _init_sqlite() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS Users (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                username       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                full_name      TEXT    NOT NULL,
                organization   TEXT,
                password_hash  TEXT    NOT NULL,
                created_at     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS Samples (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
                sample_code    TEXT    NOT NULL,
                sample_date    TEXT    NOT NULL,
                sample_time    TEXT,
                sample_type    TEXT    NOT NULL,
                location_name  TEXT    NOT NULL,
                latitude       REAL    NOT NULL,
                longitude      REAL    NOT NULL,
                sampler_name   TEXT    NOT NULL,
                sampling_method TEXT,
                lab_name       TEXT,
                weather        TEXT,
                air_temp       REAL,
                notes          TEXT,
                created_at     TEXT    NOT NULL,
                UNIQUE(user_id, sample_code)
            );

            CREATE TABLE IF NOT EXISTS LabResults (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                sample_id          INTEGER NOT NULL UNIQUE REFERENCES Samples(id) ON DELETE CASCADE,
                user_id            INTEGER NOT NULL REFERENCES Users(id) ON DELETE CASCADE,
                analysis_date      TEXT    NOT NULL,
                analyst_name       TEXT,
                standard_category  TEXT    NOT NULL,
                parameters_json    TEXT    NOT NULL,
                overall_status     TEXT    NOT NULL,
                notes              TEXT,
                created_at         TEXT    NOT NULL,
                updated_at         TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_samples_user  ON Samples(user_id);
            CREATE INDEX IF NOT EXISTS idx_results_user  ON LabResults(user_id);
            """
        )
        # مهاجرت سبک برای پایگاه‌داده‌های قدیمی‌تر
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(Samples)").fetchall()}
        if "sampling_method" not in cols:
            conn.execute("ALTER TABLE Samples ADD COLUMN sampling_method TEXT")


# ---------------------------------------------------------------------------
# رمز عبور
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None,
                  iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, _hash = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt, int(iterations))
        return hmac.compare_digest(candidate, stored)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# کاربران
# ---------------------------------------------------------------------------
def create_user(username: str, full_name: str, password: str,
                organization: str = "") -> tuple[bool, str]:
    username = to_en_digits(username or "").strip()
    full_name = (full_name or "").strip()
    if not USERNAME_RE.match(username):
        return False, ("نام کاربری باید ۳ تا ۳۲ کاراکتر و فقط شامل حروف انگلیسی، "
                       "ارقام و نمادهای _ . - باشد.")
    if len(full_name) < 2:
        return False, "نام و نام خانوادگی را وارد کنید."
    if len(password or "") < 6:
        return False, "رمز عبور باید حداقل ۶ کاراکتر باشد."
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO Users (username, full_name, organization, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, full_name, (organization or "").strip(),
                 hash_password(password), jalali_now_str()),
            )
        return True, "حساب کاربری با موفقیت ایجاد شد. اکنون وارد شوید."
    except IntegrityError:
        return False, "این نام کاربری قبلاً ثبت شده است."


def authenticate(username: str, password: str) -> dict | None:
    username = to_en_digits(username or "").strip()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM Users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
    if row and verify_password(password or "", row["password_hash"]):
        return _public_user(row)
    return None


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM Users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(row) if row else None


def update_profile(user_id: int, full_name: str, organization: str) -> tuple[bool, str]:
    if len((full_name or "").strip()) < 2:
        return False, "نام و نام خانوادگی را وارد کنید."
    with get_conn() as conn:
        conn.execute("UPDATE Users SET full_name = ?, organization = ? WHERE id = ?",
                     (full_name.strip(), (organization or "").strip(), user_id))
    return True, "اطلاعات حساب به‌روزرسانی شد."


def change_password(user_id: int, old_password: str, new_password: str) -> tuple[bool, str]:
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM Users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(old_password or "", row["password_hash"]):
            return False, "رمز عبور فعلی نادرست است."
        if len(new_password or "") < 6:
            return False, "رمز عبور جدید باید حداقل ۶ کاراکتر باشد."
        conn.execute("UPDATE Users SET password_hash = ? WHERE id = ?",
                     (hash_password(new_password), user_id))
    return True, "رمز عبور با موفقیت تغییر کرد."


def _public_user(row) -> dict:
    d = dict(row)
    d.pop("password_hash", None)
    return d


# ---------------------------------------------------------------------------
# نمونه‌ها
# ---------------------------------------------------------------------------
def generate_sample_code(conn, user_id: int, sample_date: str) -> str:
    """کد یکتا: WS-YYYYMMDD-NNN (شماره‌ی ترتیبی نمونه‌های همان روز برای کاربر)."""
    compact = sample_date.replace("/", "")
    prefix = f"WS-{compact}-"
    rows = conn.execute(
        "SELECT sample_code FROM Samples WHERE user_id = ? AND sample_code LIKE ?",
        (user_id, prefix + "%"),
    ).fetchall()
    used = []
    for r in rows:
        try:
            used.append(int(r["sample_code"].rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            pass
    return f"{prefix}{(max(used) + 1 if used else 1):03d}"


def suggest_sample_code(user_id: int, sample_date: str) -> str:
    with get_conn() as conn:
        return generate_sample_code(conn, user_id, sample_date)


def sample_code_exists(user_id: int, sample_code: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM Samples WHERE user_id = ? AND LOWER(sample_code) = LOWER(?)",
            (user_id, (sample_code or "").strip()),
        ).fetchone()
    return row is not None


def add_sample(user_id: int, data: dict[str, Any]) -> tuple[int, str]:
    """ثبت نمونه. اگر کد نمونه خالی باشد، کد یکتا به‌صورت خودکار ساخته می‌شود.

    در صورت تکراری بودن کد، ValueError با پیام فارسی برمی‌گرداند.
    """
    with get_conn() as conn:
        code = to_en_digits(data.get("sample_code") or "").strip()
        if not code:
            code = generate_sample_code(conn, user_id, data["sample_date"])
        dup = conn.execute(
            "SELECT 1 FROM Samples WHERE user_id = ? AND LOWER(sample_code) = LOWER(?)",
            (user_id, code)).fetchone()
        if dup:
            raise ValueError(f"کد نمونه «{code}» قبلاً در حساب شما ثبت شده است.")
        cur = conn.execute(
            """INSERT INTO Samples (user_id, sample_code, sample_date, sample_time, sample_type,
                   location_name, latitude, longitude, sampler_name, sampling_method,
                   lab_name, weather, air_temp, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               RETURNING id""",
            (user_id, code, data["sample_date"], data.get("sample_time"),
             data["sample_type"], data["location_name"], float(data["latitude"]),
             float(data["longitude"]), data["sampler_name"], data.get("sampling_method"),
             data.get("lab_name"), data.get("weather"), data.get("air_temp"),
             data.get("notes"), jalali_now_str()),
        )
        return int(cur.fetchone()["id"]), code


_SAMPLE_SELECT = """
    SELECT s.*, r.id AS result_id, r.overall_status, r.standard_category,
           r.analysis_date, r.updated_at AS result_updated_at
    FROM Samples s
    LEFT JOIN LabResults r ON r.sample_id = s.id AND r.user_id = s.user_id
"""


def get_samples(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            _SAMPLE_SELECT + " WHERE s.user_id = ? ORDER BY s.sample_date DESC, s.id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sample(sample_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(_SAMPLE_SELECT + " WHERE s.id = ? AND s.user_id = ?",
                           (sample_id, user_id)).fetchone()
    return dict(row) if row else None


def delete_sample(sample_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM LabResults WHERE sample_id = ? AND user_id = ?",
                     (sample_id, user_id))
        cur = conn.execute("DELETE FROM Samples WHERE id = ? AND user_id = ?",
                           (sample_id, user_id))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# نتایج آزمایشگاه
# ---------------------------------------------------------------------------
def save_lab_result(user_id: int, sample_id: int, analysis_date: str, analyst_name: str,
                    standard_category: str, parameters: dict[str, float],
                    overall_status: str, notes: str = "") -> bool:
    """ثبت یا به‌روزرسانی نتیجه‌ی آزمایش یک نمونه (هر نمونه یک کارنامه)."""
    if get_sample(sample_id, user_id) is None:
        return False
    now = jalali_now_str()
    payload = json.dumps(parameters, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO LabResults (sample_id, user_id, analysis_date, analyst_name,
                   standard_category, parameters_json, overall_status, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sample_id) DO UPDATE SET
                   analysis_date = excluded.analysis_date,
                   analyst_name = excluded.analyst_name,
                   standard_category = excluded.standard_category,
                   parameters_json = excluded.parameters_json,
                   overall_status = excluded.overall_status,
                   notes = excluded.notes,
                   updated_at = excluded.updated_at
               WHERE LabResults.user_id = excluded.user_id""",
            (sample_id, user_id, analysis_date, analyst_name, standard_category,
             payload, overall_status, notes, now, now),
        )
    return True


def get_lab_result(sample_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM LabResults WHERE sample_id = ? AND user_id = ?",
                           (sample_id, user_id)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["parameters"] = json.loads(d.pop("parameters_json") or "{}")
    except json.JSONDecodeError:
        d["parameters"] = {}
    return d


def delete_lab_result(sample_id: int, user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM LabResults WHERE sample_id = ? AND user_id = ?",
                     (sample_id, user_id))


def get_stats(user_id: int) -> dict[str, int]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM Samples WHERE user_id = ?",
                             (user_id,)).fetchone()["n"]
        rows = conn.execute(
            "SELECT overall_status, COUNT(*) AS n FROM LabResults WHERE user_id = ? "
            "GROUP BY overall_status", (user_id,)).fetchall()
        month_prefix = jalali_today().strftime("%Y/%m/")
        this_month = conn.execute(
            "SELECT COUNT(*) AS n FROM Samples WHERE user_id = ? AND sample_date LIKE ?",
            (user_id, month_prefix + "%")).fetchone()["n"]
    by_status = {r["overall_status"]: r["n"] for r in rows}
    analyzed = sum(by_status.values())
    return {
        "total": total,
        "analyzed": analyzed,
        "pending": total - analyzed,
        "compliant": by_status.get("compliant", 0),
        "non_compliant": by_status.get("non_compliant", 0),
        "this_month": this_month,
    }
