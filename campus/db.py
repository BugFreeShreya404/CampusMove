"""SQLite schema + sample (fictitious) seed data."""
import sqlite3
import time

from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','admin')),
  notif_seen_id INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_ts REAL NOT NULL);
CREATE TABLE lots(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, rate_per_hour REAL NOT NULL,
  x REAL, y REAL, w REAL, h REAL, cols INTEGER, kind TEXT NOT NULL DEFAULT 'surface');
CREATE TABLE slots(
  id INTEGER PRIMARY KEY, lot_id INTEGER NOT NULL REFERENCES lots(id), label TEXT NOT NULL,
  sensor TEXT NOT NULL DEFAULT 'free' CHECK(sensor IN ('free','occupied')),
  maintenance INTEGER NOT NULL DEFAULT 0, UNIQUE(lot_id,label));
CREATE TABLE reservations(
  id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES slots(id),
  user_id INTEGER REFERENCES users(id), vehicle_no TEXT NOT NULL,
  start_ts REAL NOT NULL, end_ts REAL NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('reserved','parked','awaiting_payment','completed','cancelled','expired')),
  source TEXT NOT NULL DEFAULT 'app', created_ts REAL NOT NULL,
  entry_ts REAL, exit_ts REAL, fee REAL, fee_json TEXT);
-- DB-level guarantee: a user can hold only one active reservation at a time
CREATE UNIQUE INDEX one_active_per_user ON reservations(user_id)
  WHERE status IN ('reserved','parked','awaiting_payment') AND user_id IS NOT NULL;
CREATE TABLE payments(
  id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL REFERENCES reservations(id),
  amount REAL NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('success','failed')),
  reason TEXT, created_ts REAL NOT NULL);
