import { useEffect, useState } from "react";
import api from "../lib/api";
import { useList, useDebounced } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";
import Pager from "../components/Pager";

export function ago(iso) {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
  if (days < 1) {
    const mins = Math.round((Date.now() - new Date(iso)) / 60000);
    return mins < 60 ? `${Math.max(mins, 1)} min ago` : `${Math.round(mins / 60)} h ago`;
  }
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString();
}

// Each tile is also a filter: click "Never used" to list those cards.
const TILES = [
  { key: "active",      label: "Active",        filter: { status: "active" } },
  { key: "regular",     label: "In regular use", filter: { status: "active", usage: "regular" }, tone: "ok" },
  { key: "rarely_used", label: "Rarely used",   filter: { status: "active", usage: "rare" }, tone: "warn" },
  { key: "never_used",  label: "Unused since registration", filter: { status: "active", usage: "never" }, tone: "warn" },
  { key: "unassigned",  label: "Not assigned",  filter: { status: "unassigned" } },
  { key: "revoked",     label: "Revoked",       filter: { status: "revoked" }, tone: "bad" },
];

function usageOf(c, threshold) {
  if (!c.active) return <span className="pill pill-bad">revoked</span>;
  if (!c.uses_total) return <span className="pill pill-warn">never used</span>;
  if (c.uses_30d < threshold) return <span className="pill pill-warn">rarely used</span>;
  return <span className="pill pill-ok">regular</span>;
}

export default function Cards() {
  const [summary, setSummary] = useState(null);
  const [filter, setFilter] = useState({ status: "active" });
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const { rows, count, page, setPage, loading, error, reload } =
    useList("/api/cards/", { ...filter, search });
  const [flash, setFlash] = useState("");
  const [actionError, setActionError] = useState(null);

  const loadSummary = () =>
    api.get("/api/cards/summary/").then(({ data }) => setSummary(data)).catch(() => {});
  useEffect(() => { loadSummary(); }, []);

  const same = (f) => JSON.stringify(f) === JSON.stringify(filter);

  async function setActive(card, active) {
    const who = card.student_name || card.holder_name || "no one";
    if (!active && !window.confirm(
      `Revoke card ${card.uid} (${who})? It stops working on every reader at the next sync.`)) return;
    setActionError(null);
    try {
      if (active) await api.patch(`/api/cards/${card.id}/`, { active: true });
      else await api.delete(`/api/cards/${card.id}/`);
      setFlash(`Card ${card.uid} ${active ? "restored" : "revoked"}.`);
      setTimeout(() => setFlash(""), 4000);
      reload();
      loadSummary();
    } catch (err) {
      setActionError(err);
    }
  }

  const threshold = summary?.rare_threshold ?? 3;

  return (
    <>
      <PageHead title="Cards" subtitle={summary ? `${summary.total} on record` : null} />

      <div className="tiles">
        {TILES.map((t) => (
          <button key={t.key} type="button"
                  className={"tile" + (same(t.filter) ? " on" : "")}
                  onClick={() => setFilter(t.filter)}>
            <span className="tile-label">{t.label}</span>
            <span className="tile-value" style={t.tone && summary?.[t.key] ? { color: `var(--${t.tone})` } : null}>
              {summary ? summary[t.key] : "-"}
            </span>
          </button>
        ))}
      </div>
      <p className="faint" style={{ fontSize: 13, margin: "-6px 0 16px" }}>
        Rarely used: tapped fewer than {threshold} times in the last 30 days.
        Unused: never tapped since it was registered.
      </p>

      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "2 1 240px" }}
               placeholder="Search card number, student name or matric no"
               value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="btn-ghost" onClick={() => setFilter({})}
                disabled={same({})}>Show all</button>
      </div>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || actionError} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="cards" /> : rows.length === 0 ? (
          <Empty message="No card matches." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Card</th><th>Belongs to</th><th>Usage</th>
                  <th>Last used</th><th>Last 30 days</th><th>Registered</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td><code className="mono">{c.uid}</code></td>
                    <td>
                      {c.is_admin ? <><span className="pill">admin</span> {c.holder_name}</>
                        : c.student_name ? <>{c.student_name}
                            {c.matric_no && <small className="faint" style={{ display: "block" }}>{c.matric_no}</small>}</>
                        : <span className="faint">not assigned</span>}
                    </td>
                    <td>{usageOf(c, threshold)}</td>
                    <td className="muted">{ago(c.last_used)}</td>
                    <td className="muted">{c.uses_30d} tap{c.uses_30d === 1 ? "" : "s"}</td>
                    <td className="muted">
                      {new Date(c.issued_at).toLocaleDateString()}
                      {!c.active && c.revoked_at && (
                        <small className="faint" style={{ display: "block" }}>
                          revoked {new Date(c.revoked_at).toLocaleDateString()}
                        </small>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {c.active ? (
                        <button className="btn-ghost btn-sm" onClick={() => setActive(c, false)}>Revoke</button>
                      ) : (
                        <button className="btn-ghost btn-sm" onClick={() => setActive(c, true)}>Restore</button>
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
    </>
  );
}
