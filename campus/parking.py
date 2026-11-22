"""Smart parking: availability, reservations, simulated sensor events, fees, payment."""
import json
import math
import re
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from .auth import login_required, notify
from .util import ApiError, as_int, body, get_db, normalize_vehicle, now, tx, VEHICLE_RE

bp = Blueprint("parking", __name__, url_prefix="/api")

GRACE = 15 * 60          # entry allowed 15 min before the reserved start
MAX_HOURS = 8
OVERSTAY_FACTOR = 0.5    # +50% of hourly rate for every started overstay hour
ACTIVE = ("reserved", "parked", "awaiting_payment")


# ------------------------------------------------------------------ fee (pure function)
def compute_fee(entry_ts, exit_ts, end_ts, rate):
    """Fee = billed hours x rate (min 1h, part hours round up) + overstay penalty."""
    parked_min = max(0.0, (exit_ts - entry_ts) / 60)
    billed_hours = max(1, math.ceil(round(parked_min, 6) / 60))
    base = billed_hours * rate
    over_min = max(0.0, (exit_ts - end_ts) / 60)
    over_hours = math.ceil(round(over_min, 6) / 60) if over_min > 0 else 0
    penalty = over_hours * rate * OVERSTAY_FACTOR
    return {"parked_minutes": round(parked_min, 1), "billed_hours": billed_hours, "rate": rate,
            "base": round(base, 2), "overstay_hours": over_hours, "overstay_penalty": round(penalty, 2),
            "total": round(base + penalty, 2), "currency": "INR (simulated)"}


# ------------------------------------------------------------------ housekeeping & state
def housekeeping(db, ts):
    """Reservations whose window passed without entry become 'expired' (slot is freed)."""
    rows = db.execute("SELECT r.id, r.user_id, s.label FROM reservations r JOIN slots s ON s.id=r.slot_id "
                      "WHERE r.status='reserved' AND r.end_ts < ?", (ts,)).fetchall()
    for r in rows:
        db.execute("UPDATE reservations SET status='expired' WHERE id=? AND status='reserved'", (r["id"],))
        if r["user_id"]:
            notify(db, f"Reservation #{r['id']} for slot {r['label']} expired (no entry). Slot released.",
                   "warning", user_id=r["user_id"])


def compute_states(db, ts, win=None):
    """Derive the live state of each slot from sensor flag + reservations.
    states: free | reserved | occupied | payment_due | mismatch | maintenance"""
    slots = db.execute("SELECT s.*, l.code lot_code FROM slots s JOIN lots l ON l.id=s.lot_id ORDER BY s.lot_id, s.id").fetchall()
    by_slot = {}
    for r in db.execute("SELECT * FROM reservations WHERE status IN ('reserved','parked','awaiting_payment')"):
        by_slot.setdefault(r["slot_id"], []).append(r)
    out = {}
    for s in slots:
        rs = by_slot.get(s["id"], [])
        parked = next((r for r in rs if r["status"] == "parked"), None)
        pay = next((r for r in rs if r["status"] == "awaiting_payment"), None)
        now_res = next((r for r in rs if r["status"] == "reserved" and r["start_ts"] - GRACE <= ts <= r["end_ts"]), None)
        current = None
        if s["maintenance"]:
            state = "maintenance"
        elif parked:
            state, current = "occupied", parked
        elif pay:
            state, current = "payment_due", pay
        elif s["sensor"] == "occupied":
            state, current = "mismatch", now_res
        elif now_res:
            state, current = "reserved", now_res
        else:
            state = "free"
        later = any(r["status"] == "reserved" and r["start_ts"] - GRACE > ts for r in rs)
        bookable = not s["maintenance"]
        if bookable and win:
            ws, we = win
            for r in rs:
                rs_, re_ = r["start_ts"], r["end_ts"]
                if r["status"] in ("parked", "awaiting_payment"):
                    re_ = max(re_, ts)
                if ws < re_ and rs_ < we:
                    bookable = False
            if ws <= ts + GRACE and s["sensor"] == "occupied" and not parked:
                bookable = False
        out[s["id"]] = {"slot": s, "state": state, "current": current, "later": later, "bookable": bookable}
    return out


