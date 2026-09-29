import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHead, Loading, ErrorBox, Empty } from "../components/bits";

function Stat({ label, value, to, tone }) {
  const body = (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 12, textTransform: "uppercase",
                                      letterSpacing: ".05em" }}>{label}</div>
      <div style={{ fontSize: 30, fontWeight: 700, marginTop: 4,
                    color: tone ? `var(--${tone})` : "inherit" }}>
        {value ?? "-"}
      </div>
    </div>
  );
  return to ? <Link to={to} style={{ color: "inherit" }}>{body}</Link> : body;
}

export default function Overview() {
  const { org } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!org) return;
    Promise.all([
      api.get("/api/organization/"),
      api.get("/api/devices/"),
      api.get("/api/taps/unregistered/?page_size=1"),
      api.get("/api/sessions/?status=open&page_size=5"),
    ])
      .then(([org, devices, unknown, sessions]) => {
        const list = devices.data.results || devices.data;
        setData({
          org: org.data,
          devices: list,
          online: list.filter((d) => d.online).length,
          unknown: unknown.data.count ?? 0,
          sessions: sessions.data.results || sessions.data,
        });
      })
      .catch(setError);
  }, [org]);

  if (!org)
    return (
      <>
        <PageHead title="Overview" />
        <Empty message="No schools registered yet."
               hint="Once a school signs up, it appears in the account menu." />
      </>
    );
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="overview" />;

  return (
    <>
      <PageHead title="Overview" subtitle={data.org.name} />

      <div style={{ display: "grid", gap: 14, marginBottom: 24,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        <Stat label="Students" value={data.org.student_count} to="/students" />
        <Stat label="Devices online"
              value={`${data.online} / ${data.devices.length}`}
              to="/devices"
              tone={data.devices.length && !data.online ? "bad" : null} />
        <Stat label="Cards to register" value={data.unknown} to="/unknown"
              tone={data.unknown ? "warn" : null} />
        <Stat label="Team members" value={data.org.member_count} to="/members" />
      </div>

      <div className="card">
        <h3>Lectures in progress</h3>
        {data.sessions.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            No lecture is running right now.
          </p>
        ) : (
          <table>
            <thead>
              <tr><th>Course</th><th>Venue</th><th>Present</th><th>Late</th><th /></tr>
            </thead>
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id}>
                  <td><strong>{s.course_code}</strong></td>
                  <td className="muted">{s.venue_code}</td>
                  <td>{s.present_count}</td>
                  <td>{s.late_count}</td>
                  <td style={{ textAlign: "right" }}>
                    <Link to={`/sessions/${s.id}`}>View</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
