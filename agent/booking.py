"""Demo hospital booking tools. Confirmed bookings are stored in a SQLite database
(bookings.db next to app.py). This is not a real hospital system."""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Callable, Iterator

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _ROOT / "bookings.db"
DB = Path(os.environ.get("BOOKINGS_DB", DEFAULT_DB))
_LEGACY_JSON = _ROOT / "bookings.json"  # imported once if present, then left alone

DEPARTMENTS = {
    "general medicine": "Dr. Haddad",
    "cardiology": "Dr. Khoury",
    "pediatrics": "Dr. Nasser",
    "orthopedics": "Dr. Saab",
    "dermatology": "Dr. Mansour",
}
SLOTS = ["09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00"]  # Mon-Fri
MAX_DAYS_AHEAD = 60

# UNIQUE(department, date, time) means the database itself refuses a double booking.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id          TEXT PRIMARY KEY,
    patient     TEXT NOT NULL,
    department  TEXT NOT NULL,
    doctor      TEXT NOT NULL,
    date        TEXT NOT NULL,
    time        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (department, date, time)
)
"""
_COLUMNS = "id, patient, department, doctor, date, time"


def _import_legacy(con: sqlite3.Connection) -> None:
    """One-time import of the old bookings.json, only into an empty default database."""
    if DB != DEFAULT_DB or not _LEGACY_JSON.exists():
        return
    if con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]:
        return
    try:
        rows = json.loads(_LEGACY_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return
    now = dt.datetime.now().isoformat(timespec="seconds")
    for r in rows:
        try:
            con.execute(
                "INSERT OR IGNORE INTO bookings (id, patient, department, doctor, date, time, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["id"], r["patient"], r["department"], r["doctor"], r["date"], r["time"], now),
            )
        except KeyError:
            continue


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute(_SCHEMA)
        _import_legacy(con)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def load_bookings() -> list[dict]:
    with _conn() as con:
        rows = con.execute(f"SELECT {_COLUMNS} FROM bookings ORDER BY date, time").fetchall()
    return [dict(r) for r in rows]


def _dept(name: str) -> str | None:
    key = (name or "").strip().lower()
    if key in DEPARTMENTS:
        return key
    matches = [d for d in DEPARTMENTS if key and key in d]
    return matches[0] if len(matches) == 1 else None


def _day(value: str) -> tuple[dt.date | None, str | None]:
    try:
        d = dt.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None, "date must be YYYY-MM-DD"
    today = dt.date.today()
    if d < today:
        return None, "date is in the past"
    if d > today + dt.timedelta(days=MAX_DAYS_AHEAD):
        return None, f"bookings open up to {MAX_DAYS_AHEAD} days ahead"
    if d.weekday() >= 5:
        return None, "clinics are open Monday to Friday only"
    return d, None


def _taken(con: sqlite3.Connection, dept: str, day: str) -> set[str]:
    rows = con.execute("SELECT time FROM bookings WHERE department = ? AND date = ?", (dept, day))
    return {r["time"] for r in rows}


def list_departments() -> str:
    return json.dumps({d: f"{doc}, Mon-Fri, slots {SLOTS[0]}-{SLOTS[-1]}" for d, doc in DEPARTMENTS.items()})


def check_availability(department: str, date: str) -> str:
    dept = _dept(department)
    if not dept:
        return f"error: unknown department. Options: {', '.join(DEPARTMENTS)}"
    d, err = _day(date)
    if err:
        return f"error: {err}"
    with _conn() as con:
        taken = _taken(con, dept, str(d))
    free = [s for s in SLOTS if s not in taken]
    return json.dumps({"department": dept, "doctor": DEPARTMENTS[dept], "date": str(d), "free_slots": free})


def book_appointment(patient_name: str, department: str, date: str, time: str) -> str:
    """Validate, then store the booking. Nothing is saved unless every check passes."""
    if not (patient_name or "").strip():
        return "error: patient_name is required"
    dept = _dept(department)
    if not dept:
        return f"error: unknown department. Options: {', '.join(DEPARTMENTS)}"
    d, err = _day(date)
    if err:
        return f"error: {err}"
    if time not in SLOTS:
        return f"error: time must be one of {', '.join(SLOTS)}"

    booking = {"patient": patient_name.strip(), "department": dept,
               "doctor": DEPARTMENTS[dept], "date": str(d), "time": time}
    now = dt.datetime.now().isoformat(timespec="seconds")
    with _conn() as con:
        if time in _taken(con, dept, str(d)):
            return "error: that slot is already taken; call check_availability"
        for _ in range(5):  # a clash on the random id is very unlikely; retry just in case
            booking["id"] = "BK-" + uuid.uuid4().hex[:6].upper()
            try:
                con.execute(
                    "INSERT INTO bookings (id, patient, department, doctor, date, time, created_at) "
                    "VALUES (:id, :patient, :department, :doctor, :date, :time, :created_at)",
                    {**booking, "created_at": now},
                )
                break
            except sqlite3.IntegrityError as exc:
                if "bookings.id" not in str(exc):  # the slot was taken a moment ago
                    return "error: that slot is already taken; call check_availability"
        else:
            return "error: could not save the booking, please try again"
    return json.dumps({"status": "confirmed", **{k: booking[k] for k in
                       ("id", "patient", "department", "doctor", "date", "time")}})


def list_bookings(patient_name: str = "") -> str:
    q = (patient_name or "").strip().lower()
    with _conn() as con:
        rows = con.execute(
            f"SELECT {_COLUMNS} FROM bookings WHERE ? = '' OR instr(lower(patient), ?) > 0 "
            "ORDER BY date, time", (q, q)).fetchall()
    rows = [dict(r) for r in rows]
    return json.dumps(rows) if rows else "no bookings found"


def cancel_booking(booking_id: str) -> str:
    bid = (booking_id or "").strip().upper()
    with _conn() as con:
        deleted = con.execute("DELETE FROM bookings WHERE id = ?", (bid,)).rowcount
    return f"cancelled {bid}" if deleted else "error: booking id not found"


BOOKING_TOOLS: dict[str, Callable[..., str]] = {
    "list_departments": list_departments,
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "list_bookings": list_bookings,
    "cancel_booking": cancel_booking,
}


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


_S = {"type": "string"}
BOOKING_SCHEMAS = [
    _fn("list_departments", "List hospital departments, doctors and clinic hours.", {}, []),
    _fn("check_availability", "List free appointment slots for a department on a date.",
        {"department": _S, "date": {"type": "string", "description": "YYYY-MM-DD"}},
        ["department", "date"]),
    _fn("book_appointment", "Book an appointment. Only call after the user confirmed all details.",
        {"patient_name": _S, "department": _S,
         "date": {"type": "string", "description": "YYYY-MM-DD"},
         "time": {"type": "string", "description": "HH:MM from the free slots"}},
        ["patient_name", "department", "date", "time"]),
    _fn("list_bookings", "List bookings, optionally filtered by patient name.", {"patient_name": _S}, []),
    _fn("cancel_booking", "Cancel a booking by its id (e.g. BK-1A2B3C).", {"booking_id": _S}, ["booking_id"]),
]