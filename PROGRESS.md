# SLAM — Smart Lecture Attendance Management System

Students tap an RFID card on a reader in the lecture hall. The device
decides on the spot whether to accept the tap, and syncs to a cloud
backend that institutions administer through a web dashboard.

---

## The decisions that shape everything

**Offline-first.** The device holds a local copy of every registered card
and the current lecture's roster. A tap resolves in under a millisecond
against memory, with no network involved. Records queue to flash and
upload in batches later. A dead campus network means attendance still
works.

This one decision drove the circular flash log, version-based sync, and
HTTP connection reuse. Everything else follows from it.

**Timetable enforcement.** A card only counts if a lecture is scheduled in
that venue now and the student is enrolled on that course. Five outcomes:
present, late, not enrolled, no lecture, unknown card. All are logged,
including cards nobody recognises — that log is how an administrator
discovers a new card needs registering.

**Multi-tenant.** Any institution can sign up and gets isolated data.
Nothing crosses between organisations, including the fact that something
exists: a direct request for another tenant's record returns 404, not 403.

**Cards separate from students.** A lost card is revoked and replaced
without touching attendance history.

**The device never registers a card.** It only reports that one was seen.
Binding a card to a student always happens in the dashboard, by an
authenticated admin. A stolen device cannot forge a student.

---

## Stack

| Layer | Technology |
|---|---|
| Device | ESP32, MFRC522 RFID reader, 1602 LCD over I2C |
| Firmware | ESP-IDF 6.0.1, FreeRTOS, five tasks across both cores |
| Backend | Django 6.1 + DRF, JWT auth, deployed on Render |
| Database | Neon (serverless Postgres), pooled connection |
| Frontend | React + Vite, deployed on Vercel |

Live: `https://slams-bez9.onrender.com` and `https://slams-chi.vercel.app`

---

## Done

### Firmware
- [x] ESP-IDF project, 5 FreeRTOS tasks pinned across both cores
- [x] MFRC522 driver over SPI, written from scratch (5.2 ms read)
- [x] 1602 LCD driver over I2C, batched writes (19 ms)
- [x] Local decision engine: directory, roster, present bitmap
- [x] Circular event log on a raw flash partition, survives reboot
- [x] WiFi manager: 5 saved networks, priority order, backoff, AP fallback
- [x] Config portal: scan, add/remove networks, backend URL, token, restart
- [x] HTTP client with connection reuse, heartbeat, versioned sync
- [x] Debounce: 2 s same-card, 60 s unknown-card, duplicate suppression

### Backend
- [x] Multi-tenant models with per-org unique constraints
- [x] Registration, JWT login, roles (owner / admin / lecturer / viewer)
- [x] Tenant isolation verified — 8 Postman tests passing
- [x] Device API: token auth, 5 endpoints, binary directory packing
- [x] Idempotent uploads via client id + unique constraint
- [x] Audit log on every card binding
- [x] Deployed to Render with Neon, whitenoise, CORS

### Frontend
- [x] Landing page, login, auth context with token refresh
- [x] Dashboard shell: sidebar, org switcher, role-aware nav
- [x] Overview page with live counts
- [x] New cards worklist — bind a seen UID to a student

---

## Open bug

**Uploads never fire.** Records queue correctly (depth climbs, survives
reboot) but no `POST /api/device/attendance/` reaches the server.
Diagnostic logging was added to `slam_api_upload` and the net task but
has not been run yet. This is the next thing to settle.

---

## Unresolved — separate from the feature list

Reading back over the project, here's what I'd flag as genuinely unresolved — separate from the feature list below, which is just work remaining.

### Things that could invalidate the design

**The upload bug is unexplained.** We know records queue and never send. We don't know why. It could be trivial (a peek returning nothing) or structural (the circular log's tail pointer being wrong after init). Until it's diagnosed, the offline-first claim is unproven — the device stores correctly but has never demonstrated it can drain.

**The 7-byte UID path has never executed.** Every card tapped so far is 4-byte MIFARE Classic. The cascade logic in the driver is written but unrun. If the institution issues NTAG or Ultralight cards, that code is the first thing that will break, and it would surface during deployment rather than now.

**No load test.** One student tapping slowly is not a lecture hall. Twenty students in thirty seconds exercises the UI queue, the store queue, the upload batching and the LCD interrupt logic simultaneously — none of which have been tested under pressure.

**A full offline lecture has never been simulated.** Disconnect the device, take a hundred taps, reconnect, verify every record arrives exactly once. That's the scenario the whole architecture exists for, and it's untested.

### Things decided but never revisited

