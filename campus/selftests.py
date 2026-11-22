"""Executable test cases (expected vs actual). Each case runs against a fresh temporary database,
so it is safe to run from the Admin page during the jury. Also used by tests/test_api.py (pytest/unittest)."""
import os
import tempfile
import time

from . import create_app
from .parking import compute_fee

CASES = []


def case(cid, name, kind, expected):
    def deco(fn):
        CASES.append({"id": cid, "name": name, "type": kind, "expected": expected, "fn": fn})
        return fn
    return deco


class Ctx:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="campus_test_")
        self.app = create_app(os.path.join(self.dir, "t.db"))
        self.client = self.app.test_client()
        self._h = {}

    def api(self, method, path, who=None, json=None):
        h = {"Authorization": f"Bearer {self.token(who)}"} if who else {}
        r = self.client.open(path, method=method, headers=h, json=json)
        return r.status_code, r.get_json(silent=True) or {}

    USERS = {"student1": ("Shreya Kanade", "shreya123"), "student2": ("Abhijit More", "abhijit123"), "admin": ("admin", "admin123")}

    def token(self, who):
        if who not in self._h:
            user, pw = self.USERS[who]
            r = self.client.post("/api/login", json={"username": user, "password": pw})
            self._h[who] = r.get_json()["token"]
        return self._h[who]

    def slots(self, who="student1", state="free", lot=None):
        _, d = self.api("GET", "/api/parking", who)
        return [s["id"] for l in d["lots"] if lot in (None, l["code"]) for s in l["slots"] if s["state"] == state and s["bookable"]]

    def slot_state(self, sid, who="admin"):
        _, d = self.api("GET", "/api/parking", who)
        return next(s["state"] for l in d["lots"] for s in l["slots"] if s["id"] == sid)

    def reserve(self, who, sid, hours=1, plate="MH12AB1234", **kw):
        return self.api("POST", "/api/reservations", who, {"slot_id": sid, "duration_hours": hours, "vehicle_no": plate, **kw})

    def route_view(self, who, rid):
        return self.api("GET", f"/api/routes/{rid}", who)


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ------------------------------------------------------------------ authentication & access
@case("TC-01", "Valid student login", "Positive", "HTTP 200, token issued, role = student")
def _(c):
    st, d = c.api("POST", "/api/login", json={"username": "Shreya Kanade", "password": "shreya123"})
    ok(st == 200 and d["user"]["role"] == "student" and d["token"], f"status {st}")
    return f"HTTP {st}, role={d['user']['role']}, token issued"


@case("TC-02", "Login with wrong password", "Negative", "HTTP 401 'Invalid username or password.'")
def _(c):
    st, d = c.api("POST", "/api/login", json={"username": "Shreya Kanade", "password": "nope"})
    ok(st == 401, f"status {st}")
    return f"HTTP {st}: {d['error']['message']}"


@case("TC-03", "Student calls admin API / anonymous call", "Negative", "Student -> 403 Forbidden; no token -> 401")
def _(c):
    a, _ = c.api("POST", "/api/admin/sensors", "student1", {"slot_id": 1, "state": "occupied"})
    b, _ = c.api("GET", "/api/parking")
    ok(a == 403 and b == 401, f"{a}/{b}")
    return f"student -> HTTP {a}; anonymous -> HTTP {b}"


# ------------------------------------------------------------------ parking workflow
@case("TC-04", "Availability totals add up", "Positive", "Per-lot counts sum to the 102 seeded slots (incl. 30 basement slots); 1 maintenance, 20 walk-in")
def _(c):
    _, d = c.api("GET", "/api/parking", "student1")
    total = sum(d["totals"].values())
    ok(total == 102 and d["totals"]["maintenance"] == 1 and d["totals"]["occupied"] == 20, str(d["totals"]))
    return f"total={total}, totals={d['totals']}"


@case("TC-05", "Reserve a free slot (valid input)", "Positive", "HTTP 201, reservation 'reserved', slot turns 'reserved'")
def _(c):
    sid = c.slots(lot="A")[0]
    st, d = c.reserve("student1", sid)
    ok(st == 201 and d["reservation"]["status"] == "reserved", f"{st}")
    s = c.slot_state(sid)
    ok(s == "reserved", s)
    return f"HTTP {st}, status={d['reservation']['status']}, slot state={s}"