# ------------------------------------------------------------------ simulated sensor logic
def _open_alert(db, slot_id, kind, detail):
    if not db.execute("SELECT 1 FROM sensor_alerts WHERE slot_id=? AND kind=? AND resolved=0", (slot_id, kind)).fetchone():
        db.execute("INSERT INTO sensor_alerts(slot_id,kind,detail,created_ts) VALUES(?,?,?,?)",
                   (slot_id, kind, detail, now()))
        notify(db, f"Sensor mismatch: {detail}", "critical", audience="admin")


def apply_sensor_event(db, slot, state, ts, extra_min=0):
    """Core of the (SIMULATED) IoT sensor. Must be called inside a tx."""
    sid, label = slot["id"], slot["label"]
    parked = db.execute("SELECT * FROM reservations WHERE slot_id=? AND status='parked'", (sid,)).fetchone()
    if state == "occupied":
        res = db.execute("SELECT * FROM reservations WHERE slot_id=? AND status='reserved' AND start_ts-?<=? AND end_ts>=? "
                         "ORDER BY start_ts LIMIT 1", (sid, GRACE, ts, ts)).fetchone()
        if parked or slot["sensor"] == "occupied":
            if not parked and res:
                _open_alert(db, sid, "slot_blocked",
                            f"Slot {label} holds reservation #{res['id']} but its sensor already reports a different vehicle.")
                return {"outcome": "blocked", "message": f"Slot {label} is physically occupied by another vehicle."}
            return {"outcome": "noop", "message": f"Slot {label} already reported occupied."}
        db.execute("UPDATE slots SET sensor='occupied' WHERE id=?", (sid,))
        if res:
            db.execute("UPDATE reservations SET status='parked', entry_ts=? WHERE id=?", (ts, res["id"]))
            if res["user_id"]:
                notify(db, f"Entry recorded at slot {label}. Parking timer started.", "success", user_id=res["user_id"])
            return {"outcome": "entry", "reservation_id": res["id"], "message": f"Entry recorded at slot {label}."}
        _open_alert(db, sid, "unreserved_occupancy",
                    f"Sensor reports slot {label} occupied but there is no active reservation.")
        return {"outcome": "mismatch", "message": f"Slot {label}: occupied without reservation. Admin alerted."}
    # state == 'free'
    if parked:
        exit_ts = ts + extra_min * 60
        rate = db.execute("SELECT rate_per_hour FROM lots WHERE id=?", (slot["lot_id"],)).fetchone()[0]
        fee = compute_fee(parked["entry_ts"], exit_ts, parked["end_ts"], rate)
        status = "completed" if parked["user_id"] is None else "awaiting_payment"
        db.execute("UPDATE reservations SET status=?, exit_ts=?, fee=?, fee_json=? WHERE id=?",
                   (status, exit_ts, fee["total"], json.dumps(fee), parked["id"]))
        db.execute("UPDATE slots SET sensor='free' WHERE id=?", (sid,))
        if parked["user_id"]:
            notify(db, f"Exit recorded at slot {label}. Fee due: ₹{fee['total']:.2f} (simulated). Pay to release the slot.",
                   "info", user_id=parked["user_id"])
        return {"outcome": "exit", "reservation_id": parked["id"], "fee": fee, "message": f"Exit recorded at slot {label}."}
    db.execute("UPDATE slots SET sensor='free' WHERE id=?", (sid,))
    cur = db.execute("UPDATE sensor_alerts SET resolved=1 WHERE slot_id=? AND resolved=0", (sid,))
    if cur.rowcount:
        return {"outcome": "mismatch_cleared", "message": f"Slot {label} sensor reports free; open alert cleared."}
    return {"outcome": "noop", "message": f"Slot {label} already reported free."}


