import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../lib/api";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";

// Date range shared by both report screens; remembered for the session
// so moving between the overview and a course keeps the same range.
function useRange() {
  const read = (k) => { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } };
  const [from, setFrom] = useState(() => read("reportFrom"));
  const [to, setTo] = useState(() => read("reportTo"));
  useEffect(() => {
    try { sessionStorage.setItem("reportFrom", from); sessionStorage.setItem("reportTo", to); }
    catch { /* optional */ }
  }, [from, to]);
  const params = { ...(from ? { from } : {}), ...(to ? { to } : {}) };
  return { from, to, setFrom, setTo, params };
}

function RangePicker({ range }) {
  return (
    <div className="row filters" style={{ flexWrap: "wrap" }}>
      <label className="row date-in">From
        <input className="input" type="date" value={range.from} max={range.to || undefined}
               onChange={(e) => range.setFrom(e.target.value)} /></label>
      <label className="row date-in">To
        <input className="input" type="date" value={range.to} min={range.from || undefined}
               onChange={(e) => range.setTo(e.target.value)} /></label>
      {(range.from || range.to) && (
        <button className="btn-ghost btn-sm" onClick={() => { range.setFrom(""); range.setTo(""); }}>
          Whole term
        </button>
      )}
    </div>
  );
}

function Rate({ value, threshold }) {
  if (value == null) return <span className="faint">-</span>;
  const tone = value < threshold ? "bad" : value < threshold + 10 ? "warn" : "ok";
  return (
    <span className="rate">
      <span className="rate-bar"><span style={{ width: `${Math.min(value, 100)}%`,
                                                background: `var(--${tone})` }} /></span>
      <span style={{ color: `var(--${tone})` }}>{value}%</span>
    </span>
  );
}

export default function Reports() {
  const range = useRange();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const key = JSON.stringify(range.params);

  useEffect(() => {
    setError(null);
    api.get("/api/reports/overview/", { params: JSON.parse(key) })
       .then(({ data }) => setData(data)).catch(setError);
  }, [key]);

  return (
    <>
      <PageHead title="Reports" subtitle={data ? `Attendance by course · term ${data.term}` : null} />
      <RangePicker range={range} />
      <ErrorBox error={error} />
      <div className="card" style={{ padding: 0 }}>
        {!data ? <Loading what="report" /> : data.courses.length === 0 ? (
          <Empty message="No courses to report on." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Course</th><th>Lecturer</th><th>Enrolled</th>
                    <th>Lectures held</th><th>Attendance</th>
                    <th title={`Below ${data.at_risk_percent}% attendance`}>At risk</th></tr>
              </thead>
              <tbody>
                {data.courses.map((c) => (
                  <tr key={c.course_id}>
                    <td>
                      <Link to={`/reports/${c.course_id}`}><strong>{c.code}</strong></Link>
                      <small className="faint" style={{ display: "block" }}>{c.title}</small>
                    </td>
                    <td className="muted">{c.lecturer || "-"}</td>
                    <td>{c.enrolled}</td>
                    <td>{c.held}</td>
                    <td><Rate value={c.attendance_rate} threshold={data.at_risk_percent} /></td>
                    <td>{c.at_risk ? <span className="pill pill-bad">{c.at_risk}</span>
                                   : <span className="faint">0</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {data && (
        <p className="faint" style={{ fontSize: 13, marginTop: 12 }}>
          A lecture counts as held once its start time has passed, unless it was cancelled.
          At risk: below {data.at_risk_percent}% of lectures attended.
        </p>
      )}
    </>
  );
}

export function CourseReport() {
  const { id } = useParams();
  const range = useRange();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [onlyRisk, setOnlyRisk] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const key = JSON.stringify(range.params);

  useEffect(() => {
    setError(null);
    api.get(`/api/reports/course/${id}/`, { params: JSON.parse(key) })
       .then(({ data }) => setData(data)).catch(setError);
  }, [id, key]);

  // Fetched through the API client so the login token goes with it; a
  // plain link would arrive at the server unauthenticated.
  async function download() {
    setDownloading(true);
    try {
      const resp = await api.get(`/api/reports/course/${id}/`, {
        params: { ...range.params, export: "csv" }, responseType: "blob" });
      const name = /filename="([^"]+)"/.exec(resp.headers["content-disposition"] || "")?.[1]
                   || "attendance.csv";
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err);
    } finally {
      setDownloading(false);
    }
  }

  if (error && !data) return <ErrorBox error={error} />;
  if (!data) return <Loading what="register" />;
  const students = onlyRisk ? data.students.filter((s) => s.at_risk) : data.students;

  return (
    <>
      <p style={{ margin: "0 0 10px", fontSize: 14 }}><Link to="/reports">← Reports</Link></p>
      <PageHead title={`${data.course.code} · ${data.course.title}`}
                subtitle={`${data.held} lecture${data.held === 1 ? "" : "s"} held${data.course.lecturer ? ` · ${data.course.lecturer}` : ""}`}>
        <button className="btn-solid" onClick={download} disabled={downloading}>
          {downloading ? "Preparing..." : "Download register (CSV)"}
        </button>
      </PageHead>
      <RangePicker range={range} />
      <ErrorBox error={error} />

      <div className="spread filters">
        <h3 style={{ margin: 0 }}>Students</h3>
        <label className="row" style={{ fontWeight: 400, fontSize: 14, margin: 0 }}>
          <input type="checkbox" checked={onlyRisk} style={{ flex: "0 0 auto" }}
                 onChange={(e) => setOnlyRisk(e.target.checked)} />
          Only below {data.at_risk_percent}%
        </label>
      </div>
      <div className="card" style={{ padding: 0, marginBottom: 24 }}>
        {students.length === 0 ? <Empty message={onlyRisk ? "Nobody is below the line." : "Nobody is enrolled."} /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Student</th><th>Level</th><th>Present</th><th>Late</th>
                         <th>Absent</th><th>Attendance</th></tr></thead>
              <tbody>
                {students.map((s) => (
                  <tr key={s.student_id}>
                    <td><strong>{s.full_name}</strong>
                      {s.matric_no && <small className="faint" style={{ display: "block" }}>{s.matric_no}</small>}</td>
                    <td className="muted">{s.level || "-"}</td>
                    <td>{s.present}</td>
                    <td>{s.late}</td>
                    <td>{s.absent}</td>
                    <td><Rate value={s.percentage} threshold={data.at_risk_percent} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <h3>Lectures</h3>
      <div className="card" style={{ padding: 0 }}>
        {data.lectures.length === 0 ? <Empty message="No lectures held in this range." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Lecture</th><th>Venue</th><th>Present</th><th>Late</th><th>Absent</th></tr></thead>
              <tbody>
                {[...data.lectures].reverse().map((l) => (
                  <tr key={l.id}>
                    <td>{l.label}</td>
                    <td className="muted">{l.venue}</td>
                    <td>{l.present}</td>
                    <td>{l.late}</td>
                    <td>{l.absent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
