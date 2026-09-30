import { useEffect, useState } from "react";
import api from "../lib/api";
import { useList } from "../lib/useList";
import { PageHead, Loading, Empty, ErrorBox, errorText } from "../components/bits";
import Modal from "../components/Modal";
import { ago } from "./Cards";

// Reader IDs are MAC addresses. The field only accepts hex digits and
// places the colons itself: typing a4cf12345678 shows A4:CF:12:34:56:78.
export function maskMac(value) {
  const hex = value.toUpperCase().replace(/[^0-9A-F]/g, "").slice(0, 12);
  return hex.match(/.{1,2}/g)?.join(":") ?? "";
}

// Pairing codes are six digits, shown on the reader as "482 913".
function maskCode(value) {
  const d = value.replace(/\D/g, "").slice(0, 6);
  return d.length > 3 ? `${d.slice(0, 3)} ${d.slice(3)}` : d;
}

function useVenues() {
  const [venues, setVenues] = useState([]);
  useEffect(() => {
    api.get("/api/venues/", { params: { page_size: 1000 } })
       .then(({ data }) => setVenues(data.results ?? data)).catch(() => {});
  }, []);
  return venues;
}

function fieldErr(error, k) {
  const v = error?.response?.data?.[k];
  return v ? <small className="field-error">{Array.isArray(v) ? v.join(" ") : v}</small> : null;
}

function secondsAgo(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso)) / 1000));
  return s < 5 ? "just now" : `${s}s ago`;
}

