import { useEffect, useState } from "react";
import api from "../lib/api";
import { useList } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox, errorText } from "../components/bits";
import Modal from "../components/Modal";
import { ago } from "./Cards";

function useVenues() {
  const [venues, setVenues] = useState([]);
  useEffect(() => {
    api.get("/api/venues/", { params: { page_size: 1000 } })
       .then(({ data }) => setVenues(data.results ?? data)).catch(() => {});
  }, []);
  return venues;
}

function DeviceForm({ device, onClose, onSaved }) {
  const editing = !!device;
  const venues = useVenues();
  const [form, setForm] = useState({
    name: device?.name ?? "", hardware_id: device?.hardware_id ?? "",
    venue: device?.venue ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const fieldErr = (k) => {
    const v = error?.response?.data?.[k];
    return v ? <small className="field-error">{Array.isArray(v) ? v.join(" ") : v}</small> : null;
  };
  const fieldKeys = ["name", "hardware_id", "venue"];
  const general = error && !fieldKeys.some((k) => error.response?.data?.[k]);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...form, venue: form.venue || null };
    // A reader registered before readers had IDs may have none yet; it
    // gets one the first time it checks in.
    if (editing && !body.hardware_id) delete body.hardware_id;
    try {
      const { data } = editing
        ? await api.patch(`/api/devices/${device.id}/`, body)
        : await api.post("/api/devices/", body);
      onSaved(data, editing);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={editing ? `Edit ${device.name}` : "Add reader"} onClose={onClose}>
      <form onSubmit={save} noValidate>
        {general && <div className="alert alert-bad">{errorText(error)}</div>}
        <div className="field">
          <label htmlFor="hw">Reader ID</label>
          <input id="hw" className="input mono" autoFocus={!editing} required
                 placeholder="A4:CF:12:34:56:78" autoComplete="off" spellCheck={false}
                 value={form.hardware_id} onChange={set("hardware_id")} />
          {fieldErr("hardware_id")}
          <small className="faint" style={{ display: "block", marginTop: 6 }}>
            Shown on the reader's screen for a few seconds when it powers on,
            and on its setup page. A reader can belong to only one account.
          </small>
        </div>
        <div className="form-2">
          <div className="field">
            <label htmlFor="dname">Name</label>
            <input id="dname" className="input" required maxLength={64}
                   placeholder="LT1 front door" value={form.name} onChange={set("name")} />
            {fieldErr("name")}
          </div>
          <div className="field">
            <label htmlFor="dvenue">Venue</label>
            <select id="dvenue" className="input" value={form.venue ?? ""}
                    onChange={set("venue")}>
              <option value="">Not placed yet</option>
              {venues.map((v) => <option key={v.id} value={v.id}>{v.code}</option>)}
            </select>
            {fieldErr("venue")}
          </div>
        </div>
        <p className="faint" style={{ fontSize: 13, marginTop: -4 }}>
          A reader takes attendance for whatever the timetable has in its venue.
        </p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-solid" disabled={busy || !form.name.trim()}>
            {busy ? "Saving..." : editing ? "Save" : "Add reader"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function TokenDialog({ device, onClose }) {
  const [token, setToken] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.post(`/api/devices/${device.id}/reveal_token/`)
       .then(({ data }) => setToken(data.token)).catch(setError);
  }, [device.id]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
    } catch { /* select and copy by hand */ }
  }

  return (
    <Modal title={`Token for ${device.name}`} onClose={onClose}>
      <ErrorBox error={error} />
      <p className="muted" style={{ marginTop: 0 }}>
        On the reader's setup page, paste this into <strong>Device token</strong> and
        set the backend address to <code>{api.defaults.baseURL}</code>.
        The token only works on this reader. Viewing it is recorded in the audit log.
      </p>
      {token ? (
        <div className="row">
          <input className="input mono" readOnly value={token}
                 onFocus={(e) => e.target.select()} />
          <button className="btn-solid" style={{ flex: "0 0 auto" }} onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      ) : !error && <Loading what="token" />}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button className="btn-ghost" onClick={onClose}>Done</button>
      </div>
    </Modal>
  );
}

export default function Devices() {
  const { rows, loading, error, reload } = useList("/api/devices/", { active: true });
  const [editing, setEditing] = useState(null);     // "new" | device
  const [showToken, setShowToken] = useState(null);
  const [flash, setFlash] = useState("");
  const [actionError, setActionError] = useState(null);

  function note(msg) {
    setFlash(msg);
    setTimeout(() => setFlash(""), 5000);
  }

  async function remove(d) {
    if (!window.confirm(
      `Remove ${d.name}? It stops working straight away and can then be added ` +
      `to another account. Its attendance history is kept.`)) return;
    setActionError(null);
    try {
      await api.delete(`/api/devices/${d.id}/`);
      note(`${d.name} removed.`);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  return (
    <>
      <PageHead title="Devices" subtitle="Card readers in your lecture halls">
        <button className="btn-solid" onClick={() => setEditing("new")}>Add reader</button>
      </PageHead>

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || actionError} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="readers" /> : rows.length === 0 ? (
          <Empty message="No readers yet."
                 hint="Power a reader on, note the Reader ID it shows, and add it here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Reader</th><th>Venue</th><th>Status</th><th>Last seen</th>
                    <th>Waiting to upload</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <strong>{d.name}</strong>
                      <small className="faint mono" style={{ display: "block" }}>
                        {d.hardware_id || "ID set on first check-in"}
                      </small>
                    </td>
                    <td className="muted">{d.venue_code || <span className="pill pill-warn">not placed</span>}</td>
                    <td>{d.online ? <span className="pill pill-ok">online</span>
                                  : <span className="pill pill-bad">offline</span>}</td>
                    <td className="muted">{d.last_seen ? ago(d.last_seen) : "never"}</td>
                    <td className="muted">{d.queue_depth} tap{d.queue_depth === 1 ? "" : "s"}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn-ghost btn-sm" onClick={() => setShowToken(d)}>Token</button>{" "}
                      <button className="btn-ghost btn-sm" onClick={() => setEditing(d)}>Edit</button>{" "}
                      <button className="btn-ghost btn-sm" onClick={() => remove(d)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <DeviceForm device={editing === "new" ? null : editing}
                    onClose={() => setEditing(null)}
                    onSaved={(d, wasEdit) => {
                      setEditing(null);
                      reload();
                      if (wasEdit) note(`${d.name} updated.`);
                      else setShowToken(d);
                    }} />
      )}
      {showToken && <TokenDialog device={showToken} onClose={() => setShowToken(null)} />}
    </>
  );
}