CREATE TABLE sensor_alerts(
  id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES slots(id), kind TEXT NOT NULL,
  detail TEXT NOT NULL, created_ts REAL NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE stops(id INTEGER PRIMARY KEY, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL);
CREATE TABLE routes(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, color TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
  first_departure TEXT NOT NULL, last_departure TEXT NOT NULL, frequency_min INTEGER NOT NULL, note TEXT);
CREATE TABLE route_stops(
  route_id INTEGER NOT NULL REFERENCES routes(id), seq INTEGER NOT NULL, stop_id INTEGER NOT NULL REFERENCES stops(id),
  PRIMARY KEY(route_id, seq));
CREATE TABLE buses(
  id INTEGER PRIMARY KEY, plate TEXT NOT NULL, route_id INTEGER NOT NULL REFERENCES routes(id),
  distance REAL NOT NULL DEFAULT 0, x REAL, y REAL, speed_mps REAL NOT NULL DEFAULT 8,
  gps_enabled INTEGER NOT NULL DEFAULT 1, last_update_ts REAL);
CREATE TABLE notifications(
  id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
  audience TEXT NOT NULL DEFAULT 'all', kind TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL, created_ts REAL NOT NULL);
"""

DEMO_USERS = [  # usernames are stored lowercase; login is case-insensitive ("Shreya Kanade" works)
    ("shreya kanade", "shreya123", "Shreya Kanade", "student"),
    ("abhijit more", "abhijit123", "Abhijit More", "student"),
    ("admin", "admin123", "Campus Admin", "admin"),
]

# name, x, y  (schematic map is a 1000 x 620 canvas; positions are approximate, not surveyed)
STOPS = [
    ("Main Gate", 70, 300), ("MANET", 170, 120), ("School of Computing", 650, 120),
    ("Institute of Design", 400, 120), ("ISBJ", 880, 120), ("Tuck Shop", 340, 300),
    ("Sports Complex", 230, 470), ("UTK", 580, 300), ("World Peace Dome", 700, 470),
    ("Hostel A", 880, 260), ("Hostel B", 900, 380), ("Sangeetkala", 470, 640), ("Raj Mess", 880, 640),
]
# code, name, color, stop ids (1-based, in STOPS order), first, last, frequency (min)
# NOTE: these 4 routes are a proposed design for the prototype, not the official timetable.
ROUTES = [
    ("R1", "Academic Loop", "#0b84a5", [1, 2, 4, 3, 5, 8, 6], "07:30", "20:00", 15),
    ("R2", "Hostel Express", "#e07a1f", [1, 6, 8, 10, 11, 13, 12, 7], "07:30", "20:00", 20),
    ("R3", "Sports & Arts Shuttle", "#7b4fc4", [6, 7, 12, 9], "07:30", "20:00", 20),
    ("R4", "North-East Connector", "#d6336c", [4, 3, 5, 10, 9, 8], "07:30", "20:00", 30),
]
# plate, route id, start distance (m along route), speed (m/s), gps_enabled
BUSES = [
    ("MH12 AB 1001", 1, 0, 8, 1), ("MH12 AB 1002", 1, 900, 8, 1),
    ("MH12 AB 2001", 2, 300, 9, 1), ("MH12 AB 3001", 3, 0, 8, 0),  # R3 bus: no GPS yet -> "unavailable"
    ("MH12 AB 2002", 2, 1700, 9, 1), ("MH12 AB 4001", 4, 0, 8, 1),
]
# code, name, rate/hour, x, y, w, h, cols, n_slots, kind
LOTS = [
    ("A", "Lot A \u2013 MANET", 10, 53, 16, 234, 78, 6, 18, "surface"),
    ("T", "Lot T \u2013 Tuck Shop", 10, 225, 188, 234, 78, 6, 18, "surface"),
    ("C", "Lot C \u2013 World Peace Dome", 5, 640, 510, 234, 78, 6, 18, "surface"),
    ("D", "Lot D \u2013 Sports Complex", 8, 45, 525, 234, 78, 6, 18, "surface"),
    ("B1", "Basement B1 \u2013 School of Computing", 15, 540, 16, 190, 78, 5, 15, "basement"),
    ("B2", "Basement B2 \u2013 School of Computing", 15, 745, 16, 190, 78, 5, 15, "basement"),
]
WALKINS = ["A2", "A5", "A9", "A14", "T3", "T8", "T12", "T16", "C1", "C6", "C11", "C17", "D4", "D10", "D15",
            "B1-2", "B1-7", "B1-12", "B2-5", "B2-9"]  # slot labels that already hold a walk-in vehicle


def connect(path):
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path, seed=True):
    conn = connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    reset(conn, seed)
    conn.close()


def reset(conn, seed=True):
    conn.execute("PRAGMA foreign_keys=OFF")
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    if seed:
        seed_data(conn)


def seed_data(c):
    t = time.time()
    c.execute("BEGIN")
    for u, p, n, r in DEMO_USERS:
        c.execute("INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,?)",
                  (u, generate_password_hash(p), n, r))
    lot_ids = {}
    for code, name, rate, x, y, w, h, cols, n, kind in LOTS:
        cur = c.execute("INSERT INTO lots(code,name,rate_per_hour,x,y,w,h,cols,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                        (code, name, rate, x, y, w, h, cols, kind))
        lot_ids[code] = cur.lastrowid
        sep = "-" if kind == "basement" else ""   # basement slots are B1-1, B1-2 ... (no clash with other lots)
        for i in range(1, n + 1):
            c.execute("INSERT INTO slots(lot_id,label) VALUES(?,?)", (lot_ids[code], f"{code}{sep}{i}"))
    # one slot under maintenance
    c.execute("UPDATE slots SET maintenance=1 WHERE label='A8'")
    # walk-in vehicles already parked (sensor = occupied, no app reservation)
    for i, label in enumerate(WALKINS):
        sid = c.execute("SELECT id FROM slots WHERE label=?", (label,)).fetchone()[0]
        c.execute("UPDATE slots SET sensor='occupied' WHERE id=?", (sid,))
        c.execute("""INSERT INTO reservations(slot_id,user_id,vehicle_no,start_ts,end_ts,status,source,created_ts,entry_ts)
                     VALUES(?,?,?,?,?,'parked','walkin',?,?)""",
                  (sid, None, f"MH14WK{1000 + i}", t - 1800, t + 7200, t - 1800, t - 1800))
    for name, x, y in STOPS:
        c.execute("INSERT INTO stops(name,x,y) VALUES(?,?,?)", (name, x, y))
    for code, name, color, stops, first, last, freq in ROUTES:
        cur = c.execute("INSERT INTO routes(code,name,color,first_departure,last_departure,frequency_min) VALUES(?,?,?,?,?,?)",
                        (code, name, color, first, last, freq))
        for seq, sid in enumerate(stops):
            c.execute("INSERT INTO route_stops VALUES(?,?,?)", (cur.lastrowid, seq, sid))
    for plate, rid, dist, spd, gps in BUSES:
        c.execute("INSERT INTO buses(plate,route_id,distance,speed_mps,gps_enabled,last_update_ts) VALUES(?,?,?,?,?,?)",
                  (plate, rid, dist, spd, gps, t if gps else None))
    c.execute("INSERT INTO notifications(audience,kind,message,created_ts) VALUES('all','info',?,?)",
              ("Welcome! Sensor, GPS, payment and push alerts in this prototype are SIMULATED.", t))
    c.execute("COMMIT")