# ------------------------------------------------------------------ serialisers
def res_json(r, db, ts, admin=False):
    s = db.execute("SELECT s.label, l.name lot_name, l.rate_per_hour FROM slots s JOIN lots l ON l.id=s.lot_id WHERE s.id=?",
                   (r["slot_id"],)).fetchone()
    d = {"id": r["id"], "slot_id": r["slot_id"], "slot": s["label"], "lot": s["lot_name"], "vehicle_no": r["vehicle_no"],
         "start_ts": r["start_ts"], "end_ts": r["end_ts"], "status": r["status"], "source": r["source"],
         "entry_ts": r["entry_ts"], "exit_ts": r["exit_ts"], "fee": r["fee"],
         "fee_breakdown": json.loads(r["fee_json"]) if r["fee_json"] else None}
    if r["status"] == "parked":
        d["fee_so_far"] = compute_fee(r["entry_ts"], ts, r["end_ts"], s["rate_per_hour"])["total"]
    if admin:
        u = db.execute("SELECT username FROM users WHERE id=?", (r["user_id"],)).fetchone() if r["user_id"] else None
        d["user"] = u["username"] if u else "walk-in"
    return d


def fmt_clock(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _own_res(db, rid):
    r = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ApiError(404, f"Reservation #{rid} not found.", "not_found")
    if g.user["role"] != "admin" and r["user_id"] != g.user["id"]:
        raise ApiError(403, "That reservation belongs to another user.", "forbidden")
    return r


# ------------------------------------------------------------------ endpoints
@bp.get("/parking")
@login_required()
def parking():
    db, ts = get_db(), now()
    housekeeping(db, ts)
    start = request.args.get("start_ts", type=float) or ts
    hours = request.args.get("duration_hours", default=1, type=int)
    hours = min(max(hours, 1), MAX_HOURS)
    states = compute_states(db, ts, (start, start + hours * 3600))
    lots = []
    for l in db.execute("SELECT * FROM lots ORDER BY id"):
        counts = dict.fromkeys(("free", "reserved", "occupied", "payment_due", "mismatch", "maintenance"), 0)
        slots = []
        for sid, st in states.items():
            if st["slot"]["lot_id"] != l["id"]:
                continue
            counts[st["state"]] += 1
            cur = st["current"]
            slots.append({"id": sid, "label": st["slot"]["label"], "state": st["state"], "bookable": st["bookable"],
                          "reserved_later": st["later"], "sensor": st["slot"]["sensor"],
                          "mine": bool(cur and cur["user_id"] == g.user["id"]),
                          "vehicle_no": cur["vehicle_no"] if cur and g.user["role"] == "admin" else None})
        lots.append({"id": l["id"], "code": l["code"], "name": l["name"], "rate_per_hour": l["rate_per_hour"],
                     "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"], "cols": l["cols"], "kind": l["kind"],
                     "counts": counts, "total": len(slots), "slots": slots})
    totals = {k: sum(l["counts"][k] for l in lots) for k in lots[0]["counts"]}
    return jsonify({"lots": lots, "totals": totals, "server_ts": ts, "sensor_source": "SIMULATED"})


