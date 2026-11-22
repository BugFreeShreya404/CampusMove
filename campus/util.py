"""Shared helpers: error type, clock, DB access, validation."""
import re
import sqlite3
import time

from flask import current_app, g, request


class ApiError(Exception):
    """Raised anywhere in a request; converted to a JSON error response."""

    def __init__(self, status, message, code="error", fields=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.fields = fields or {}


def now():
    """Current epoch seconds. TIME_OFFSET lets tests / demo advance the clock."""
    return time.time() + current_app.config.get("TIME_OFFSET", 0)


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DB_PATH"], timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


class tx:
    """`with tx(db):` -> atomic write transaction (BEGIN IMMEDIATE serialises writers,
    which is what prevents two students booking the same slot at the same moment)."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        self.db.execute("ROLLBACK" if et else "COMMIT")
        return False


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Request body must be a JSON object.", "bad_request")
    return data


# ---------- validation helpers ----------
VEHICLE_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalize_vehicle(v):
    return re.sub(r"[\s-]", "", str(v or "")).upper()


def as_int(data, key, lo=None, hi=None, required=True, label=None):
    label = label or key
    if key not in data or data[key] in (None, ""):
        if required:
            raise ApiError(400, f"{label} is required.", "validation", {key: "required"})
        return None
    v = data[key]
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()))):
        raise ApiError(400, f"{label} must be a whole number.", "validation", {key: "must be an integer"})
    v = int(v)
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ApiError(400, f"{label} must be between {lo} and {hi}.", "validation", {key: f"range {lo}-{hi}"})
    return v


def as_text(data, key, lo=1, hi=200, required=True, label=None):
    label = label or key
    v = data.get(key)
    if v is None or str(v).strip() == "":
        if required:
            raise ApiError(400, f"{label} is required.", "validation", {key: "required"})
        return None
    v = str(v).strip()
    if not (lo <= len(v) <= hi):
        raise ApiError(400, f"{label} must be {lo}-{hi} characters.", "validation", {key: f"length {lo}-{hi}"})
    return v


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)