@case("TC-06", "Competing reservations for the same slot", "Negative", "2nd student gets HTTP 409 'slot_conflict'; first booking untouched")
def _(c):
    sid = c.slots(lot="A")[0]
    a, _ = c.reserve("student1", sid)
    b, d = c.reserve("student2", sid, plate="MH14CD5678")
    ok(a == 201 and b == 409 and d["error"]["code"] == "slot_conflict", f"{a}/{b}")
    return f"student1 -> HTTP {a}; student2 -> HTTP {b} ({d['error']['code']})"


@case("TC-07", "Invalid vehicle number / missing field", "Negative", "HTTP 400 with field error; nothing saved")
def _(c):
    sid = c.slots()[0]
    a, d = c.reserve("student1", sid, plate="ABC")
    b, _ = c.api("POST", "/api/reservations", "student1", {"slot_id": sid, "duration_hours": 1})
    ok(a == 400 and b == 400 and "vehicle_no" in d["error"]["fields"], f"{a}/{b}")
    return f"'ABC' -> HTTP {a} ({d['error']['message']}); missing plate -> HTTP {b}"


@case("TC-08", "Duration boundary values (0, 1, 8, 9 hours)", "Boundary", "0 and 9 rejected (400); 1 accepted; 8 accepted")
def _(c):
    s = c.slots()
    r0, _ = c.reserve("student1", s[0], 0)
    r9, _ = c.reserve("student1", s[0], 9)
    r1, d1 = c.reserve("student1", s[0], 1)
    c.api("POST", f"/api/reservations/{d1['reservation']['id']}/cancel", "student1")
    r8, _ = c.reserve("student1", s[0], 8)
    ok((r0, r9, r1, r8) == (400, 400, 201, 201), f"{r0},{r9},{r1},{r8}")
    return f"0h -> {r0}, 9h -> {r9}, 1h -> {r1}, 8h -> {r8}"


@case("TC-09", "Second active reservation by same user", "Negative", "HTTP 409 'already_active'")
def _(c):
    s = c.slots()
    c.reserve("student1", s[0])
    st, d = c.reserve("student1", s[1])
    ok(st == 409 and d["error"]["code"] == "already_active", f"{st}")
    return f"HTTP {st}: {d['error']['message']}"


@case("TC-10", "Cancel reservation releases the slot", "Positive", "Cancel -> slot 'free' again and another student can book it")
def _(c):
    sid = c.slots()[0]
    _, d = c.reserve("student1", sid)
    st, _ = c.api("POST", f"/api/reservations/{d['reservation']['id']}/cancel", "student1")
    after = c.slot_state(sid)
    again, _ = c.reserve("student2", sid, plate="MH14CD5678")
    ok(st == 200 and after == "free" and again == 201, f"{st},{after},{again}")
    return f"cancel -> {st}, slot={after}, rebook by student2 -> {again}"


@case("TC-11", "Entry too early (reservation 3 h ahead)", "Boundary", "HTTP 409 'too_early' (entry opens 15 min before start)")
def _(c):
    sid = c.slots()[0]
    _, d = c.reserve("student1", sid, start_ts=time.time() + 3 * 3600)
    st, e = c.api("POST", f"/api/reservations/{d['reservation']['id']}/entry", "student1")
    ok(st == 409 and e["error"]["code"] == "too_early", f"{st}")
    return f"HTTP {st}: {e['error']['message']}"


@case("TC-12", "Full flow: entry -> exit -> fee -> pay -> slot released", "Positive", "parked -> awaiting_payment (fee shown) -> completed; slot free again")
def _(c):
    sid = c.slots(lot="C")[0]  # lot C = Rs 5/h
    _, d = c.reserve("student1", sid, 2)
    rid = d["reservation"]["id"]
    st1, e1 = c.api("POST", f"/api/reservations/{rid}/entry", "student1")
    s1 = c.slot_state(sid)
    st2, e2 = c.api("POST", f"/api/reservations/{rid}/exit", "student1", {"simulate_minutes": 90})
    s2 = c.slot_state(sid)
    st3, e3 = c.api("POST", f"/api/reservations/{rid}/pay", "student1", {"method": "UPI", "upi_id": "aarav@okbank"})
    s3 = c.slot_state(sid)
    fee = e2["reservation"]["fee"]
    ok((st1, st2, st3) == (200, 200, 200) and (s1, s2, s3) == ("occupied", "payment_due", "free") and fee == 10.0
       and e3["reservation"]["status"] == "completed", f"{s1},{s2},{s3},{fee}")
    return f"entry->{s1}; exit (90 min) fee=₹{fee} ->{s2}; paid -> {e3['reservation']['status']}, slot {s3}"


