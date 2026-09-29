import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useList, useDebounced } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";
import Modal from "../components/Modal";
import Pager from "../components/Pager";

const BLANK = { matric_no: "", first_name: "", last_name: "",
                department: "", level: "", active: true };

function StudentForm({ student, onClose, onSaved }) {
  const editing = !!student;
  const [form, setForm] = useState(editing ? {
    matric_no: student.matric_no, first_name: student.first_name,
    last_name: student.last_name, department: student.department,
    level: student.level, active: student.active,
  } : BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) =>
    setForm({ ...form, [k]: e.target.type === "checkbox"
                              ? e.target.checked : e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (editing) await api.patch(`/api/students/${student.id}/`, form);
      else await api.post("/api/students/", form);
      onSaved(editing ? "Student updated." : `${form.matric_no.toUpperCase()} added.`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${student.matric_no}? This cannot be undone.`))
      return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/students/${student.id}/`);
      onSaved(`${student.matric_no} deleted.`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={editing ? "Edit student" : "Add student"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className="field">
          <label htmlFor="matric">Matric number</label>
          <input id="matric" className="input" required autoFocus
                 value={form.matric_no} onChange={set("matric_no")} />
        </div>
        <div className="form-2">
          <div className="field">
            <label htmlFor="first">First name</label>
            <input id="first" className="input" required
                   value={form.first_name} onChange={set("first_name")} />
          </div>
          <div className="field">
            <label htmlFor="last">Last name</label>
            <input id="last" className="input" required
                   value={form.last_name} onChange={set("last_name")} />
          </div>
          <div className="field">
            <label htmlFor="dept">Department</label>
            <input id="dept" className="input"
                   value={form.department} onChange={set("department")} />
          </div>
          <div className="field">
            <label htmlFor="level">Level</label>
            <input id="level" className="input" placeholder="e.g. 200"
                   maxLength={8} value={form.level} onChange={set("level")} />
          </div>
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
            <button className="btn-solid" disabled={busy}>
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
  const active = student.cards?.filter((c) => c.active) ?? [];

  return (
    <Modal title={student.full_name} onClose={onClose} width={560}>
      <p className="muted" style={{ marginTop: -8 }}>
        {student.matric_no}
        {student.department && ` · ${student.department}`}
        {student.level && ` · ${student.level} level`}
      </p>

      <div className="row" style={{ flexWrap: "wrap", marginBottom: 18 }}>
        {active.length ? active.map((c) => (
          <span key={c.id} className="pill pill-ok">Card {c.uid}</span>
        )) : <span className="pill pill-warn">No card</span>}
        {!student.active && <span className="pill pill-bad">Inactive</span>}
      </div>

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
  const search = useDebounced(query);
  const params = { search, ...(status ? { active: status } : {}) };
  const { rows, count, page, setPage, loading, error, reload } =
    useList("/api/students/", params);

  const [editing, setEditing] = useState(null);   // null | "new" | student
  const [viewing, setViewing] = useState(null);
  const [flash, setFlash] = useState("");

  function saved(msg) {
    setEditing(null);
    setViewing(null);
    setFlash(msg);
    reload();
    setTimeout(() => setFlash(""), 4000);
  }

  return (
    <>
      <PageHead title="Students" subtitle={`${count} ${status === "false" ? "inactive" : status ? "active" : "in total"}`}>
        {isAdmin && (
          <button className="btn-solid" onClick={() => setEditing("new")}>
            Add student
          </button>
        )}
      </PageHead>

      <div className="row filters">
        <input className="input" placeholder="Search by matric number or name"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="input" value={status} style={{ maxWidth: 160 }}
                onChange={(e) => setStatus(e.target.value)}>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
          <option value="">All</option>
        </select>
      </div>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="students" /> : rows.length === 0 ? (
          <Empty message={search ? "No student matches that search."
                                 : "No students yet."}
                 hint={isAdmin && !search ? "Add a student, then register their card from New cards." : null} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Matric no</th><th>Name</th><th>Department</th>
                  <th>Level</th><th>Card</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} className="clickable" onClick={() => setViewing(s)}>
                    <td><code>{s.matric_no}</code></td>
                    <td>
                      <strong>{s.full_name}</strong>
                      {!s.active && <span className="pill pill-bad" style={{ marginLeft: 8 }}>inactive</span>}
                    </td>
                    <td className="muted">{s.department || "-"}</td>
                    <td className="muted">{s.level || "-"}</td>
                    <td>
                      {s.cards?.some((c) => c.active)
                        ? <span className="pill pill-ok">registered</span>
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
                ))}
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