@bp.post("/reservations")
@login_required("student")
def reserve():
    d = body()
    slot_id = as_int(d, "slot_id", 1, label="Slot")
    hours = as_int(d, "duration_hours", 1, MAX_HOURS, label="Duration (hours)")
    vehicle = normalize_vehicle(d.get("vehicle_no"))
    if not vehicle:
        raise ApiError(400, "Vehicle number is required.", "validation", {"vehicle_no": "required"})
    if not VEHICLE_RE.match(vehicle):
        raise ApiError(400, "Vehicle number looks invalid. Expected format like MH12AB1234.", "validation", {"vehicle_no": "format"})
    db, ts = get_db(), now()
    start = d.get("start_ts")
    if start in (None, ""):
        start = ts
    try:
        start = float(start)
    except (TypeError, ValueError):
        raise ApiError(400, "Start time is invalid.", "validation", {"start_ts": "invalid"})
    if start < ts - 60:
        raise ApiError(400, "Start time cannot be in the past.", "validation", {"start_ts": "past"})
    if start > ts + 24 * 3600:
        raise ApiError(400, "You can reserve at most 24 hours ahead.", "validation", {"start_ts": "too_far"})
    start = max(start, ts)
    end = start + hours * 3600
    with tx(db):
        housekeeping(db, ts)
        slot = db.execute("SELECT s.*, l.name lot_name FROM slots s JOIN lots l ON l.id=s.lot_id WHERE s.id=?", (slot_id,)).fetchone()
        if not slot:
            raise ApiError(404, "That parking slot does not exist.", "not_found", {"slot_id": "unknown"})
        mine = db.execute("SELECT id FROM reservations WHERE user_id=? AND status IN ('reserved','parked','awaiting_payment')",
                          (g.user["id"],)).fetchone()
        if mine:
            raise ApiError(409, f"You already have an active reservation (#{mine['id']}). Cancel or complete it first.", "already_active")
        st = compute_states(db, ts, (start, end))[slot_id]
        if slot["maintenance"]:
            raise ApiError(409, f"Slot {slot['label']} is under maintenance.", "maintenance")
        if not st["bookable"]:
            raise ApiError(409, f"Slot {slot['label']} is not available for that time (just taken, occupied or flagged by sensor). "
                                "Please choose another slot.", "slot_conflict")
        cur = db.execute("INSERT INTO reservations(slot_id,user_id,vehicle_no,start_ts,end_ts,status,created_ts) "
                         "VALUES(?,?,?,?,?,'reserved',?)", (slot_id, g.user["id"], vehicle, start, end, ts))
        notify(db, f"Reservation #{cur.lastrowid} confirmed: slot {slot['label']}, {fmt_clock(start)}–{fmt_clock(end)}.",
               "success", user_id=g.user["id"])
        r = db.execute("SELECT * FROM reservations WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"reservation": res_json(r, db, ts)}), 201


@bp.get("/reservations")
@login_required()
def my_reservations():
    db, ts = get_db(), now()
    housekeeping(db, ts)
    if g.user["role"] == "admin":
        rows = db.execute("SELECT * FROM reservations ORDER BY id DESC LIMIT 100").fetchall()
    else:
        rows = db.execute("SELECT * FROM reservations WHERE user_id=? ORDER BY id DESC LIMIT 50", (g.user["id"],)).fetchall()
    return jsonify({"reservations": [res_json(r, db, ts, g.user["role"] == "admin") for r in rows]})


@bp.post("/reservations/<int:rid>/cancel")
@login_required()
def cancel(rid):
    db, ts = get_db(), now()
    with tx(db):
        r = _own_res(db, rid)
        if r["status"] != "reserved":
            raise ApiError(409, f"Only a reservation that has not started parking can be cancelled (this one is '{r['status']}').", "bad_state")
        db.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (rid,))
        label = db.execute("SELECT label FROM slots WHERE id=?", (r["slot_id"],)).fetchone()[0]
        if r["user_id"]:
            notify(db, f"Reservation #{rid} cancelled. Slot {label} is available again.", "info", user_id=r["user_id"])
        r = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    return jsonify({"reservation": res_json(r, db, ts)})


@bp.post("/reservations/<int:rid>/entry")
@login_required()
def entry(rid):
    """Student arrives at the slot -> SIMULATED sensor reports 'occupied'."""
    db, ts = get_db(), now()
    with tx(db):
        housekeeping(db, ts)
        r = _own_res(db, rid)
        if r["status"] == "parked":
            raise ApiError(409, "Entry already recorded for this reservation.", "bad_state")
        if r["status"] != "reserved":
            raise ApiError(409, f"Cannot enter: reservation is '{r['status']}'.", "bad_state")
        if ts < r["start_ts"] - GRACE:
            raise ApiError(409, f"Too early: entry opens at {fmt_clock(r['start_ts'] - GRACE)}.", "too_early")
        slot = db.execute("SELECT * FROM slots WHERE id=?", (r["slot_id"],)).fetchone()
        out = apply_sensor_event(db, slot, "occupied", ts)
        if out["outcome"] != "entry":
            db.execute("COMMIT")  # keep the alert we just raised, then report the conflict
            db.execute("BEGIN IMMEDIATE")
            raise ApiError(409, out["message"] + " A mismatch alert was sent to the parking attendant.", "sensor_mismatch")
        r = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    return jsonify({"reservation": res_json(r, db, ts), "sensor": out, "simulated": True})