@case("TC-13", "Fee boundaries: 60 vs 61 minutes, overstay", "Boundary", "60 min = 1 h; 61 min = 2 h; 30 min overstay adds 50% of one hour")
def _(c):
    a = compute_fee(0, 3600, 7200, 10)
    b = compute_fee(0, 3660, 7200, 10)
    o = compute_fee(0, 3600 * 2 + 1800, 7200, 10)
    ok(a["total"] == 10 and b["total"] == 20 and o["total"] == 35, f"{a['total']},{b['total']},{o['total']}")
    return f"60 min -> ₹{a['total']}; 61 min -> ₹{b['total']}; 2h30 on 2h booking -> ₹{o['total']} (incl. penalty ₹{o['overstay_penalty']})"


@case("TC-14", "Payment failure keeps slot on hold; retry succeeds", "Negative", "HTTP 402, status stays awaiting_payment, slot 'payment_due'; retry -> 200 and slot free")
def _(c):
    sid = c.slots()[0]
    _, d = c.reserve("student1", sid)
    rid = d["reservation"]["id"]
    c.api("POST", f"/api/reservations/{rid}/entry", "student1")
    c.api("POST", f"/api/reservations/{rid}/exit", "student1", {"simulate_minutes": 10})
    f, fe = c.api("POST", f"/api/reservations/{rid}/pay", "student1", {"method": "CARD", "card_number": "4000 0000 0000 0002"})
    held = c.slot_state(sid)
    r, _ = c.api("POST", f"/api/reservations/{rid}/pay", "student1", {"method": "CARD", "card_number": "4242424242424242"})
    dup, _ = c.api("POST", f"/api/reservations/{rid}/pay", "student1", {"method": "UPI", "upi_id": "a@b"})
    ok(f == 402 and held == "payment_due" and r == 200 and c.slot_state(sid) == "free" and dup == 409, f"{f},{held},{r},{dup}")
    return f"declined -> HTTP {f}, slot={held}; retry -> {r}, slot=free; duplicate payment -> {dup}"


@case("TC-15", "Sensor mismatch: unreserved vehicle in a free slot", "Negative", "Slot becomes 'mismatch', admin alert raised, slot cannot be reserved")
def _(c):
    sid = c.slots()[0]
    st, d = c.api("POST", "/api/admin/sensors", "admin", {"slot_id": sid, "state": "occupied"})
    _, al = c.api("GET", "/api/admin/sensor-alerts", "admin")
    res, _ = c.reserve("student1", sid)
    ok(d["result"]["outcome"] == "mismatch" and c.slot_state(sid) == "mismatch" and len(al["alerts"]) == 1 and res == 409,
       d["result"]["outcome"])
    return f"outcome={d['result']['outcome']}, alerts={len(al['alerts'])}, student reserve -> HTTP {res}"


@case("TC-16", "Student arrives but reserved slot is physically taken", "Negative", "Entry -> HTTP 409 'sensor_mismatch' and attendant alert recorded")
def _(c):
    sid = c.slots()[0]
    # booking starts in 20 min; a stranger parks there now (sensor flags mismatch); 10 min later the student arrives
    _, d = c.reserve("student1", sid, start_ts=time.time() + 20 * 60)
    c.api("POST", "/api/admin/sensors", "admin", {"slot_id": sid, "state": "occupied"})
    c.app.config["TIME_OFFSET"] = 10 * 60
    st, e = c.api("POST", f"/api/reservations/{d['reservation']['id']}/entry", "student1")
    _, al = c.api("GET", "/api/admin/sensor-alerts", "admin")
    ok(st == 409 and e["error"]["code"] == "sensor_mismatch" and al["alerts"], f"{st}")
    return f"HTTP {st}: {e['error']['message']} | alerts logged: {len(al['alerts'])}"