// Step 1: look for readers announcing themselves on this network.
// Step 2: name the chosen one and type the code from its screen.
// Step 3: wait for the reader to collect its token and check in.
function AddReader({ onClose, onAdded }) {
  const venues = useVenues();
  const [step, setStep] = useState("search");       // search | pair | done
  const [found, setFound] = useState(null);
  const [manual, setManual] = useState(false);
  const [picked, setPicked] = useState(null);       // hardware id
  const [form, setForm] = useState({ name: "", venue: "", code: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [device, setDevice] = useState(null);

  // Searching: ask every 3 seconds while the list is on screen.
  useEffect(() => {
    if (step !== "search") return undefined;
    let stop = false;
    let timer;
    const look = () => api.get("/api/devices/discover/")
      .then(({ data }) => { if (!stop) setFound(data); })
      .catch(() => {})
      .finally(() => { if (!stop) timer = setTimeout(look, 3000); });
    look();
    return () => { stop = true; clearTimeout(timer); };
  }, [step]);

  // Added: watch for the reader's first check-in with its new token.
  useEffect(() => {
    if (step !== "done" || !device || device.last_seen) return undefined;
    const timer = setInterval(() => {
      api.get(`/api/devices/${device.id}/`).then(({ data }) => {
        if (data.last_seen) setDevice(data);
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [step, device]);

  function choose(hw) {
    setPicked(hw);
    setForm({ name: "", venue: venues[0]?.id ?? "", code: "" });
    setError(null);
    setStep("pair");
  }

  async function pair(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post("/api/devices/claim/", {
        hardware_id: picked, code: form.code.replace(/\s/g, ""),
        name: form.name.trim(), venue: form.venue || null,
      });
      setDevice(data);
      setStep("done");
      onAdded();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    const connected = !!device?.last_seen;
    return (
      <Modal title="Reader added" onClose={onClose}>
        <p style={{ marginTop: 0 }}>
          <strong>{device.name}</strong> ({device.hardware_id}) now belongs to your account
          and cannot be added to any other until you remove it.
        </p>
        <p className={connected ? "" : "muted"} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {connected ? <span className="pill pill-ok">connected</span>
                     : <span className="pulse" aria-hidden="true" />}
          {connected ? "The reader has checked in and is ready."
                     : "Waiting for the reader to pick up its settings. This takes a few seconds; its screen will say “Reader added”."}
        </p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn-solid" onClick={onClose}>Done</button>
        </div>
      </Modal>
    );
  }

  if (step === "pair") {
    const general = error && !["code", "hardware_id", "name", "venue"].some((k) => error.response?.data?.[k]);
    return (
      <Modal title="Add this reader" onClose={onClose}>
        <form onSubmit={pair} noValidate>
          <p className="muted" style={{ marginTop: 0 }}>
            Reader <code className="mono">{picked}</code>
          </p>
          {general && <div className="alert alert-bad">{errorText(error)}</div>}
          {fieldErr(error, "hardware_id")}
          <div className="field">
            <label htmlFor="pcode">Pairing code</label>
            <input id="pcode" className="input mono code-input" autoFocus inputMode="numeric"
                   autoComplete="one-time-code" placeholder="000 000"
                   value={form.code} onChange={(e) => setForm({ ...form, code: maskCode(e.target.value) })} />
            {fieldErr(error, "code") || (
              <small className="faint" style={{ display: "block", marginTop: 6 }}>
                The 6 digits on the reader's screen, under &ldquo;Pair code&rdquo;.
              </small>
            )}
          </div>
          <div className="form-2">
            <div className="field">
              <label htmlFor="pname">Name</label>
              <input id="pname" className="input" maxLength={64} placeholder="LT1 front door"
                     value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              {fieldErr(error, "name")}
            </div>
            <div className="field">
              <label htmlFor="pvenue">Venue</label>
              <select id="pvenue" className="input" value={form.venue ?? ""}
                      onChange={(e) => setForm({ ...form, venue: e.target.value })}>
                <option value="">Not placed yet</option>
                {venues.map((v) => <option key={v.id} value={v.id}>{v.code}</option>)}
              </select>
              {fieldErr(error, "venue")}
            </div>
          </div>
          <div className="spread">
            <button type="button" className="btn-ghost" onClick={() => { setStep("search"); setError(null); }}>
              Back
            </button>
            <button className="btn-solid"
                    disabled={busy || form.code.replace(/\s/g, "").length !== 6 || !form.name.trim()}>
              {busy ? "Adding..." : "Add reader"}
            </button>
          </div>
        </form>
      </Modal>
    );
  }

  return (
    <Modal title="Search for readers" onClose={onClose} width={560}>
      <p className="muted" style={{ marginTop: 0 }}>
        Power the reader on and connect it to WiFi. Readers that are not yet in
        any account and are on the same network as this computer appear here.
      </p>
      <div className="pick-list">
        {found === null ? <Loading what="readers" /> : found.length === 0 ? (
          <p className="capture-wait" style={{ padding: 14, margin: 0 }}>
            <span className="pulse" aria-hidden="true" /> Searching…
          </p>
        ) : found.map((r) => (
          <button key={r.hardware_id} type="button" className="pick-row reader-row"
                  onClick={() => choose(r.hardware_id)}>
            <span className="grow">
              <code className="mono">{r.hardware_id}</code>
              <small className="faint" style={{ display: "block" }}>
                {r.local_ip && `IP ${r.local_ip} · `}firmware {r.firmware || "?"} · seen {secondsAgo(r.last_seen)}
              </small>
            </span>
            <span className="btn-solid btn-sm" aria-hidden="true">Select</span>
          </button>
        ))}
      </div>

      {manual ? (
        <form className="row" style={{ marginTop: 14 }}
              onSubmit={(e) => { e.preventDefault(); if (picked?.length === 17) choose(picked); }}>
          <input className="input mono" autoFocus placeholder="__:__:__:__:__:__"
                 value={picked ?? ""} onChange={(e) => setPicked(maskMac(e.target.value))} />
          <button className="btn-solid" style={{ flex: "0 0 auto" }}
                  disabled={picked?.length !== 17}>Next</button>
        </form>
      ) : (
        <p className="faint" style={{ fontSize: 13, marginBottom: 0 }}>
          Not listed? A reader on a different network (for example if this computer is
          on mobile data) will not show up.{" "}
          <button type="button" className="linkish" onClick={() => { setManual(true); setPicked(""); }}>
            Enter its reader ID instead
          </button>
        </p>
      )}

      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button className="btn-ghost" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

// For a reader already in this account that lost its token: it goes
// back to showing a pairing code, and the code reconnects this same entry.
function RepairReader({ device, onClose, onDone }) {
  const [phase, setPhase] = useState("opening");      // opening | code | done
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [minutes, setMinutes] = useState(15);

  useEffect(() => {
    api.post(`/api/devices/${device.id}/repair/`)
       .then(({ data }) => { setMinutes(data.minutes); setPhase("code"); })
       .catch((err) => { setError(err); setPhase("code"); });
  }, [device.id]);

  async function confirm(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/devices/${device.id}/repair_confirm/`,
                     { code: code.replace(/\s/g, "") });
      setPhase("done");
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Re-pair ${device.name}`} onClose={onClose}>
      {phase === "done" ? (
        <>
          <p style={{ marginTop: 0 }}>
            Reconnected. The reader picks up its new settings within a few seconds
            and its screen says &ldquo;Reader added&rdquo;. Its name, venue and history are unchanged.
          </p>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn-solid" onClick={onClose}>Done</button>
          </div>
        </>
      ) : phase === "opening" ? <Loading what="re-pairing" /> : (
        <form onSubmit={confirm} noValidate>
          <p className="muted" style={{ marginTop: 0 }}>
            Use this when the reader has lost its settings and shows
            &ldquo;Re-pair in app&rdquo; or a pairing code. Within a few seconds it shows a
            6-digit code; type it below. This stays open for {minutes} minutes.
          </p>
          {error && !error.response?.data?.code && <div className="alert alert-bad">{errorText(error)}</div>}
          <div className="field">
            <label htmlFor="rcode">Pairing code</label>
            <input id="rcode" className="input mono code-input" autoFocus inputMode="numeric"
                   autoComplete="one-time-code" placeholder="000 000"
                   value={code} onChange={(e) => setCode(maskCode(e.target.value))} />
            {fieldErr(error, "code")}
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-solid" disabled={busy || code.replace(/\s/g, "").length !== 6}>
              {busy ? "Reconnecting..." : "Reconnect"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function EditReader({ device, onClose, onSaved }) {
  const venues = useVenues();
  const [form, setForm] = useState({ name: device.name, venue: device.venue ?? "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.patch(`/api/devices/${device.id}/`,
                                       { name: form.name, venue: form.venue || null });
      onSaved(data);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={`Edit ${device.name}`} onClose={onClose}>
      <form onSubmit={save} noValidate>
        {error && !error.response?.data?.name && <div className="alert alert-bad">{errorText(error)}</div>}
        <p className="muted" style={{ marginTop: 0 }}>
          Reader <code className="mono">{device.hardware_id || "ID set on first check-in"}</code>
        </p>
        <div className="form-2">
          <div className="field">
            <label htmlFor="dname">Name</label>
            <input id="dname" className="input" maxLength={64} value={form.name}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
            {fieldErr(error, "name")}
          </div>
          <div className="field">
            <label htmlFor="dvenue">Venue</label>
            <select id="dvenue" className="input" value={form.venue ?? ""}
                    onChange={(e) => setForm({ ...form, venue: e.target.value })}>
              <option value="">Not placed yet</option>
              {venues.map((v) => <option key={v.id} value={v.id}>{v.code}</option>)}
            </select>
          </div>
        </div>
        <p className="faint" style={{ fontSize: 13, marginTop: -4 }}>
          A reader takes attendance for whatever the timetable has in its venue.
        </p>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-solid" disabled={busy || !form.name.trim()}>
            {busy ? "Saving..." : "Save"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Devices({ embedded = false }) {
  const { rows, loading, error, reload } = useList("/api/devices/", { active: true });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const [repairing, setRepairing] = useState(null);
  const [flash, setFlash] = useState("");
  const [actionError, setActionError] = useState(null);

  function note(msg) {
    setFlash(msg);
    setTimeout(() => setFlash(""), 5000);
  }

  async function remove(d) {
    if (!window.confirm(
      `Remove ${d.name}? It stops working straight away, shows a new pairing code, ` +
      `and can then be added to another account. Its attendance history is kept.`)) return;
    setActionError(null);
    try {
      await api.delete(`/api/devices/${d.id}/`);
      note(`${d.name} removed.`);
      reload();
    } catch (err) {
      setActionError(err);
    }
  }

  const addButton = (
    <button className="btn-solid" onClick={() => setAdding(true)}>Search for readers</button>
  );

  return (
    <>
      {embedded ? (
        <div className="spread filters">
          <p className="muted" style={{ margin: 0 }}>Card readers in your lecture halls.</p>
          {addButton}
        </div>
      ) : (
        <PageHead title="Devices" subtitle="Card readers in your lecture halls">{addButton}</PageHead>
      )}

      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || actionError} />

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Loading what="readers" /> : rows.length === 0 ? (
          <Empty message="No readers yet."
                 hint="Power a reader on, connect it to WiFi, then press Search for readers." />
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
                      <button className="btn-ghost btn-sm" onClick={() => setEditing(d)}>Edit</button>{" "}
                      {d.hardware_id && (
                        <><button className="btn-ghost btn-sm" onClick={() => setRepairing(d)}
                                  title="For a reader that lost its settings">Re-pair</button>{" "}</>
                      )}
                      <button className="btn-ghost btn-sm" onClick={() => remove(d)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {adding && <AddReader onClose={() => { setAdding(false); reload(); }} onAdded={reload} />}
      {repairing && (
        <RepairReader device={repairing} onClose={() => { setRepairing(null); reload(); }}
                      onDone={reload} />
      )}
      {editing && (
        <EditReader device={editing} onClose={() => setEditing(null)}
                    onSaved={(d) => { setEditing(null); reload(); note(`${d.name} updated.`); }} />
      )}
    </>
  );
}
