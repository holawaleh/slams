import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHead, Loading, ErrorBox, Empty } from "../components/bits";
import Modal from "../components/Modal";
import "./Timetable.css";

// Must match TimetableSlotSerializer on the server.
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const FIRST_HOUR = 7;
const LAST_HOUR = 18;
const LANE_PX = 58;          // height of one row of lectures within a day
const STEP_MIN = 15;

const toMin = (t) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};
const toHHMM = (min) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;

// Every quarter hour in the teaching day, for the start/end pickers.
const TIMES = [];
for (let m = FIRST_HOUR * 60; m <= LAST_HOUR * 60; m += STEP_MIN) TIMES.push(toHHMM(m));

// A stable colour per course, so the same course reads the same all week.
function hue(code) {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

// Slots on one day that overlap (only possible across different venues)
// are laid out side by side in lanes instead of on top of each other.
function layDay(slots) {
  const sorted = [...slots].sort((a, b) => toMin(a.start_time) - toMin(b.start_time));
  const out = [];
  let group = [];
  let groupEnd = -1;
  const flush = () => {
    const lanes = [];
    for (const s of group) {
      let lane = lanes.findIndex((end) => end <= toMin(s.start_time));
      if (lane < 0) { lane = lanes.length; lanes.push(0); }
      lanes[lane] = toMin(s.end_time);
      out.push({ slot: s, lane, lanes: 0 });
    }
    for (const o of out.slice(out.length - group.length)) o.lanes = lanes.length;
    group = [];
  };
  for (const s of sorted) {
    if (group.length && toMin(s.start_time) >= groupEnd) flush();
    group.push(s);
    groupEnd = Math.max(groupEnd, toMin(s.end_time));
  }
  if (group.length) flush();
  return out;
}

function SlotForm({ slot, draft, courses, venues, onClose, onSaved }) {
  const editing = !!slot;
  const [form, setForm] = useState(() => ({
    course: slot?.course ?? "",
    venue: slot?.venue ?? draft?.venue ?? venues[0]?.id ?? "",
    weekday: slot?.weekday ?? draft?.weekday ?? 0,
    start_time: (slot?.start_time ?? draft?.start_time ?? "09:00").slice(0, 5),
    end_time: (slot?.end_time ?? draft?.end_time ?? "10:00").slice(0, 5),
    grace_minutes: slot?.grace_minutes ?? 15,
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  function setStart(e) {
    const start = e.target.value;
    // Keep the lecture's length when it is moved.
    const len = toMin(form.end_time) - toMin(form.start_time);
    const end = Math.min(toMin(start) + (len > 0 ? len : 60), LAST_HOUR * 60);
    setForm({ ...form, start_time: start, end_time: toHHMM(end) });
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...form, weekday: Number(form.weekday),
                   grace_minutes: Number(form.grace_minutes) };
    try {
      if (editing) await api.patch(`/api/slots/${slot.id}/`, body);
      else await api.post("/api/slots/", body);
      onSaved(editing ? "Lecture updated." : "Lecture added.");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Remove ${slot.course_code} on ${DAYS[slot.weekday]} from the timetable?`))
      return;
    setBusy(true);
    try {
      await api.delete(`/api/slots/${slot.id}/`);
      onSaved("Lecture removed.");
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={editing ? `Edit ${slot.course_code}` : "Add lecture"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="field">
          <label htmlFor="course">Course</label>
          <select id="course" className="input" required autoFocus={!editing}
                  value={form.course} onChange={set("course")}>
            <option value="" disabled>Choose a course</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.code} · {c.title}</option>
            ))}
          </select>
        </div>
        <div className="form-2">
          <div className="field">
            <label htmlFor="day">Day</label>
            <select id="day" className="input" value={form.weekday}
                    onChange={set("weekday")}>
              {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="venue">Venue</label>
            <select id="venue" className="input" required value={form.venue}
                    onChange={set("venue")}>
              {venues.map((v) => (
                <option key={v.id} value={v.id}>{v.code}{v.name && v.name !== v.code ? ` · ${v.name}` : ""}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="start">Starts</label>
            <select id="start" className="input" value={form.start_time} onChange={setStart}>
              {TIMES.slice(0, -1).map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="end">Ends</label>
            <select id="end" className="input" value={form.end_time} onChange={set("end_time")}>
              {TIMES.filter((t) => toMin(t) > toMin(form.start_time))
                    .map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="grace">Late after (minutes from start)</label>
          <input id="grace" className="input" type="number" min="0" max="120"
                 value={form.grace_minutes} onChange={set("grace_minutes")} />
          <small className="faint" style={{ display: "block", marginTop: 6 }}>
            Taps count only between the start and end time. After this many
            minutes they are marked late.
          </small>
        </div>
        <div className="spread">
          {editing ? (
            <button type="button" className="btn-danger" disabled={busy}
                    onClick={remove}>Remove</button>
          ) : <span />}
          <div className="row">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-solid" disabled={busy || !form.course}>
              {busy ? "Saving..." : editing ? "Save" : "Add lecture"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function VenuesDialog({ venues, onClose, onChanged }) {
  const [form, setForm] = useState({ code: "", name: "", capacity: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/venues/", {
        code: form.code, name: form.name || form.code,
        capacity: Number(form.capacity) || 0,
      });
      setForm({ code: "", name: "", capacity: "" });
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove(v) {
    if (!window.confirm(`Delete venue ${v.code}? Its timetable slots go with it.`)) return;
    setError(null);
    try {
      await api.delete(`/api/venues/${v.id}/`);
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Modal title="Venues" onClose={onClose} width={560}>
      <p className="muted" style={{ marginTop: 0 }}>
        Lecture halls and rooms. Each reader is placed in one venue, and takes
        attendance for whatever the timetable has there.
      </p>
      <ErrorBox error={error} />
      <form onSubmit={add} className="venue-add">
        <input className="input" placeholder="Code, e.g. LT1" required maxLength={16}
               value={form.code} onChange={set("code")} />
        <input className="input" placeholder="Name (optional)" maxLength={128}
               value={form.name} onChange={set("name")} />
        <input className="input" placeholder="Seats" type="number" min="0"
               value={form.capacity} onChange={set("capacity")} />
        <button className="btn-solid" disabled={busy}>Add</button>
      </form>
      {venues.length === 0 ? (
        <p className="faint" style={{ fontSize: 14 }}>No venues yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Code</th><th>Name</th><th>Seats</th><th /></tr></thead>
            <tbody>
              {venues.map((v) => (
                <tr key={v.id}>
                  <td><strong>{v.code}</strong></td>
                  <td className="muted">{v.name}</td>
                  <td className="muted">{v.capacity || "-"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn-ghost btn-sm" onClick={() => remove(v)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button className="btn-ghost" onClick={onClose}>Done</button>
      </div>
    </Modal>
  );
}

export default function Timetable() {
  const { org, isAdmin } = useAuth();
  const [slots, setSlots] = useState(null);
  const [courses, setCourses] = useState([]);
  const [venues, setVenues] = useState([]);
  const [error, setError] = useState(null);
  const [venueFilter, setVenueFilter] = useState("");
  const [courseFilter, setCourseFilter] = useState("");
  const [editing, setEditing] = useState(null);   // { slot } | { draft }
  const [managing, setManaging] = useState(false);
  const [flash, setFlash] = useState("");

  const load = useCallback(() => {
    Promise.all([
      api.get("/api/slots/", { params: { term: org?.term, active: true, page_size: 1000 } }),
      api.get("/api/courses/", { params: { page_size: 200 } }),
      api.get("/api/venues/", { params: { page_size: 1000 } }),
    ])
      .then(([s, c, v]) => {
        setSlots(s.data.results ?? s.data);
        setCourses(c.data.results ?? c.data);
        setVenues(v.data.results ?? v.data);
      })
      .catch(setError);
  }, [org?.term]);

  useEffect(load, [load]);

  const shown = useMemo(() => (slots ?? []).filter((s) =>
    (!venueFilter || String(s.venue) === venueFilter) &&
    (!courseFilter || String(s.course) === courseFilter)), [slots, venueFilter, courseFilter]);

  const byDay = useMemo(() => DAYS.map((_, d) =>
    layDay(shown.filter((s) => s.weekday === d))), [shown]);

  function saved(msg) {
    setEditing(null);
    setFlash(msg);
    load();
    setTimeout(() => setFlash(""), 4000);
  }

  // Clicking an empty part of a day starts a one-hour lecture there,
  // snapped to the half hour.
  function clickDay(e, day) {
    if (!isAdmin || e.target !== e.currentTarget) return;
    if (!venues.length || !courses.length) return;
    const box = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - box.left) / box.width;
    let start = FIRST_HOUR * 60 + Math.floor(frac * (LAST_HOUR - FIRST_HOUR) * 2) * 30;
    start = Math.min(start, LAST_HOUR * 60 - 60);
    setEditing({ draft: {
      weekday: day, start_time: toHHMM(start), end_time: toHHMM(start + 60),
      venue: venueFilter ? Number(venueFilter) : undefined,
    } });
  }

  if (error) return <ErrorBox error={error} />;
  if (!slots) return <Loading what="timetable" />;

  const hours = [];
  for (let h = FIRST_HOUR; h < LAST_HOUR; h++) hours.push(h);
  const missing = !venues.length ? "venue" : !courses.length ? "course" : null;

  return (
    <>
      <PageHead title="Timetable" subtitle={`Term ${org?.term} · Monday to Saturday, 07:00 to 18:00`}>
        {isAdmin && (
          <>
            <button className="btn-ghost" onClick={() => setManaging(true)}>Venues</button>
            <button className="btn-solid" disabled={!!missing}
                    onClick={() => setEditing({ draft: {
                      venue: venueFilter ? Number(venueFilter) : undefined } })}>
              Add lecture
            </button>
          </>
        )}
      </PageHead>

      {isAdmin && missing === "venue" && (
        <div className="alert alert-bad">
          Add a venue first. <button className="btn-ghost btn-sm" onClick={() => setManaging(true)}>Add venue</button>
        </div>
      )}
      {isAdmin && missing === "course" && (
        <div className="alert alert-bad">
          Add a course first on the <Link to="/courses">Courses</Link> page.
        </div>
      )}
      {flash && <div className="alert alert-ok">{flash}</div>}

      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <select className="input" style={{ maxWidth: 220 }} value={venueFilter}
                onChange={(e) => setVenueFilter(e.target.value)}>
          <option value="">All venues</option>
          {venues.map((v) => <option key={v.id} value={v.id}>{v.code}</option>)}
        </select>
        <select className="input" style={{ maxWidth: 260 }} value={courseFilter}
                onChange={(e) => setCourseFilter(e.target.value)}>
          <option value="">All courses</option>
          {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
        </select>
        {isAdmin && !missing && (
          <span className="faint" style={{ fontSize: 13 }}>
            Click an empty space to add a lecture there, or a lecture to change it.
          </span>
        )}
      </div>

      {slots.length === 0 && !isAdmin ? (
        <div className="card"><Empty message="No lectures on the timetable yet." /></div>
      ) : (
        <>
        <p className="phone-only faint" style={{ fontSize: 13, margin: "0 0 8px" }}>
          Swipe sideways to see the whole day.
        </p>
        <div className="card tt-card">
          {/* Days down the side, the teaching day across. */}
          <div className="tth" style={{ "--hours": LAST_HOUR - FIRST_HOUR }}>
            <div className="tth-corner" />
            <div className="tth-hours">
              {hours.map((h) => (
                <span key={h} style={{ left: `${((h - FIRST_HOUR) / (LAST_HOUR - FIRST_HOUR)) * 100}%` }}>
                  {toHHMM(h * 60)}
                </span>
              ))}
              <span className="tth-end">{toHHMM(LAST_HOUR * 60)}</span>
            </div>

            {byDay.map((items, d) => {
              const lanes = Math.max(1, ...items.map((i) => i.lanes));
              return (
                <div key={d} className="tth-row">
                  <div className="tth-day">
                    <span className="tt-long">{DAYS[d]}</span>
                    <span className="tt-short">{DAYS[d].slice(0, 3)}</span>
                  </div>
                  <div className={"tth-track" + (isAdmin && !missing ? " editable" : "")}
                       style={{ height: lanes * LANE_PX + 8 }}
                       onClick={(e) => clickDay(e, d)}>
                    {items.map(({ slot: s, lane }) => {
                      const span = (LAST_HOUR - FIRST_HOUR) * 60;
                      const left = (toMin(s.start_time) - FIRST_HOUR * 60) / span * 100;
                      const width = (toMin(s.end_time) - toMin(s.start_time)) / span * 100;
                      return (
                        <button key={s.id} type="button" className="tt-slot"
                                disabled={!isAdmin}
                                title={`${s.course_code} · ${s.course_title}\n${s.start_time.slice(0, 5)}-${s.end_time.slice(0, 5)} · ${s.venue_code}${s.lecturer_name ? `\n${s.lecturer_name}` : ""}`}
                                style={{
                                  left: `calc(${left}% + 2px)`,
                                  width: `calc(${width}% - 4px)`,
                                  top: lane * LANE_PX + 4,
                                  height: LANE_PX - 4,
                                  "--h": hue(s.course_code),
                                }}
                                onClick={() => setEditing({ slot: s })}>
                          <strong>{s.course_code}</strong>
                          <span>{s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)} · {s.venue_code}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        </>
      )}

      {editing && (
        <SlotForm slot={editing.slot} draft={editing.draft}
                  courses={courses} venues={venues}
                  onClose={() => setEditing(null)} onSaved={saved} />
      )}
      {managing && (
        <VenuesDialog venues={venues} onClose={() => setManaging(false)} onChanged={load} />
      )}
    </>
  );
}
