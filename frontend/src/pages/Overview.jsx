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
  const { org, isAdmin } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!org) return;
    // Readers and card counts are for admins only; a lecturer or viewer
    // gets the parts they are allowed to see instead of an error page.
    const optional = (p) => p.then((r) => r.data).catch(() => null);
    const lecturerUp = org.role !== "viewer";
    Promise.all([
      api.get("/api/organization/").then((r) => r.data),
      isAdmin ? optional(api.get("/api/devices/", { params: { active: true } })) : null,
      isAdmin ? optional(api.get("/api/cards/summary/")) : null,
      lecturerUp ? optional(api.get("/api/sessions/", { params: { running: true, page_size: 20 } })) : null,
    ])
      .then(([orgData, devices, cards, sessions]) => {
        const list = devices ? devices.results ?? devices : null;
        setData({
          org: orgData,
          devices: list,
          online: list ? list.filter((d) => d.online).length : 0,
          cards,
          sessions: sessions ? sessions.results ?? sessions : null,
        });
      })
      .catch(setError);
  }, [org, isAdmin]);

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
        {data.devices && (
          <Stat label="Readers online"
                value={`${data.online} / ${data.devices.length}`}
                to="/settings/devices"
                tone={data.devices.length && !data.online ? "bad" : null} />
        )}
        {data.cards && (
          <Stat label="Cards unused since issue" value={data.cards.never_used} to="/cards"
                tone={data.cards.never_used ? "warn" : null} />
        )}
        <Stat label="Staff" value={data.org.member_count}
              to={isAdmin ? "/settings/team" : null} />
      </div>

      <div className="card">
        <h3>Lectures in progress</h3>
        {data.sessions === null ? (
          <p className="muted" style={{ margin: 0 }}>
            See <Link to="/timetable">the timetable</Link> for this week's lectures.
          </p>
        ) : data.sessions.length === 0 ? (
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
                    <Link to={`/reports/${s.course}`}>Course report</Link>
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
