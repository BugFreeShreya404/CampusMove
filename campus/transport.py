"""Campus transport: routes, stops, schedules, SIMULATED bus GPS, admin updates, alerts."""
import math
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from .auth import login_required, notify
from .util import ApiError, TIME_RE, as_int, as_text, body, get_db, hhmm_to_min, now, tx

bp = Blueprint("transport", __name__, url_prefix="/api")

STALE_AFTER = 20  # seconds without a GPS ping before a bus is shown as "stale"
# Simulated coordinates: map canvas units (1 unit = 1 m) anchored to an approximate campus point.
ANCHOR_LAT, ANCHOR_LON = 18.4885, 74.0227


def to_latlon(x, y):
    return round(ANCHOR_LAT + (310 - y) * 0.000009, 6), round(ANCHOR_LON + (x - 500) * 0.0000095, 6)


# ------------------------------------------------------------------ geometry
def route_stops(db, route_id):
    return db.execute("SELECT st.id, st.name, st.x, st.y FROM route_stops rs JOIN stops st ON st.id=rs.stop_id "
                      "WHERE rs.route_id=? ORDER BY rs.seq", (route_id,)).fetchall()


def geometry(stops):
    """Circular route: last stop connects back to the first."""
    pts = [(s["x"], s["y"]) for s in stops]
    loop = pts + [pts[0]]
    cum = [0.0]
    for a, b in zip(loop, loop[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    return loop, cum


def point_at(loop, cum, d):
    total = cum[-1]
    d = d % total if total else 0
    for i in range(len(loop) - 1):
        if cum[i] <= d <= cum[i + 1]:
            seg = cum[i + 1] - cum[i] or 1
            t = (d - cum[i]) / seg
            return (loop[i][0] + (loop[i + 1][0] - loop[i][0]) * t, loop[i][1] + (loop[i + 1][1] - loop[i][1]) * t)
    return loop[0]


def tick(db, ts):
    """Advance every bus whose (simulated) GPS is enabled, based on elapsed wall time."""
    routes = {r["id"]: r for r in db.execute("SELECT * FROM routes")}
    geo = {}
    for b in db.execute("SELECT * FROM buses").fetchall():
        if not b["gps_enabled"]:
            continue
        r = routes[b["route_id"]]
        if b["route_id"] not in geo:
            geo[b["route_id"]] = geometry(route_stops(db, b["route_id"]))
        loop, cum = geo[b["route_id"]]
        dist = b["distance"] or 0
        if r["status"] == "active" and b["last_update_ts"]:
            dist += b["speed_mps"] * min(max(ts - b["last_update_ts"], 0), 60)
        dist = dist % cum[-1] if cum[-1] else 0
        x, y = point_at(loop, cum, dist)
        db.execute("UPDATE buses SET distance=?, x=?, y=?, last_update_ts=? WHERE id=?", (dist, x, y, ts, b["id"]))


def bus_json(db, b, route, geo, ts):
    loop, cum = geo
    stops = route_stops(db, b["route_id"])
    d = {"id": b["id"], "plate": b["plate"], "route_id": b["route_id"], "route_code": route["code"], "color": route["color"],
         "gps_enabled": bool(b["gps_enabled"]), "gps_source": "SIMULATED", "x": None, "y": None, "lat": None, "lon": None,
         "age_s": None, "next_stop": None, "eta_s": None, "speed_kmh": round(b["speed_mps"] * 3.6)}
    if b["x"] is None or b["last_update_ts"] is None:
        d["freshness"] = "unavailable"
        d["message"] = "Location unavailable – no GPS ping received yet."
        return d
    age = ts - b["last_update_ts"]
    d.update(x=round(b["x"], 1), y=round(b["y"], 1), age_s=round(age))
    d["lat"], d["lon"] = to_latlon(b["x"], b["y"])
    if route["status"] != "active":
        d["freshness"] = "out_of_service"
        d["message"] = "Route suspended – bus not in service."
    elif age > STALE_AFTER:
        d["freshness"] = "stale"
        d["message"] = f"Last known position, updated {round(age)}s ago – may be inaccurate."
    else:
        d["freshness"] = "live"
        d["message"] = "Live (simulated GPS)"
    if route["status"] == "active" and stops and cum[-1]:
        dist = b["distance"] or 0
        best = None
        for i, s in enumerate(stops):
            gap = (cum[i] - dist) % cum[-1]
            if gap < 1:
                gap = cum[-1]
            if best is None or gap < best[0]:
                best = (gap, s)
        d["next_stop"] = best[1]["name"]
        d["eta_s"] = round(best[0] / b["speed_mps"])
    return d


def next_departures(route, ts, n=4):
    f, l, step = hhmm_to_min(route["first_departure"]), hhmm_to_min(route["last_departure"]), route["frequency_min"]
    t = datetime.fromtimestamp(ts)
    cur = t.hour * 60 + t.minute
    times = [m for m in range(f, l + 1, step) if m >= cur][:n]
    return [f"{m // 60:02d}:{m % 60:02d}" for m in times]


def route_json(db, r, ts):
    stops = route_stops(db, r["id"])
    f, l, step = hhmm_to_min(r["first_departure"]), hhmm_to_min(r["last_departure"]), r["frequency_min"]
    return {"id": r["id"], "code": r["code"], "name": r["name"], "color": r["color"], "status": r["status"],
            "first_departure": r["first_departure"], "last_departure": r["last_departure"], "frequency_min": step,
            "note": r["note"], "stops": [{"id": s["id"], "name": s["name"], "x": s["x"], "y": s["y"]} for s in stops],
            "trips_per_day": len(range(f, l + 1, step)), "next_departures": next_departures(r, ts)}


# ------------------------------------------------------------------ read endpoints
@bp.get("/transport/overview")
@login_required()
def overview():
    db, ts = get_db(), now()
    tick(db, ts)
    routes = db.execute("SELECT * FROM routes ORDER BY id").fetchall()
    return jsonify({"routes": [route_json(db, r, ts) for r in routes],
                    "stops": [dict(s) for s in db.execute("SELECT * FROM stops ORDER BY id")],
                    "buses": _buses(db, ts), "stale_after_s": STALE_AFTER, "server_ts": ts, "gps_source": "SIMULATED"})


def _buses(db, ts):
    routes = {r["id"]: r for r in db.execute("SELECT * FROM routes")}
    geo = {}
    out = []
    for b in db.execute("SELECT * FROM buses ORDER BY id"):
        if b["route_id"] not in geo:
            geo[b["route_id"]] = geometry(route_stops(db, b["route_id"]))
        out.append(bus_json(db, b, routes[b["route_id"]], geo[b["route_id"]], ts))
    return out


@bp.get("/buses")
@login_required()
def buses():
    db, ts = get_db(), now()
    tick(db, ts)
    return jsonify({"buses": _buses(db, ts), "server_ts": ts, "gps_source": "SIMULATED", "stale_after_s": STALE_AFTER})


@bp.get("/routes/<rid>")
@login_required()
def route_detail(rid):
    if not rid.isdigit():
        raise ApiError(404, f"'{rid}' is not a valid route id.", "invalid_route")
    db, ts = get_db(), now()
    r = db.execute("SELECT * FROM routes WHERE id=?", (int(rid),)).fetchone()
    if not r:
        raise ApiError(404, f"Route {rid} does not exist.", "invalid_route")
    return jsonify({"route": route_json(db, r, ts)})


# ------------------------------------------------------------------ admin updates
@bp.put("/admin/routes/<rid>")
@login_required("admin")
def update_route(rid):
    if not rid.isdigit():
        raise ApiError(404, f"'{rid}' is not a valid route id.", "invalid_route")
    d = body()
    db, ts = get_db(), now()
    with tx(db):
        r = db.execute("SELECT * FROM routes WHERE id=?", (int(rid),)).fetchone()
        if not r:
            raise ApiError(404, f"Route {rid} does not exist.", "invalid_route")
        old = route_json(db, r, ts)
        first = as_text(d, "first_departure", 5, 5, required=False, label="First departure") or r["first_departure"]
        last = as_text(d, "last_departure", 5, 5, required=False, label="Last departure") or r["last_departure"]
        for k, v in (("first_departure", first), ("last_departure", last)):
            if not TIME_RE.match(v):
                raise ApiError(400, "Times must be in 24-hour HH:MM format (e.g. 07:30).", "validation", {k: "format"})
        if hhmm_to_min(last) <= hhmm_to_min(first):
            raise ApiError(400, "Last departure must be later than first departure.", "validation", {"last_departure": "order"})
        freq = as_int(d, "frequency_min", 5, 60, required=False, label="Frequency (minutes)") or r["frequency_min"]
        status = d.get("status", r["status"])
        if status not in ("active", "suspended"):
            raise ApiError(400, "Status must be 'active' or 'suspended'.", "validation", {"status": "invalid"})
        note = as_text(d, "note", 0, 160, required=False, label="Note") if "note" in d else r["note"]
        stop_ids = None
        if "stops" in d:
            raw = d["stops"]
            if not isinstance(raw, list) or len(raw) < 2:
                raise ApiError(400, "A route needs at least 2 stops.", "validation", {"stops": "min 2"})
            try:
                stop_ids = [int(x) for x in raw]
            except (TypeError, ValueError):
                raise ApiError(400, "Stops must be a list of stop ids.", "validation", {"stops": "invalid"})
            known = {s["id"] for s in db.execute("SELECT id FROM stops")}
            bad = [x for x in stop_ids if x not in known]
            if bad:
                raise ApiError(400, f"Unknown stop id(s): {bad}.", "validation", {"stops": "unknown"})
            if len(set(stop_ids)) != len(stop_ids):
                raise ApiError(400, "A stop cannot appear twice in the same route.", "validation", {"stops": "duplicate"})
        db.execute("UPDATE routes SET first_departure=?, last_departure=?, frequency_min=?, status=?, note=? WHERE id=?",
                   (first, last, freq, status, note, r["id"]))
        if stop_ids is not None:
            db.execute("DELETE FROM route_stops WHERE route_id=?", (r["id"],))
            for seq, sid in enumerate(stop_ids):
                db.execute("INSERT INTO route_stops VALUES(?,?,?)", (r["id"], seq, sid))
            db.execute("UPDATE buses SET distance=0 WHERE route_id=?", (r["id"],))
        new = route_json(db, db.execute("SELECT * FROM routes WHERE id=?", (r["id"],)).fetchone(), ts)
        changes = []
        if old["first_departure"] != new["first_departure"] or old["last_departure"] != new["last_departure"]:
            changes.append(f"timings {old['first_departure']}–{old['last_departure']} → {new['first_departure']}–{new['last_departure']}")
        if old["frequency_min"] != new["frequency_min"]:
            changes.append(f"frequency every {old['frequency_min']} → {new['frequency_min']} min")
        if old["status"] != new["status"]:
            changes.append("service SUSPENDED" if new["status"] == "suspended" else "service RESUMED")
        if [s["id"] for s in old["stops"]] != [s["id"] for s in new["stops"]]:
            changes.append("stops: " + " → ".join(s["name"] for s in new["stops"]))
        if old["note"] != new["note"] and new["note"]:
            changes.append(f"note: {new['note']}")
        if changes:
            notify(db, f"Route {r['code']} ({r['name']}) updated – " + "; ".join(changes) + ".", "warning")
    return jsonify({"route": new, "changed": bool(changes), "changes": changes})


@bp.post("/admin/buses/<int:bid>/gps")
@login_required("admin")
def bus_gps(bid):
    d = body()
    if not isinstance(d.get("enabled"), bool):
        raise ApiError(400, "'enabled' must be true or false.", "validation", {"enabled": "boolean"})
    db, ts = get_db(), now()
    with tx(db):
        b = db.execute("SELECT * FROM buses WHERE id=?", (bid,)).fetchone()
        if not b:
            raise ApiError(404, f"Bus {bid} does not exist.", "not_found")
        # re-enabling resets the ping clock so the bus does not "jump"
        db.execute("UPDATE buses SET gps_enabled=?, last_update_ts=CASE WHEN ?=1 THEN ? ELSE last_update_ts END WHERE id=?",
                   (int(d["enabled"]), int(d["enabled"]), ts, bid))
    tick(db, ts)
    return jsonify({"ok": True, "bus_id": bid, "gps_enabled": d["enabled"]})


@bp.post("/admin/alerts")
@login_required("admin")
def post_alert():
    d = body()
    msg = as_text(d, "message", 5, 200, label="Alert message")
    sev = d.get("severity", "warning")
    if sev not in ("info", "warning", "critical"):
        raise ApiError(400, "Severity must be info, warning or critical.", "validation", {"severity": "invalid"})
    db = get_db()
    prefix = ""
    if d.get("route_id") not in (None, ""):
        rid = as_int(d, "route_id", 1, label="Route")
        r = db.execute("SELECT code FROM routes WHERE id=?", (rid,)).fetchone()
        if not r:
            raise ApiError(404, f"Route {rid} does not exist.", "invalid_route")
        prefix = f"[{r['code']}] "
    with tx(db):
        notify(db, prefix + msg, sev)
    return jsonify({"ok": True}), 201
