"""Admin tools: dashboard KPIs, sensor simulator, mismatch alerts, maintenance, tests, reset."""
from flask import Blueprint, current_app, jsonify

from .auth import login_required
from .parking import apply_sensor_event, compute_states, housekeeping
from .transport import _buses, tick
from .util import ApiError, as_int, body, get_db, now, tx

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.get("/summary")
@login_required("admin")
def summary():
    db, ts = get_db(), now()
    housekeeping(db, ts)
    tick(db, ts)
    states = compute_states(db, ts)
    n = len(states)
    cnt = {}
    for s in states.values():
        cnt[s["state"]] = cnt.get(s["state"], 0) + 1
    usable = n - cnt.get("maintenance", 0)
    busy = n - cnt.get("free", 0) - cnt.get("maintenance", 0)
    fresh = {}
    for b in _buses(db, ts):
        fresh[b["freshness"]] = fresh.get(b["freshness"], 0) + 1
    rev = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='success'").fetchone()[0]
    return jsonify({
        "slots": n, "states": cnt, "occupancy_pct": round(100 * busy / usable) if usable else 0,
        "active_reservations": db.execute("SELECT COUNT(*) FROM reservations WHERE status IN ('reserved','parked','awaiting_payment') AND source='app'").fetchone()[0],
        "open_alerts": db.execute("SELECT COUNT(*) FROM sensor_alerts WHERE resolved=0").fetchone()[0],
        "revenue_simulated": round(rev, 2), "buses": fresh})


@bp.get("/sensor-alerts")
@login_required("admin")
def alerts():
    db = get_db()
    rows = db.execute("SELECT a.*, s.label FROM sensor_alerts a JOIN slots s ON s.id=a.slot_id ORDER BY a.resolved, a.id DESC LIMIT 30").fetchall()
    return jsonify({"alerts": [{"id": r["id"], "slot": r["label"], "kind": r["kind"], "detail": r["detail"],
                                "ts": r["created_ts"], "resolved": bool(r["resolved"])} for r in rows]})


@bp.post("/sensor-alerts/<int:aid>/resolve")
@login_required("admin")
def resolve(aid):
    db = get_db()
    with tx(db):
        a = db.execute("SELECT * FROM sensor_alerts WHERE id=?", (aid,)).fetchone()
        if not a:
            raise ApiError(404, "Alert not found.", "not_found")
        db.execute("UPDATE sensor_alerts SET resolved=1 WHERE id=?", (aid,))
        # attendant confirmed it was a sensor glitch / vehicle gone -> reset sensor if nobody is legitimately parked
        if not db.execute("SELECT 1 FROM reservations WHERE slot_id=? AND status='parked'", (a["slot_id"],)).fetchone():
            db.execute("UPDATE slots SET sensor='free' WHERE id=?", (a["slot_id"],))
    return jsonify({"ok": True})


@bp.post("/sensors")
@login_required("admin")
def sensor_sim():
    """Sensor simulator: inject an 'occupied' / 'free' reading for any slot (clearly SIMULATED)."""
    d = body()
    sid = as_int(d, "slot_id", 1, label="Slot")
    state = d.get("state")
    if state not in ("occupied", "free"):
        raise ApiError(400, "State must be 'occupied' or 'free'.", "validation", {"state": "invalid"})
    db, ts = get_db(), now()
    with tx(db):
        slot = db.execute("SELECT * FROM slots WHERE id=?", (sid,)).fetchone()
        if not slot:
            raise ApiError(404, "That slot does not exist.", "not_found")
        out = apply_sensor_event(db, slot, state, ts, 0)
    return jsonify({"result": out, "simulated": True})


@bp.post("/slots/<int:sid>/maintenance")
@login_required("admin")
def maintenance(sid):
    d = body()
    if not isinstance(d.get("maintenance"), bool):
        raise ApiError(400, "'maintenance' must be true or false.", "validation", {"maintenance": "boolean"})
    db = get_db()
    with tx(db):
        if not db.execute("SELECT 1 FROM slots WHERE id=?", (sid,)).fetchone():
            raise ApiError(404, "That slot does not exist.", "not_found")
        db.execute("UPDATE slots SET maintenance=? WHERE id=?", (int(d["maintenance"]), sid))
    return jsonify({"ok": True})


@bp.post("/run-tests")
@login_required("admin")
def run_tests():
    from .selftests import run_all  # runs against its own temporary database
    return jsonify(run_all())


@bp.post("/reset-demo")
@login_required("admin")
def reset_demo():
    from . import db as dbm
    conn = get_db()
    dbm.reset(conn)
    return jsonify({"ok": True, "message": "Demo data reset. Please log in again."})
