import { useEffect, useState } from "react";
import api from "../lib/api";
import { useList, useDebounced } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";
import Modal from "../components/Modal";
import Pager from "../components/Pager";

function when(iso) {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString();
}

function BindDialog({ uid, onClose, onDone }) {
  const [query, setQuery] = useState("");
  const search = useDebounced(query);
  const [students, setStudents] = useState([]);
  const [chosen, setChosen] = useState(null);
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (search.length < 2) { setStudents([]); return; }
    api.get("/api/students/", { params: { search, page_size: 8 } })
       .then(({ data }) => setStudents(data.results ?? data))
       .catch(() => setStudents([]));
  }, [search]);

  async function bind() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/cards/bind/", {
        uid, student_id: chosen.id, replace,
      });
      onDone();
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  return (
    <Modal title="Register this card" onClose={onClose}>
      <p className="muted" style={{ marginTop: 0 }}>
        Card <code style={{ color: "var(--accent)" }}>{uid}</code> was seen by a
        reader but is not assigned to anyone.
      </p>

      <ErrorBox error={error} />

      <div className="field">
        <label htmlFor="q">Find the student</label>
        <input id="q" className="input" value={query} autoFocus
               placeholder="Matric number or surname"
               onChange={(e) => { setQuery(e.target.value); setChosen(null); }} />
      </div>

      {chosen ? (
        <div className="card" style={{ background: "var(--accent-ghost)",
                                       borderColor: "var(--accent)",
                                       marginBottom: 16 }}>
          <div className="spread">
            <div>
              <strong>{chosen.full_name}</strong>
              <div className="faint" style={{ fontSize: 13 }}>
                {chosen.matric_no}
                {chosen.cards?.filter((c) => c.active).length > 0 &&
                  " - already holds a card"}
              </div>
            </div>
            <button className="btn-ghost" onClick={() => setChosen(null)}>
              Change
            </button>
          </div>
        </div>
      ) : (
        query.length >= 2 && (
          <div style={{ maxHeight: 220, overflowY: "auto", marginBottom: 16 }}>
            {students.length === 0 ? (
              <p className="faint" style={{ fontSize: 14 }}>No match.</p>
            ) : (
              students.map((s) => (
                <button key={s.id} className="menu-item"
                        onClick={() => setChosen(s)}>
                  <span>
                    {s.full_name}
                    <small className="faint" style={{ display: "block" }}>
                      {s.matric_no}
                    </small>
                  </span>
                  {s.cards?.some((c) => c.active) && (
                    <span className="pill pill-warn">has card</span>
                  )}
                </button>
              ))
            )}
          </div>
        )
      )}

      {chosen?.cards?.some((c) => c.active) && (
        <label className="row" style={{ marginBottom: 16, fontWeight: 400,
                                        fontSize: 14 }}>
          <input type="checkbox" checked={replace} style={{ flex: "0 0 auto" }}
                 onChange={(e) => setReplace(e.target.checked)} />
          Revoke their existing card (use for a lost or replaced card)
        </label>
      )}

      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-solid" disabled={!chosen || busy} onClick={bind}>
          {busy ? "Saving..." : "Register card"}
        </button>
      </div>
    </Modal>
  );
}

export default function UnknownCards() {
  const { rows, count, page, setPage, loading, error, reload } =
    useList("/api/taps/unregistered/");
  const [binding, setBinding] = useState(null);
  const [flash, setFlash] = useState("");

  return (
    <>
      <PageHead
        title="New cards"
        subtitle="Cards presented to a reader that are not registered yet">
        <button className="btn-ghost" onClick={reload}>Refresh</button>
      </PageHead>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <Loading what="cards" />
        ) : rows.length === 0 ? (
          <Empty message="Nothing waiting."
                 hint="Cards tapped on a reader that are not yet assigned appear here." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Card number</th>
                <th>Times seen</th>
                <th>Reader</th>
                <th>Last seen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.uid}>
                  <td><code style={{ color: "var(--accent)" }}>{r.uid}</code></td>
                  <td>{r.times_seen}</td>
                  <td className="muted">{r.last_device || "-"}</td>
                  <td className="muted">{when(r.last_seen)}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn-solid"
                            style={{ padding: "6px 14px", fontSize: 13 }}
                            onClick={() => setBinding(r.uid)}>
                      Register
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Pager page={page} setPage={setPage} count={count} />

      {binding && (
        <BindDialog
          uid={binding}
          onClose={() => setBinding(null)}
          onDone={() => {
            setFlash(`Card ${binding} registered.`);
            setBinding(null);
            reload();
            setTimeout(() => setFlash(""), 4000);
          }}
        />
      )}
    </>
  );
}
