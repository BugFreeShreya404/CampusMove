"""Login, registration, role-based access control, notifications."""
import re
import secrets
from functools import wraps

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .util import ApiError, as_text, body, get_db, now, tx

bp = Blueprint("auth", __name__, url_prefix="/api")
SESSION_TTL = 12 * 3600


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            h = request.headers.get("Authorization", "")
            if not h.startswith("Bearer "):
                raise ApiError(401, "Please log in first.", "unauthenticated")
            db = get_db()
            row = db.execute(
                "SELECT u.*, s.created_ts FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
                (h[7:],)).fetchone()
            if not row or now() - row["created_ts"] > SESSION_TTL:
                raise ApiError(401, "Session expired. Please log in again.", "unauthenticated")
            if role and row["role"] != role:
                raise ApiError(403, f"This action needs the '{role}' role.", "forbidden")
            g.user = row
            return fn(*a, **kw)
        return wrapper
    return deco


def user_json(u):
    return {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}


@bp.post("/login")
def login():
    d = body()
    username = as_text(d, "username", 1, 40, label="Username")
    password = as_text(d, "password", 1, 100, label="Password")
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE username=?", (username.lower(),)).fetchone()
    if not u or not check_password_hash(u["password_hash"], password):
        raise ApiError(401, "Invalid username or password.", "bad_credentials")
    token = secrets.token_urlsafe(24)
    db.execute("INSERT INTO sessions(token,user_id,created_ts) VALUES(?,?,?)", (token, u["id"], now()))
    return jsonify({"token": token, "user": user_json(u)})


@bp.post("/register")
def register():
    d = body()
    name = as_text(d, "name", 2, 60, label="Full name")
    username = as_text(d, "username", 3, 20, label="Username").lower()
    password = as_text(d, "password", 6, 64, label="Password")
    if not re.fullmatch(r"[a-z0-9_]+", username):
        raise ApiError(400, "Username may contain only letters, digits and underscore.", "validation", {"username": "format"})
    db = get_db()
    try:
        with tx(db):
            db.execute("INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,'student')",
                       (username, generate_password_hash(password), name))
    except Exception as e:  # sqlite3.IntegrityError
        if "UNIQUE" in str(e):
            raise ApiError(409, "That username is already taken.", "duplicate", {"username": "taken"})
        raise
    return jsonify({"ok": True}), 201


@bp.post("/logout")
@login_required()
def logout():
    h = request.headers["Authorization"][7:]
    get_db().execute("DELETE FROM sessions WHERE token=?", (h,))
    return jsonify({"ok": True})


@bp.get("/me")
@login_required()
def me():
    return jsonify({"user": user_json(g.user)})


# ---------- notifications (in-app; push is SIMULATED) ----------
def notify(db, message, kind="info", user_id=None, audience="all"):
    db.execute("INSERT INTO notifications(user_id,audience,kind,message,created_ts) VALUES(?,?,?,?,?)",
               (user_id, audience, kind, message, now()))


VISIBLE = "(user_id=? OR (user_id IS NULL AND audience IN ('all',?)))"


@bp.get("/notifications")
@login_required()
def notifications():
    db = get_db()
    u = g.user
    rows = db.execute(f"SELECT * FROM notifications WHERE {VISIBLE} ORDER BY id DESC LIMIT 40",
                      (u["id"], u["role"])).fetchall()
    unread = db.execute(f"SELECT COUNT(*) FROM notifications WHERE {VISIBLE} AND id>?",
                        (u["id"], u["role"], u["notif_seen_id"])).fetchone()[0]
    return jsonify({
        "unread": unread, "simulated": True,
        "items": [{"id": r["id"], "kind": r["kind"], "message": r["message"], "ts": r["created_ts"],
                   "unread": r["id"] > u["notif_seen_id"]} for r in rows]})


@bp.post("/notifications/read")
@login_required()
def read_all():
    db = get_db()
    m = db.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0]
    db.execute("UPDATE users SET notif_seen_id=? WHERE id=?", (m, g.user["id"]))
    return jsonify({"ok": True})
