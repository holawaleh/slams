import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useList, useDebounced } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox, errorText } from "../components/bits";
import Modal from "../components/Modal";
import Pager from "../components/Pager";
import CardCapture from "../components/CardCapture";

const BLANK = { full_name: "", phone: "", department: "", level: "",
                email: "", card_uid: "", matric_no: "", active: true };

function activeCard(student) {
  return student?.cards?.find((c) => c.active && !c.is_admin);
}

function StudentForm({ student, onClose, onSaved }) {
  const editing = !!student;
  const current = activeCard(student);
  const [form, setForm] = useState(editing ? {
    full_name: student.full_name, phone: student.phone,
    department: student.department, level: student.level,
    email: student.email, card_uid: current?.uid ?? "",
    matric_no: student.matric_no, active: student.active,
  } : BLANK);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) =>
    setForm({ ...form, [k]: e.target.type === "checkbox"
                              ? e.target.checked : e.target.value });
  // Field-level messages from the server, shown under each input.
  const fieldErr = (k) => {
    const v = error?.response?.data?.[k];
    return v ? <small className="field-error">{Array.isArray(v) ? v.join(" ") : v}</small> : null;
  };
  const replacing = editing && current && form.card_uid &&
    form.card_uid.replace(/[\s:-]/g, "").toUpperCase() !== current.uid;

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...form };
    if (editing && body.card_uid === (current?.uid ?? "")) delete body.card_uid;
    try {
      if (editing) await api.patch(`/api/students/${student.id}/`, body);
      else await api.post("/api/students/", body);
      onSaved(editing ? "Student updated." : `${form.full_name.trim()} added.`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${student.full_name}? This cannot be undone.`))
      return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/students/${student.id}/`);
      onSaved(`${student.full_name} deleted.`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const fields = error?.response?.status === 400 ? error.response.data : {};
  const generalError = error && !Object.keys(fields).some((k) => k in BLANK) ? error : null;

  return (
    <Modal title={editing ? "Edit student" : "Add student"} onClose={onClose} width={560}>
      <form onSubmit={save} noValidate>
        {generalError && <div className="alert alert-bad">{errorText(generalError)}</div>}

        <div className="field">
          <label htmlFor="name">Full name</label>
          <input id="name" className="input" required autoFocus maxLength={128}
                 autoComplete="off" placeholder="As it should appear on records"
                 value={form.full_name} onChange={set("full_name")} />
          {fieldErr("full_name")}
        </div>

        <div className="form-2">
          <div className="field">
            <label htmlFor="phone">Phone no</label>
            <input id="phone" className="input" type="tel" inputMode="tel"
                   placeholder="08031234567" maxLength={20}
                   value={form.phone} onChange={set("phone")} />
            {fieldErr("phone")}
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" className="input" type="email"
                   placeholder="name@example.com"
                   value={form.email} onChange={set("email")} />
            {fieldErr("email")}
          </div>
          <div className="field">
            <label htmlFor="dept">Department</label>
            <input id="dept" className="input" maxLength={64}
                   value={form.department} onChange={set("department")} />
            {fieldErr("department")}
          </div>
          <div className="field">
            <label htmlFor="level">Level</label>
            <input id="level" className="input" placeholder="e.g. 200" maxLength={8}
                   list="level-options" value={form.level} onChange={set("level")} />
            <datalist id="level-options">
              {["100", "200", "300", "400", "500", "600", "ND1", "ND2", "HND1", "HND2"]
                .map((l) => <option key={l} value={l} />)}
            </datalist>
            {fieldErr("level")}
          </div>
        </div>

        <div className="field">
          <label htmlFor="uid">Card UID</label>
          <div className="row">
            <input id="uid" className="input mono" placeholder="Tap Scan, or type it: 0A3F05B2"
                   maxLength={32} autoComplete="off" spellCheck={false}
                   value={form.card_uid} onChange={set("card_uid")} />
            {!scanning && (
              <button type="button" className="btn-ghost" style={{ flex: "0 0 auto" }}
                      onClick={() => setScanning(true)}>Scan card</button>
            )}
          </div>
          {scanning && (
            <CardCapture studentId={student?.id}
                         onCancel={() => setScanning(false)}
                         onCaptured={(uid) => { setForm({ ...form, card_uid: uid }); setScanning(false); }} />
          )}
          {fieldErr("card_uid")}
          {replacing && (
            <small className="faint" style={{ display: "block", marginTop: 6 }}>
              Their current card {current.uid} will be revoked.
            </small>
          )}
          {!scanning && !form.card_uid && (
            <small className="faint" style={{ display: "block", marginTop: 6 }}>
              Optional now; a card can be registered later from New cards.
            </small>
          )}
        </div>

        <div className="field">
          <label htmlFor="matric">Matric number <span className="faint">(optional)</span></label>
          <input id="matric" className="input" maxLength={32}
                 value={form.matric_no} onChange={set("matric_no")} />
          {fieldErr("matric_no")}
        </div>

        {editing && (
          <label className="row" style={{ fontWeight: 400, fontSize: 14,
                                          marginBottom: 18 }}>
            <input type="checkbox" checked={form.active} onChange={set("active")}
                   style={{ flex: "0 0 auto" }} />
            Active. Inactive students are left off lecture rosters.
          </label>
        )}
        <div className="spread">
          {editing ? (
            <button type="button" className="btn-danger" disabled={busy}
                    onClick={remove}>Delete</button>
          ) : <span />}
          <div className="row">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn-solid" disabled={busy || !form.full_name.trim()}>
              {busy ? "Saving..." : editing ? "Save" : "Add student"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

function StudentDetail({ student, canEdit, onEdit, onClose }) {
  const [courses, setCourses] = useState(null);
  const [stats, setStats] = useState([]);
  const [error, setError] = useState(null);
  const { org } = useAuth();

  useEffect(() => {
    Promise.all([
      api.get("/api/enrollments/", { params: { student: student.id,
                                                term: org?.term } }),
      api.get(`/api/students/${student.id}/attendance/`),
    ])
      .then(([e, a]) => {
        setCourses(e.data.results ?? e.data);
        setStats(a.data);
      })
      .catch(setError);
  }, [student.id, org?.term]);

  const pct = (code) => stats.find((s) => s.course === code);
  const card = activeCard(student);
  const facts = [
    ["Phone", student.phone], ["Email", student.email],
    ["Department", student.department], ["Level", student.level],
    ["Matric no", student.matric_no],
  ].filter(([, v]) => v);

  return (
    <Modal title={student.full_name} onClose={onClose} width={560}>
      <div className="row" style={{ flexWrap: "wrap", marginTop: -6, marginBottom: 14 }}>
        {card ? <span className="pill pill-ok">Card {card.uid}</span>
              : <span className="pill pill-warn">No card</span>}
        {!student.active && <span className="pill pill-bad">Inactive</span>}
      </div>
      {facts.length > 0 && (
        <dl className="facts">
          {facts.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}

      <ErrorBox error={error} />
      <h3>Courses this term</h3>
      {!courses ? <Loading what="courses" /> : courses.length === 0 ? (
        <p className="faint" style={{ fontSize: 14 }}>
          Not enrolled on any course. Enrol from a course's page.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Course</th><th>Attended</th><th>Late</th><th>Rate</th></tr>
            </thead>
            <tbody>
              {courses.map((c) => {
                const s = pct(c.course_code);
                return (
                  <tr key={c.id}>
                    <td><strong>{c.course_code}</strong></td>
                    <td>{s ? `${s.attended} / ${s.sessions_held}` : "-"}</td>
                    <td>{s?.late ?? "-"}</td>
                    <td>{s?.percentage != null ? `${s.percentage}%` : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="row" style={{ justifyContent: "flex-end", marginTop: 18 }}>
        <button className="btn-ghost" onClick={onClose}>Close</button>
        {canEdit && <button className="btn-solid" onClick={onEdit}>Edit</button>}
      </div>
    </Modal>
  );
}

export default function Students() {
  const { isAdmin } = useAuth();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("true");
  const [level, setLevel] = useState("");
  const [card, setCard] = useState("");
  const [levels, setLevels] = useState([]);
  const search = useDebounced(query);
  const params = { search, ...(status ? { active: status } : {}),
                   ...(level ? { level } : {}), ...(card ? { has_card: card } : {}) };
  const { rows, count, page, setPage, loading, error, reload } =
    useList("/api/students/", params);

  const [editing, setEditing] = useState(null);   // null | "new" | student
  const [viewing, setViewing] = useState(null);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    api.get("/api/students/levels/").then(({ data }) => setLevels(data)).catch(() => {});
  }, [flash]);

  function saved(msg) {
    setEditing(null);
    setViewing(null);
    setFlash(msg);
    reload();
    setTimeout(() => setFlash(""), 4000);
  }

  return (
    <>
      <PageHead title="Students" subtitle={`${count} shown`}>
        {isAdmin && (
          <button className="btn-solid" onClick={() => setEditing("new")}>
            Add student
          </button>
        )}
      </PageHead>

      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "2 1 260px" }}
               placeholder="Search name, level, matric no, phone, email or card"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="input" style={{ flex: "1 1 130px" }} value={level}
                onChange={(e) => setLevel(e.target.value)} aria-label="Level">
          <option value="">All levels</option>
          {levels.map((l) => <option key={l} value={l}>{l} level</option>)}
        </select>
        <select className="input" style={{ flex: "1 1 130px" }} value={card}
                onChange={(e) => setCard(e.target.value)} aria-label="Card">
          <option value="">Any card status</option>
          <option value="true">Has a card</option>
          <option value="false">No card yet</option>
        </select>
        <select className="input" style={{ flex: "1 1 120px" }} value={status}
                onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="true">Active</option>
          <option value="false">Inactive</option>
          <option value="">All</option>
        </select>
      </div>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="students" /> : rows.length === 0 ? (
          <Empty message={search || level || card ? "No student matches these filters."
                                                  : "No students yet."}
                 hint={isAdmin && !search ? "Add a student and scan their card in one go." : null} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Full name</th><th>Phone</th><th>Department</th>
                  <th>Level</th><th>Card</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const c = activeCard(s);
                  return (
                    <tr key={s.id} className="clickable" onClick={() => setViewing(s)}>
                      <td>
                        <strong>{s.full_name}</strong>
                        {!s.active && <span className="pill pill-bad" style={{ marginLeft: 8 }}>inactive</span>}
                        {s.matric_no && <small className="faint" style={{ display: "block" }}>{s.matric_no}</small>}
                      </td>
                      <td className="muted">{s.phone || "-"}</td>
                      <td className="muted">{s.department || "-"}</td>
                      <td className="muted">{s.level || "-"}</td>
                      <td>
                        {c ? <code className="mono" style={{ fontSize: 13 }}>{c.uid}</code>
                           : <span className="pill pill-warn">none</span>}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {isAdmin && (
                          <button className="btn-ghost btn-sm"
                                  onClick={(e) => { e.stopPropagation(); setEditing(s); }}>
                            Edit
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Pager page={page} setPage={setPage} count={count} />

      {viewing && (
        <StudentDetail student={viewing} canEdit={isAdmin}
                       onClose={() => setViewing(null)}
                       onEdit={() => { setEditing(viewing); setViewing(null); }} />
      )}
      {editing && (
        <StudentForm student={editing === "new" ? null : editing}
                     onClose={() => setEditing(null)} onSaved={saved} />
      )}
    </>
  );
}
