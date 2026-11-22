# Test Report – CampusMove v5

Executed with `python -m campus.selftests` – **20/20 passed** (each case runs on a fresh temporary database).

| ID | Test case | Type | Expected | Actual | Result |
|---|---|---|---|---|---|
| TC-01 | Valid student login | Positive | HTTP 200, token issued, role = student | HTTP 200, role=student, token issued | PASS |
| TC-02 | Login with wrong password | Negative | HTTP 401 'Invalid username or password.' | HTTP 401: Invalid username or password. | PASS |
| TC-03 | Student calls admin API / anonymous call | Negative | Student -> 403 Forbidden; no token -> 401 | student -> HTTP 403; anonymous -> HTTP 401 | PASS |
| TC-04 | Availability totals add up | Positive | Per-lot counts sum to the 102 seeded slots (incl. 30 basement slots); 1 maintenance, 20 walk-in | total=102, totals={'free': 81, 'maintenance': 1, 'mismatch': 0, 'occupied': 20, 'payment_due': 0, 'reserved': 0} | PASS |
| TC-05 | Reserve a free slot (valid input) | Positive | HTTP 201, reservation 'reserved', slot turns 'reserved' | HTTP 201, status=reserved, slot state=reserved | PASS |
| TC-06 | Competing reservations for the same slot | Negative | 2nd student gets HTTP 409 'slot_conflict'; first booking untouched | student1 -> HTTP 201; student2 -> HTTP 409 (slot_conflict) | PASS |
| TC-07 | Invalid vehicle number / missing field | Negative | HTTP 400 with field error; nothing saved | 'ABC' -> HTTP 400 (Vehicle number looks invalid. Expected format like MH12AB1234.); missing plate -> HTTP 400 | PASS |
| TC-08 | Duration boundary values (0, 1, 8, 9 hours) | Boundary | 0 and 9 rejected (400); 1 accepted; 8 accepted | 0h -> 400, 9h -> 400, 1h -> 201, 8h -> 201 | PASS |
| TC-09 | Second active reservation by same user | Negative | HTTP 409 'already_active' | HTTP 409: You already have an active reservation (#21). Cancel or complete it first. | PASS |
| TC-10 | Cancel reservation releases the slot | Positive | Cancel -> slot 'free' again and another student can book it | cancel -> 200, slot=free, rebook by student2 -> 201 | PASS |
| TC-11 | Entry too early (reservation 3 h ahead) | Boundary | HTTP 409 'too_early' (entry opens 15 min before start) | HTTP 409: Too early: entry opens at 03:16. | PASS |
| TC-12 | Full flow: entry -> exit -> fee -> pay -> slot released | Positive | parked -> awaiting_payment (fee shown) -> completed; slot free again | entry->occupied; exit (90 min) fee=₹10.0 ->payment_due; paid -> completed, slot free | PASS |
| TC-13 | Fee boundaries: 60 vs 61 minutes, overstay | Boundary | 60 min = 1 h; 61 min = 2 h; 30 min overstay adds 50% of one hour | 60 min -> ₹10.0; 61 min -> ₹20.0; 2h30 on 2h booking -> ₹35.0 (incl. penalty ₹5.0) | PASS |
| TC-14 | Payment failure keeps slot on hold; retry succeeds | Negative | HTTP 402, status stays awaiting_payment, slot 'payment_due'; retry -> 200 and slot free | declined -> HTTP 402, slot=payment_due; retry -> 200, slot=free; duplicate payment -> 409 | PASS |
| TC-15 | Sensor mismatch: unreserved vehicle in a free slot | Negative | Slot becomes 'mismatch', admin alert raised, slot cannot be reserved | outcome=mismatch, alerts=1, student reserve -> HTTP 409 | PASS |
| TC-16 | Student arrives but reserved slot is physically taken | Negative | Entry -> HTTP 409 'sensor_mismatch' and attendant alert recorded | HTTP 409: Slot A1 is physically occupied by another vehicle. A mismatch alert was sent to the parking attendant. \| alerts logged: 2 | PASS |
| TC-17 | Admin changes route timing -> student sees update & alert | Positive | Route R1 shows new timing; broadcast notification visible to student | HTTP 200; student sees 08:00 every 10 min; alert: "Route R1 (Academic Loop) updated – timings 07:30–20:00 → 08:00–20:00; frequency every 15 → 10 min; note: Exam week schedule." | PASS |
| TC-18 | Invalid route / invalid timing input | Negative | Unknown route -> 404; last<first -> 400; frequency 2 min -> 400; 1 stop -> 400 | route 99 -> 404; last<first -> 400; freq 2 -> 400; 1 stop -> 400; route 'abc' -> 404 | PASS |
| TC-19 | Missing & stale bus location | Boundary | Bus with no GPS = 'unavailable'; live bus silenced for 30 s = 'stale'; re-enabled = 'live' | bus 4 (never reported) = unavailable; bus 1 after 30 s silence = stale; after re-enable = live | PASS |
| TC-20 | Suspended route -> buses out of service + alert | Positive | Route suspended; its buses report 'out_of_service'; students receive notification | HTTP 200; R2 bus = out_of_service; alert: "Route R2 (Hostel Express) updated – service SUSPENDED." | PASS |
