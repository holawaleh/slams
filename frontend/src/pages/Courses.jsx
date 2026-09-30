import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useList, useDebounced } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";
import Modal from "../components/Modal";
import Pager from "../components/Pager";

// People who can be put in charge of a course.
function useLecturers(enabled) {
  const [people, setPeople] = useState([]);
  useEffect(() => {
    if (!enabled) return;
    api.get("/api/members/")
       .then(({ data }) => setPeople((data.results ?? data)
         .filter((m) => ["owner", "admin", "lecturer"].includes(m.role))))
       .catch(() => setPeople([]));
  }, [enabled]);
  return people;
}

export function CourseForm({ course, onClose, onSaved, onDeleted }) {
  const editing = !!course;
  // A new course is created without a lecturer; one can be assigned
  // afterwards from Edit, once the course exists.
  const lecturers = useLecturers(editing);
  const [form, setForm] = useState({
    code: course?.code ?? "", title: course?.title ?? "",
    lecturer: course?.lecturer ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { code: form.code.trim().toUpperCase(), title: form.title };
    if (editing) body.lecturer = form.lecturer || null;
    try {
      const { data } = editing
        ? await api.patch(`/api/courses/${course.id}/`, body)
        : await api.post("/api/courses/", body);
      onSaved(data);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${course.code}? Its enrolments and timetable slots go with it.`))
      return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/courses/${course.id}/`);
      onDeleted();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={editing ? "Edit course" : "Add course"} onClose={onClose}>
      <form onSubmit={save}>
        <ErrorBox error={error} />
        <div className={editing ? "form-2" : ""}>
          <div className="field">
            <label htmlFor="code">Course code</label>
            <input id="code" className="input" required maxLength={12}
                   autoFocus placeholder="CSC101"
                   value={form.code} onChange={set("code")} />
          </div>
          {editing && <div className="field">
            <label htmlFor="lect">Lecturer</label>
            <select id="lect" className="input" value={form.lecturer ?? ""}
                    onChange={set("lecturer")}>
              <option value="">Not assigned</option>
              {lecturers.map((m) => (
                <option key={m.user} value={m.user}>
                  {m.full_name || m.username}
                </option>
              ))}
            </select>
          </div>}
        </div>
        <div className="field">
          <label htmlFor="title">Title</label>
          <input id="title" className="input" required maxLength={128}
                 placeholder="Introduction to Computer Science"
                 value={form.title} onChange={set("title")} />
        </div>
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
              {busy ? "Saving..." : editing ? "Save" : "Add course"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

export default function Courses() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const { rows, count, page, setPage, loading, error } =
    useList("/api/courses/", { search });
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHead title="Courses" subtitle={`${count} course${count === 1 ? "" : "s"}`}>
        {isAdmin && (
          <button className="btn-solid" onClick={() => setAdding(true)}>
            Add course
          </button>
        )}
      </PageHead>

      <div className="row filters">
        <input className="input" placeholder="Search by code or title"
               value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <ErrorBox error={error} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="courses" /> : rows.length === 0 ? (
          <Empty message={search ? "No course matches that search." : "No courses yet."}
                 hint={isAdmin && !search ? "Add a course, then enrol students on it." : null} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Code</th><th>Title</th><th>Lecturer</th><th>Enrolled</th></tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="clickable"
                      onClick={() => navigate(`/courses/${c.id}`)}>
                    <td><Link to={`/courses/${c.id}`} onClick={(e) => e.stopPropagation()}>
                      <strong>{c.code}</strong></Link></td>
                    <td>{c.title}</td>
                    <td className="muted">{c.lecturer_name || "-"}</td>
                    <td>{c.enrolled_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Pager page={page} setPage={setPage} count={count} />

      {adding && (
        <CourseForm onClose={() => setAdding(false)}
                    onSaved={(c) => navigate(`/courses/${c.id}`)} />
      )}
    </>
  );
}

function EnrolDialog({ course, term, onClose, onDone }) {
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const [found, setFound] = useState([]);
  const [enrolled, setEnrolled] = useState(new Set());
  const [picked, setPicked] = useState(new Map());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Who is already on the course, so they can be shown as such rather
  // than offered again.
  useEffect(() => {
    api.get("/api/enrollments/", { params: { course: course.id, term,
                                              page_size: 1000 } })
       .then(({ data }) => setEnrolled(new Set((data.results ?? data)
         .map((e) => e.student))))
       .catch(() => {});
  }, [course.id, term]);

  useEffect(() => {
    api.get("/api/students/", { params: { search, active: true, page_size: 25 } })
       .then(({ data }) => setFound(data.results ?? data))
       .catch(() => setFound([]));
  }, [search]);

  function toggle(s) {
    const next = new Map(picked);
    if (next.has(s.id)) next.delete(s.id);
    else next.set(s.id, s);
    setPicked(next);
  }

  const selectable = found.filter((s) => !enrolled.has(s.id));
  const allPicked = selectable.length > 0 && selectable.every((s) => picked.has(s.id));

  function toggleAll() {
    const next = new Map(picked);
    for (const s of selectable) {
      if (allPicked) next.delete(s.id);
      else next.set(s.id, s);
    }
    setPicked(next);
  }

  async function enrol() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post("/api/enrollments/bulk/", {
        course: course.id, term, student_ids: [...picked.keys()],
      });
      onDone(data.created);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={`Enrol students on ${course.code}`} onClose={onClose} width={560}>
      <p className="muted" style={{ marginTop: 0 }}>Term {term}</p>
      <ErrorBox error={error} />
      <div className="field">
        <input className="input" autoFocus value={query}
               placeholder="Search by matric number or name"
               onChange={(e) => setQuery(e.target.value)} />
      </div>

      <div className="pick-list">
        {found.length === 0 ? (
          <p className="faint" style={{ fontSize: 14, padding: 12, margin: 0 }}>
            No active student matches.
          </p>
        ) : (
          <>
            {selectable.length > 1 && (
              <label className="pick-row pick-all">
                <input type="checkbox" checked={allPicked} onChange={toggleAll} />
                <span>Select all {selectable.length} shown</span>
              </label>
            )}
            {found.map((s) => {
              const already = enrolled.has(s.id);
              return (
                <label key={s.id} className={"pick-row" + (already ? " done" : "")}>
                  <input type="checkbox" disabled={already}
                         checked={already || picked.has(s.id)}
                         onChange={() => toggle(s)} />
                  <span className="grow">
                    {s.full_name}
                    <small className="faint" style={{ display: "block" }}>{s.matric_no}</small>
                  </span>
                  {already && <span className="pill">enrolled</span>}
                </label>
              );
            })}
          </>
        )}
      </div>

      <div className="spread" style={{ marginTop: 16 }}>
        <span className="faint" style={{ fontSize: 14 }}>{picked.size} selected</span>
        <div className="row">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-solid" disabled={!picked.size || busy} onClick={enrol}>
            {busy ? "Enrolling..." : `Enrol ${picked.size || ""}`.trim()}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function CourseDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { org, isAdmin } = useAuth();
  const [course, setCourse] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [flash, setFlash] = useState("");
  const [actionError, setActionError] = useState(null);

  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const term = org?.term;
  const roster = useList("/api/enrollments/", { course: id, term, search });

  useEffect(() => {
    api.get(`/api/courses/${id}/`).then(({ data }) => setCourse(data))
       .catch(setLoadError);
  }, [id]);

  function note(msg) {
    setFlash(msg);
    setTimeout(() => setFlash(""), 4000);
  }

  async function unenrol(e) {
    if (!window.confirm(`Remove ${e.full_name} from ${course.code}?`)) return;
    setActionError(null);
    try {
      await api.delete(`/api/enrollments/${e.id}/`);
      note(`${e.matric_no} removed.`);
      roster.reload();
      setCourse({ ...course, enrolled_count: course.enrolled_count - 1 });
    } catch (err) {
      setActionError(err);
    }
  }

  if (loadError) return <ErrorBox error={loadError} />;
  if (!course) return <Loading what="course" />;

  return (
    <>
      <p style={{ margin: "0 0 10px", fontSize: 14 }}>
        <Link to="/courses">← Courses</Link>
      </p>
      <PageHead title={`${course.code} · ${course.title}`}
                subtitle={`Lecturer: ${course.lecturer_name || "not assigned"}`}>
        {isAdmin && (
          <>
            <button className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>
            <button className="btn-solid" onClick={() => setEnrolling(true)}>
              Enrol students
            </button>
          </>
        )}
      </PageHead>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={actionError || roster.error} />

      <div className="spread filters">
        <h3 style={{ margin: 0 }}>
          Enrolled this term <span className="faint">({roster.count})</span>
        </h3>
        <input className="input" style={{ maxWidth: 280 }} value={query}
               placeholder="Search the roster"
               onChange={(e) => setQuery(e.target.value)} />
      </div>

      <div className="card" style={{ padding: 0 }}>
        {roster.loading ? <Loading what="roster" /> : roster.rows.length === 0 ? (
          <Empty message={search ? "Nobody on the roster matches." : "No students enrolled yet."}
                 hint={isAdmin && !search ? "Students must be enrolled for their taps to count in this course's lectures." : null} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Matric no</th><th>Name</th><th /></tr>
              </thead>
              <tbody>
                {roster.rows.map((e) => (
                  <tr key={e.id}>
                    <td><code>{e.matric_no}</code></td>
                    <td>{e.full_name}</td>
                    <td style={{ textAlign: "right" }}>
                      {isAdmin && (
                        <button className="btn-ghost btn-sm" onClick={() => unenrol(e)}>
                          Remove
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

      <Pager page={roster.page} setPage={roster.setPage} count={roster.count} size={200} />

      {editing && (
        <CourseForm course={course} onClose={() => setEditing(false)}
                    onSaved={(c) => { setCourse({ ...course, ...c }); setEditing(false); note("Course updated."); }}
                    onDeleted={() => navigate("/courses")} />
      )}
      {enrolling && (
        <EnrolDialog course={course} term={term} onClose={() => setEnrolling(false)}
                     onDone={(n) => {
                       setEnrolling(false);
                       note(`${n} student${n === 1 ? "" : "s"} enrolled.`);
                       roster.reload();
                       setCourse({ ...course, enrolled_count: course.enrolled_count + n });
                     }} />
      )}
    </>
  );
}
