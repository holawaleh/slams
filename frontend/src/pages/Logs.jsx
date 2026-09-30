import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { useList, useDebounced } from "../lib/useList";
import { Loading, Empty, ErrorBox } from "../components/bits";
import Pager from "../components/Pager";

// What the server decided about each swipe.
export const OUTCOMES = {
  present:      ["Present", "ok"],
  late:         ["Late", "warn"],
  no_session:   ["Outside lecture time", "bad"],
  not_enrolled: ["Not enrolled", "bad"],
  unknown:      ["Unregistered card", "bad"],
  time_unknown: ["Time unknown", "bad"],
  admin:        ["Admin card", ""],
  enroll_scan:  ["Enrolment scan", ""],
};

function Outcome({ value }) {
  const [label, tone] = OUTCOMES[value] ?? [value, ""];
  return <span className={"pill" + (tone ? ` pill-${tone}` : "")}>{label}</span>;
}

function when(iso, tz) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: tz,
  });
}

export function Swipes() {
  const { org } = useAuth();
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const [outcome, setOutcome] = useState("");
  const [device, setDevice] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [devices, setDevices] = useState([]);
  const params = { search, ...(outcome ? { outcome } : {}),
                   ...(device ? { device } : {}),
                   ...(from ? { date_from: from } : {}), ...(to ? { date_to: to } : {}) };
  const { rows, count, page, setPage, loading, error } = useList("/api/taps/", params);

  useEffect(() => {
    api.get("/api/devices/").then(({ data }) => setDevices(data.results ?? data))
       .catch(() => setDevices([]));
  }, []);

  return (
    <>
      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "2 1 220px" }} value={query}
               placeholder="Search student, matric no, card or reader"
               onChange={(e) => setQuery(e.target.value)} />
        <select className="input" style={{ flex: "1 1 160px" }} value={outcome}
                onChange={(e) => setOutcome(e.target.value)} aria-label="Outcome">
          <option value="">Every outcome</option>
          {Object.entries(OUTCOMES).map(([k, [label]]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <select className="input" style={{ flex: "1 1 140px" }} value={device}
                onChange={(e) => setDevice(e.target.value)} aria-label="Reader">
          <option value="">Every reader</option>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <label className="row date-in">From
          <input className="input" type="date" value={from} max={to || undefined}
                 onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row date-in">To
          <input className="input" type="date" value={to} min={from || undefined}
                 onChange={(e) => setTo(e.target.value)} /></label>
      </div>

      <ErrorBox error={error} />
      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="history" /> : rows.length === 0 ? (
          <Empty message="No swipes match." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Who</th><th>Card</th><th>Reader</th>
                    <th>Result</th><th>Lecture</th></tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>
                      {when(t.tapped_at, org?.timezone)}
                      {t.time_conf !== "synced" && (
                        <small className="faint" style={{ display: "block" }}>
                          {t.time_conf === "drift" ? "clock drifting" : "time estimated"}
                        </small>
                      )}
                    </td>
                    <td>{t.student_name || <span className="faint">-</span>}</td>
                    <td><code className="mono" style={{ fontSize: 13 }}>{t.uid}</code></td>
                    <td className="muted">{t.device_name}</td>
                    <td>
                      <Outcome value={t.outcome} />
                      {t.device_outcome && t.device_outcome !== t.outcome && (
                        <small className="faint" style={{ display: "block" }}
                               title="What the reader showed at the time, before the server checked it">
                          reader said {OUTCOMES[t.device_outcome]?.[0]?.toLowerCase() ?? t.device_outcome}
                        </small>
                      )}
                    </td>
                    <td className="muted">{t.course_code || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
    </>
  );
}

const ACTIONS = {
  student_create: "Student added", student_update: "Student edited",
  card_bind: "Card registered", card_revoke: "Card revoked",
  card_create: "Card added", card_update: "Card changed",
  enroll_bulk: "Students enrolled", slot_create: "Lecture scheduled",
  slot_update: "Lecture moved", slot_delete: "Lecture removed",
  device_add: "Reader added", device_update: "Reader changed",
  device_remove: "Reader removed", device_token_reveal: "Reader token viewed",
  device_token_rotate: "Reader token replaced",
  session_open: "Lecture opened", session_close: "Lecture closed",
  staff_add: "Staff added", staff_role: "Staff role changed",
  staff_remove: "Staff removed", staff_password: "Staff password reset",
};

export function AdminActions() {
  const { org } = useAuth();
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const { rows, count, page, setPage, loading, error } =
    useList("/api/audit/", { search });

  return (
    <>
      <div className="row filters">
        <input className="input" value={query} placeholder="Search actions, people or details"
               onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ErrorBox error={error} />
      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="actions" /> : rows.length === 0 ? (
          <Empty message="Nothing recorded yet." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{when(a.created_at, org?.timezone)}</td>
                    <td>{a.actor_name || "-"}</td>
                    <td>{ACTIONS[a.action] ?? a.action}</td>
                    <td className="muted" style={{ wordBreak: "break-word" }}>{a.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
    </>
  );
}