# ------------------------------------------------------------------ transport
@case("TC-17", "Admin changes route timing -> student sees update & alert", "Positive", "Route R1 shows new timing; broadcast notification visible to student")
def _(c):
    st, d = c.api("PUT", "/api/admin/routes/1", "admin", {"first_departure": "08:00", "frequency_min": 10, "note": "Exam week schedule"})
    _, v = c.route_view("student1", 1)
    _, n = c.api("GET", "/api/notifications", "student1")
    msg = n["items"][0]["message"]
    ok(st == 200 and v["route"]["first_departure"] == "08:00" and v["route"]["frequency_min"] == 10 and "R1" in msg and n["unread"] >= 1, msg)
    return f"HTTP {st}; student sees {v['route']['first_departure']} every {v['route']['frequency_min']} min; alert: \"{msg}\""


@case("TC-18", "Invalid route / invalid timing input", "Negative", "Unknown route -> 404; last<first -> 400; frequency 2 min -> 400; 1 stop -> 400")
def _(c):
    a, _ = c.api("PUT", "/api/admin/routes/99", "admin", {"frequency_min": 10})
    b, _ = c.api("PUT", "/api/admin/routes/1", "admin", {"first_departure": "18:00", "last_departure": "09:00"})
    d, _ = c.api("PUT", "/api/admin/routes/1", "admin", {"frequency_min": 2})
    e, _ = c.api("PUT", "/api/admin/routes/1", "admin", {"stops": [1]})
    f, _ = c.route_view("student1", "abc")
    ok((a, b, d, e, f) == (404, 400, 400, 400, 404), f"{a},{b},{d},{e},{f}")
    return f"route 99 -> {a}; last<first -> {b}; freq 2 -> {d}; 1 stop -> {e}; route 'abc' -> {f}"


@case("TC-19", "Missing & stale bus location", "Boundary", "Bus with no GPS = 'unavailable'; live bus silenced for 30 s = 'stale'; re-enabled = 'live'")
def _(c):
    _, b = c.api("GET", "/api/buses", "student1")
    fresh = {x["id"]: x["freshness"] for x in b["buses"]}
    ok(fresh[4] == "unavailable" and fresh[1] == "live", str(fresh))
    c.api("POST", "/api/admin/buses/1/gps", "admin", {"enabled": False})
    c.app.config["TIME_OFFSET"] = 30
    _, b2 = c.api("GET", "/api/buses", "student1")
    stale = next(x for x in b2["buses"] if x["id"] == 1)["freshness"]
    c.api("POST", "/api/admin/buses/1/gps", "admin", {"enabled": True})
    _, b3 = c.api("GET", "/api/buses", "student1")
    back = next(x for x in b3["buses"] if x["id"] == 1)["freshness"]
    ok(stale == "stale" and back == "live", f"{stale},{back}")
    return f"bus 4 (never reported) = {fresh[4]}; bus 1 after 30 s silence = {stale}; after re-enable = {back}"


@case("TC-20", "Suspended route -> buses out of service + alert", "Positive", "Route suspended; its buses report 'out_of_service'; students receive notification")
def _(c):
    st, _ = c.api("PUT", "/api/admin/routes/2", "admin", {"status": "suspended"})
    _, b = c.api("GET", "/api/buses", "student1")
    state = next(x for x in b["buses"] if x["route_id"] == 2)["freshness"]
    _, n = c.api("GET", "/api/notifications", "student1")
    ok(st == 200 and state == "out_of_service" and "SUSPENDED" in n["items"][0]["message"], state)
    return f"HTTP {st}; R2 bus = {state}; alert: \"{n['items'][0]['message']}\""


def run_all():
    results = []
    for k in CASES:
        c = Ctx()
        try:
            actual, passed = k["fn"](c), True
        except AssertionError as e:
            actual, passed = f"FAILED: {e}", False
        except Exception as e:  # pragma: no cover
            actual, passed = f"ERROR: {type(e).__name__}: {e}", False
        results.append({"id": k["id"], "name": k["name"], "type": k["type"], "expected": k["expected"],
                        "actual": actual, "passed": passed})
    n_ok = sum(r["passed"] for r in results)
    return {"total": len(results), "passed": n_ok, "failed": len(results) - n_ok, "results": results}


if __name__ == "__main__":
    out = run_all()
    for r in out["results"]:
        print(("PASS" if r["passed"] else "FAIL"), r["id"], f"[{r['type']}]", r["name"], "->", r["actual"])
    print(f"\n{out['passed']}/{out['total']} passed")
    raise SystemExit(0 if out["failed"] == 0 else 1)
