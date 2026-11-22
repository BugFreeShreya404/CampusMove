# Agile Artefacts – CampusMove (Problem Statement 5)

> **Draft to adapt.** These artefacts describe the work as structured in this codebase. Before the jury, copy them into your **Jira/Trello board**, add real sprint dates, assignees, screenshots, burndown/velocity from your board, and make sure your **GitHub commit history** reflects who built what. Only claim Agile practices your team actually followed; list the rest as "proposed improvements".

## 1. Product vision & users
For **students and staff** who waste time hunting for parking and waiting for buses, **CampusMove** shows real-time (sensor/GPS-based) parking availability and bus locations. Unlike notice boards or phone calls, it updates live and alerts on changes. *Sensors/GPS are simulated in this prototype.*

Users: Student/Staff (reserve, track, pay), Campus Admin / Transport Coordinator (operate sensors, routes, alerts).

## 2. Prioritised Product Backlog (MoSCoW + story points)

| ID | User story | Priority | SP | Sprint |
|---|---|---|---|---|
| US-01 | As a user I can log in with a role so that I only see what I am allowed to | Must | 3 | 1 |
| US-02 | As a student I can see live free/occupied slots per lot | Must | 5 | 1 |
| US-03 | As a student I can reserve a slot for a time window | Must | 8 | 1 |
| US-04 | As a student I can see bus routes, stops and schedules | Must | 3 | 1 |
| US-05 | As a student I can see bus location on a map | Must | 5 | 2 |
| US-06 | As a student I can cancel a reservation and the slot is freed | Must | 2 | 2 |
| US-07 | As a student I get entry/exit recognised by the (simulated) sensor | Must | 5 | 2 |
| US-08 | As a student I see my fee and pay (simulated) to release the slot | Must | 5 | 2 |
| US-09 | As an admin I can change route timing/stops and students are alerted | Must | 5 | 3 |
| US-10 | As an admin I see sensor mismatches and can resolve them | Should | 5 | 3 |
| US-11 | As a student I see "stale / no location" instead of wrong bus positions | Should | 3 | 3 |
| US-12 | As an admin I see KPIs (occupancy, revenue, bus health) | Should | 3 | 3 |
| US-13 | As an admin I can broadcast a delay alert | Could | 2 | 3 |
| US-14 | As a student I can register an account | Could | 2 | 3 |
| US-15 | Real sensors (ESP32/ultrasonic) over MQTT | Won't (this release) | – | Future |
| US-16 | Real GPS trackers + live map tiles | Won't (this release) | – | Future |

## 3. User stories with acceptance criteria (core ones)

**US-03 Reserve a slot**
* Given a free slot and a valid vehicle number (e.g. MH12AB1234), when I confirm, then a reservation is created and the slot shows *Reserved*.
* Duration must be 1–8 h; start time cannot be in the past or >24 h ahead.
* If another student has the slot for an overlapping time, I get a clear "slot not available" message and nothing is saved.
* I can hold only one active reservation at a time.

**US-07/08 Entry, exit, fee, payment**
* Entry is accepted from 15 min before start until the booking ends; earlier → "Too early" message.
* On exit, fee = billed hours × rate (min 1 h, part-hours rounded up) + 50 % overstay penalty per late hour.
* A failed payment keeps the slot on hold and allows retry; a duplicate payment is blocked; success releases the slot.

**US-09 Admin route update**
* Times must be HH:MM, last > first, frequency 5–60 min, ≥2 unique stops, route must exist.
* After saving, students see the new timing and an alert within one refresh cycle (3 s).

**US-11 Missing/stale location**
* A bus that never reported shows "No location"; one silent for >20 s shows "Stale" with the age; suspended routes show "Out of service".

## 4. Sprint plan (3 sprints × 1 week – adjust to your real dates)

| Sprint | Goal | Backlog items | Demo-able increment |
|---|---|---|---|
| 1 | Walking skeleton: login, parking availability, reservation, route list | US-01–04 | Student can log in, see slots/routes, reserve |
| 2 | Parking life-cycle + live buses | US-05–08 | Reserve → entry → exit → fee → pay → slot freed; bus map |
| 3 | Admin, alerts, hardening, tests | US-09–14 | Route change alerts, sensor mismatch, 20 test cases |

**Sprint 3 backlog tasks (example task allocation):** route editor API (Member 3), notification polling + toasts (Member 4), mismatch alerts (Member 2), test suite (Member 2), UI polish (Member 4), documentation (all).

## 5. Definition of Done
- [ ] Code merged to `main` via pull request with at least one review
- [ ] Acceptance criteria demonstrated on the running app
- [ ] Input validation + meaningful error messages for the story
- [ ] At least one positive and one negative automated test; whole suite green (`python -m campus.selftests`)
- [ ] Simulated components clearly labelled in the UI
- [ ] No hard-coded secrets; fictitious data only
- [ ] Board card moved to Done; README/docs updated

## 6. Risk & impediment register

| # | Risk / impediment | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | No real sensors/GPS hardware available | High | Med | Software simulators, clearly labelled; abstraction so MQTT/GPS can replace them later |
| R2 | Two users booking the same slot concurrently | Med | High | Transactional overlap check + DB unique index; test TC-06 |
| R3 | Live demo fails (network/environment) | Med | High | Runs fully local with SQLite, no internet needed; *Reset demo data* button |
| R4 | Stale bus positions mislead students | Med | Med | Freshness states (live/stale/no location) with ages |
| R5 | Scope creep (payments, maps, real IoT) | Med | Med | MoSCoW; "Won't" items in backlog |

## 7. Defect record (real entries from this build)

| ID | Found in | Description | Root cause | Fix | Status |
|---|---|---|---|---|---|
| D-01 | TC-16 (first run) | Test "student arrives but slot is occupied" failed: entry succeeded | Test injected the sensor reading while the student's reservation was already active, so the system correctly treated it as *their* arrival | Re-designed the scenario: stranger parks before the booking window, student arrives later → entry blocked + alert | Closed |
| D-02 | Manual UI review | R2 bus icon and route line overlapped Lot B on the map | Lot drawn on top of the route line | Moved Lot B coordinates in seed data | Closed |

Add your own defects found during team testing.

## 8. Agile ceremonies & practices (fill in honestly)
Sprint planning, daily stand-up (15 min), sprint review (demo), retrospective; board columns *Backlog → To Do → In Progress → In Review → Done*. Velocity: record story points completed per sprint from your board (e.g. S1 = 21, S2 = 22, S3 = 20 – **replace with your real numbers**).