@bp.post("/reservations/<int:rid>/exit")
@login_required()
def exit_(rid):
    """Student leaves -> SIMULATED sensor reports 'free'; fee is calculated.
    `simulate_minutes` (demo only) fast-forwards parked time so fees are visible in a short demo."""
    d = request.get_json(silent=True) or {}
    extra = as_int(d, "simulate_minutes", 0, 720, required=False, label="Simulated minutes") or 0
    db, ts = get_db(), now()
    with tx(db):
        r = _own_res(db, rid)
        if r["status"] != "parked":
            raise ApiError(409, f"Cannot exit: vehicle is not parked under this reservation (status '{r['status']}').", "bad_state")
        slot = db.execute("SELECT * FROM slots WHERE id=?", (r["slot_id"],)).fetchone()
        out = apply_sensor_event(db, slot, "free", ts, extra)
        r = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    return jsonify({"reservation": res_json(r, db, ts), "sensor": out, "simulated": True})


def _gateway(method, d):
    """SIMULATED payment gateway. No real money, cards or UPI are touched."""
    if method not in ("UPI", "CARD", "WALLET"):
        raise ApiError(400, "Choose a payment method: UPI, CARD or WALLET.", "validation", {"method": "invalid"})
    if method == "UPI" and not re.fullmatch(r"[\w.\-]{2,}@[a-zA-Z]{2,}", str(d.get("upi_id", "")).strip()):
        raise ApiError(400, "Enter a valid UPI ID, e.g. name@bank.", "validation", {"upi_id": "format"})
    if method == "CARD":
        card = re.sub(r"[\s-]", "", str(d.get("card_number", "")))
        if not re.fullmatch(r"\d{16}", card):
            raise ApiError(400, "Card number must be 16 digits (use a test number).", "validation", {"card_number": "format"})
        if card == "4000000000000002":
            return False, "Card declined – insufficient funds (simulated test card)."
    if d.get("simulate_failure"):
        return False, "Gateway timeout – failure forced by the demo switch (simulated)."
    return True, "Approved (simulated)"


@bp.post("/reservations/<int:rid>/pay")
@login_required()
def pay(rid):
    d = body()
    method = str(d.get("method", "")).upper()
    db, ts = get_db(), now()
    with tx(db):
        r = _own_res(db, rid)
        if r["status"] == "completed":
            raise ApiError(409, "This reservation is already paid. Duplicate payment blocked.", "already_paid")
        if r["status"] != "awaiting_payment":
            raise ApiError(409, f"Nothing to pay yet: reservation is '{r['status']}'. Exit the slot first.", "bad_state")
        ok, reason = _gateway(method, d)
        db.execute("INSERT INTO payments(reservation_id,amount,method,status,reason,created_ts) VALUES(?,?,?,?,?,?)",
                   (rid, r["fee"], method, "success" if ok else "failed", reason, ts))
        label = db.execute("SELECT label FROM slots WHERE id=?", (r["slot_id"],)).fetchone()[0]
        if ok:
            db.execute("UPDATE reservations SET status='completed' WHERE id=?", (rid,))
            notify(db, f"Payment of ₹{r['fee']:.2f} received (simulated). Slot {label} released. Thank you!", "success", user_id=r["user_id"])
        else:
            notify(db, f"Payment failed for reservation #{rid}: {reason} Slot {label} stays on hold – please retry.", "warning", user_id=r["user_id"])
        r = db.execute("SELECT * FROM reservations WHERE id=?", (rid,)).fetchone()
    if not ok:
        raise ApiError(402, f"Payment failed: {reason} Your slot remains on hold – please retry.", "payment_failed")
    return jsonify({"reservation": res_json(r, db, ts), "payment": {"status": "success", "simulated": True, "message": reason}})
