import { useEffect, useRef, useState } from "react";
import api from "../lib/api";

const WAIT_SECONDS = 90;
const POLL_MS = 2000;

// Waits for the next card tapped on a chosen reader and hands back its
// number. The reader uploads every tap within a few seconds, so this only
// has to watch for it; nothing is sent to the reader.
export default function CardCapture({ onCaptured, onCancel, studentId }) {
  const [readers, setReaders] = useState(null);
  const [reader, setReader] = useState(() => {
    try { return localStorage.getItem("captureReader") || ""; } catch { return ""; }
  });
  const [since, setSince] = useState(null);
  const [left, setLeft] = useState(WAIT_SECONDS);
  const [result, setResult] = useState(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef(null);

  useEffect(() => {
    api.get("/api/devices/", { params: { active: true } })
       .then(({ data }) => {
         const list = data.results ?? data;
         setReaders(list);
         if (list.length && !list.some((d) => String(d.id) === reader))
           setReader(String(list[0].id));
       })
       .catch(() => setReaders([]));
    // Only on open; the chosen reader is remembered separately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function start() {
    try { localStorage.setItem("captureReader", reader); } catch { /* optional */ }
    setResult(null);
    setError("");
    setLeft(WAIT_SECONDS);
    setSince(new Date(Date.now() - 1000).toISOString());
  }

  useEffect(() => {
    if (!since) return undefined;
    const began = Date.now();
    const tick = async () => {
      const remaining = WAIT_SECONDS - Math.round((Date.now() - began) / 1000);
      setLeft(remaining);
      if (remaining <= 0) { setSince(null); setError("No card was tapped. Try again."); return; }
      try {
        const { data } = await api.get("/api/cards/capture/", {
          params: { device: reader, since } });
        setOffline(!data.device_online);
        if (data.uid) { setResult(data); setSince(null); return; }
      } catch {
        /* a dropped poll is retried on the next tick */
      }
      timer.current = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => clearTimeout(timer.current);
  }, [since, reader]);

  const waiting = !!since;
  const own = result?.state === "taken" && studentId && result.student_id === studentId;
  const usable = result && ["new", "unassigned", "revoked"].includes(result.state);

  if (readers && readers.length === 0) {
    return (
      <div className="capture">
        <p style={{ margin: 0 }}>No reader is set up yet. Add one on the Devices page,
          or type the card number instead.</p>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button type="button" className="btn-ghost btn-sm" onClick={onCancel}>Close</button>
        </div>
      </div>
    );
  }

  return (
    <div className="capture">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select className="input" style={{ flex: "1 1 180px" }} value={reader}
                disabled={waiting} onChange={(e) => setReader(e.target.value)}>
          {(readers ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}{d.venue_code ? ` · ${d.venue_code}` : ""}{d.online ? "" : " (offline)"}
            </option>
          ))}
        </select>
        {waiting ? (
          <button type="button" className="btn-ghost btn-sm" onClick={() => setSince(null)}>
            Stop
          </button>
        ) : (
          <button type="button" className="btn-solid btn-sm" disabled={!reader} onClick={start}>
            {result || error ? "Scan again" : "Start scanning"}
          </button>
        )}
        <button type="button" className="btn-ghost btn-sm" onClick={onCancel}>Close</button>
      </div>

      {waiting && (
        <p className="capture-wait">
          <span className="pulse" aria-hidden="true" />
          Tap the card on the reader now… {left}s
          {offline && <small className="field-error">This reader has not been in touch for a few minutes, so the tap may not arrive.</small>}
        </p>
      )}
      {error && <small className="field-error">{error}</small>}
      {result && (
        <div className={"alert " + (usable || own ? "alert-ok" : "alert-bad")} style={{ marginTop: 12, marginBottom: 0 }}>
          Card <code>{result.uid}</code>{" "}
          {result.state === "new" && "is new."}
          {result.state === "unassigned" && "is on record but not assigned to anyone."}
          {result.state === "revoked" && "was revoked earlier; it will be reactivated."}
          {own && "is already this student's card."}
          {result.state === "taken" && !own && `is already registered to ${result.student}.`}
          {result.state === "admin" && "is an admin card."}
          {usable && (
            <button type="button" className="btn-solid btn-sm" style={{ marginLeft: 10 }}
                    onClick={() => onCaptured(result.uid)}>Use this card</button>
          )}
        </div>
      )}
    </div>
  );
}
