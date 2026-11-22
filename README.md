# CampusMove v5 – IoT-Based Campus Parking & Smart Transport Locator

Agile Software Development – Final Jury prototype · Problem Statement 5
(covers the core workflows of *18 – Smart Parking* and *12 – Campus Transportation*)

A web app where students see **live parking availability** and **college-bus locations**, reserve a slot, pay the fee and receive route-change alerts; an admin operates sensors, routes and alerts.

> **Simulation notice (label this in the jury – do not claim live integrations):**
> parking sensors, bus GPS, payment gateway and push notifications are **simulated** in software and labelled as such in the UI. No real hardware, bank, UPI or map API is used. All users, vehicles and money are fictitious.

## Run it (2 minutes)

```bash
pip install -r requirements.txt        # only Flask
python run.py                          # -> http://127.0.0.1:5004
```
Demo logins (username is not case-sensitive): `Shreya Kanade / shreya123`, `Abhijit More / abhijit123`, `admin / admin123` (or use the buttons on the login page).

> This is **v5** and runs on port **5004**, so it can run side by side with the first project (port 5000) and v2/v3/v4 (ports 5001/5002/5003).
Admin → **Reset demo data** restores a clean state before the jury. Open two browsers (student + admin) to show live updates.

Tests: `python -m campus.selftests` (prints expected vs actual) or `python -m unittest discover tests -v`, or **Admin → Test Cases → Run all tests** in the browser.

## Features vs. jury requirements

| Requirement | Where |
|---|---|
| Parking area/slot availability | Live Map + Parking page (per-lot counts, 6 slot states) |
| Slot reservation and time | Arrival now/later (≤24 h) + 1–8 h duration, conflict-safe |
| Entry/exit status (simulated sensor) | "Arrive at slot" / "Leave slot" buttons + Admin sensor simulator |
| Fee calculation + payment simulation | Hourly rate, part-hours round up, overstay penalty; simulated UPI/Card/Wallet gateway with forced-failure switch |
| Availability update after cancel/exit | Slot returns to *free* after cancel or **successful** payment |
| Competing reservations, sensor mismatch, payment failure | TC-06, TC-14, TC-15, TC-16 |
| Bus routes, stops, schedules | Buses page (stops, first/last, frequency, next departures) |
| Bus location (labelled simulated coordinates) | Map + bus list with lat/lon, speed, next stop and ETA |
| Admin route/timing update + student alert | Admin → Route editor → students get an in-app alert within 3 s |
| Invalid route, missing or stale location | TC-18, TC-19 ("No location", "Stale" after 20 s without ping) |
| Role-based access, validation, error messages | Student/Admin roles (403/401), field-level 400 errors |
| Persistent storage | SQLite (`campus.db`), created automatically |

## Suggested 7-minute live demo

1. **Shreya** → Live Map: free slots, buses moving (simulated GPS). Bus MH12 AB 3001 (R3) shows *No location*.
2. Parking → pick slot → enter `ABC` → validation error → `MH12AB1234` → **reserve**.
3. **Abhijit** (second browser) → try the same slot → *competing reservation* rejected (409).
4. Shreya → *Arrive at slot* → *Leave slot* with `61` fast-forward minutes → fee ₹20 (+ penalty) → tick **Force payment failure** → declined, slot stays *Payment due* → untick → paid → slot *free*.
5. **Admin** → Sensor simulator: report *OCCUPIED* on a free slot → mismatch alert appears → Resolve.
6. Admin → Route editor: change R1 frequency/stops → **Student sees alert + new timing** instantly.
7. Admin → *Cut GPS* on bus R1, wait 20 s → student sees **Stale**. Admin → **Test Cases → Run all** (20/20).

## Architecture

```
Browser (vanilla JS SPA, SVG map, polls every 3 s)
        │  JSON / REST  (Bearer token)
Flask app  ── auth.py        login, register, roles, notifications
           ── parking.py     availability, reservations, sensor logic, fee, payment
           ── transport.py   routes, stops, schedules, simulated GPS, admin updates, alerts
           ── admin.py       KPIs, sensor simulator, mismatch alerts, maintenance, test runner
           ── selftests.py   20 executable test cases (expected vs actual)
SQLite (db.py schema + fictitious seed data)
```
Key design decisions (good viva answers):
* **Slot state is derived**, not stored: `free / reserved / occupied / payment_due / mismatch / maintenance` is computed from the sensor flag + reservations, so the UI and API can never disagree.
* **No double booking**: writes run in `BEGIN IMMEDIATE` transactions with an overlap check, and a DB unique index allows one active reservation per user.
* **Simulated GPS**: buses advance along their route polyline according to elapsed time; "stale" = no ping for 20 s, "unavailable" = never pinged. Coordinates are map units converted to approximate lat/lon.
* **Time control for tests/demo**: `TIME_OFFSET` shifts the server clock in tests; `simulate_minutes` on exit is a labelled demo shortcut.

## Fee rules
`billed hours = max(1, ceil(parked minutes / 60))` × hourly rate (A ₹10, B ₹10, C ₹5, D ₹8 per hour) + overstay penalty of 50 % of the hourly rate for every started hour beyond the booked end. Slot is released only after successful payment.

## Contribution split (edit to match your team)
| Member | Module(s) |
|---|---|
| Member 1 | `parking.py` – availability, reservation, conflict handling |
| Member 2 | sensor simulation, fee & payment (`parking.py`), `selftests.py` |
| Member 3 | `transport.py` – routes, schedules, simulated GPS, alerts |
| Member 4 | `static/` UI, `auth.py`, `admin.py`, documentation |

See `docs/AGILE_ARTEFACTS.md` (backlog, user stories, sprint plan, DoD, risks) and `docs/TEST_REPORT.md`.

## v2 changes
* Wider responsive layout (3-column live map page, lots shown as cards side by side).
* Car icon on every slot that holds a vehicle (map and parking page).
* Two basement parking areas, **B1** and **B2** (15 slots each, `B1-1`…`B2-15`, ₹15/h) near School of Computing. Lot A now belongs to MANET. Every surface lot has 18 slots (102 slots in total). The Tuck Shop lot is now *Lot T* so slot names never clash with B1/B2.
* Users: Shreya Kanade, Abhijit More, admin.
* Campus data: 13 real stop names, lots near School of Computing, Tuck Shop, World Peace Dome and Sports Complex, 4 proposed bus routes 07:30–20:00 (route design is a prototype proposal, not the official timetable).
* **Dark theme** across the whole app (login, map, parking, buses, admin).
* **Illustrated login background** (campus buildings, shuttle bus, parked cars, GPS pin, IoT signals) – an original offline SVG, `static/login-bg.svg`.