**The clock problem.** The plan was to derive time from the last sync plus uptime, with a confidence flag. Never settled: whether flagged-but-unverified records are acceptable to the institution, or whether a lecturer needs to confirm them. That affects the dashboard design.

**Session ownership.** Both timetable-created and lecturer-opened sessions were meant to exist. Only the timetable half is built. The lecturer-card path — which handles reschedules, the most common real-world case — doesn't exist.

**Enrolment mode.** Two mechanisms were designed (admin card, server flag). Neither is implemented. The dashboard side now exists, so this is unblocked.

### Things that went wrong along the way

Worth naming, since they're the kind of error that recurs:

- 400 kHz was assumed for the I2C display; the PCF8574 is rated for 100 kHz. Corrected, but should have been checked first.
- LittleFS was used for the event queue — wrong tool. A filesystem commits metadata on every close, and flash warnings showed up within minutes.
- Sample data was invented (`ADEYEMI H.`) without clearly flagging it as fake, and it was reasonable to assume it came from somewhere real.
- Several code blocks silently failed to apply, costing time debugging symptoms rather than checking whether the file had been written. `check-files.ps1` exists now; it should be extended as new files are added.

### The one thing to do before anything else

Not the upload bug — the **offline lecture test**. It exercises the queue, the drain, the timestamps and the deduplication in one go, and it's the scenario that decides whether this system is trustworthy. The upload bug will surface during it anyway.

---

## Remaining

### Firmware
- [ ] Fix the upload bug
- [ ] Enrolment mode: admin card and server-initiated flag
- [ ] OTA firmware updates
- [ ] Untested: 7-byte UID cards (cascade path never executed)
- [ ] Untested: several students in quick succession
- [ ] Untested: a full offline lecture followed by reconnect

### Backend
- [ ] Lecturer opens/closes a session by card
- [ ] CSV and PDF export
- [ ] Attendance summary table (avoid recomputing percentages per request)

### Frontend
- [ ] Students, cards, courses, enrolment
- [ ] Timetable and venues
- [ ] Device management, token reveal
- [ ] Live lecture view (polls with a `since` cursor)
- [ ] Attendance reports
- [ ] Team management, invitations

### Before real deployment
- [ ] Admin password on the device config portal
- [ ] Anti-fraud: lecturer-triggered mid-lecture re-tap
- [ ] Tighten `CORS_ALLOWED_ORIGINS` and `ALLOWED_HOSTS`
- [ ] Paid tier if cold starts matter (free Render + Neon both sleep)

---

## Known weak points

**No real-time clock.** The hardware cannot be changed, so the device
derives time from the last server sync plus uptime. After a reboot with
no network it flags its records as unverified rather than pretending to
know the time. This works, but it is the softest part of the design.

**Card cloning.** Common MIFARE cards can be copied with cheap equipment.
The planned mid-lecture re-tap is the practical defence. Cards with a
secret key (DESFire) would close it properly at a higher cost per card.

**Config portal has no password of its own.** Anyone who can join the
device's access point can change the backend address and token. The
per-device AP password is a reasonable boundary for a lecture hall, but
this should be tightened before deployment.

---

## Gotchas worth remembering

- **ESP-IDF 6.0** split the `driver` component. GPIO is now
  `esp_driver_gpio`, SPI is `esp_driver_spi`, and so on. cJSON and
  `wifi_provisioning` moved out to managed components.
- **The old Arduino firmware mangled UIDs**: `String(byte, HEX)` drops
  leading zeros, so `0A3F05B2` became `A3F5B2`. UIDs are now stored as
  raw bytes and only converted to hex for display and JSON.
- **LittleFS is wrong for an append-only log.** Writing one record per
  tap caused superblock warnings within minutes. The event queue lives on
  a raw partition with tag-based slots instead.
- **Spaces in environment variables.** `ALLOWED_HOSTS=a, b` produced a
  host with a leading space that could never match. Both host and CORS
  lists now strip each entry.
- **CORS preflight caching.** `Access-Control-Max-Age` is 24 hours by
  default, so a failed preflight sticks around long after the server is
  fixed. Test in a private window.

---

## Running locally

Three terminals:

| Folder | Command |
|---|---|
| `C:\CodeSet\idf_folder\slam` (separate location, not in this repo) | `idf.py build` then `idf.py -p COM? flash monitor` |
| `slams/backend` | `python manage.py runserver 0.0.0.0:8000` |
| `slams/frontend` | `npm run dev` |

The backend needs `slenv` active. Seed demo data with
`python manage.py seed_demo --uid <your card UID>`, which prints a device
token to paste into the config portal.
