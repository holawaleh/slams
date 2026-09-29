export function PageHead({ title, subtitle, children }) {
  return (
    <div className="spread" style={{ marginBottom: 22, flexWrap: "wrap" }}>
      <div>
        <h2>{title}</h2>
        {subtitle && (
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>{subtitle}</p>
        )}
      </div>
      <div className="row">{children}</div>
    </div>
  );
}

export function Loading({ what = "data" }) {
  return (
    <div className="muted center" style={{ padding: 48 }}>
      Loading {what}...
    </div>
  );
}

export function Empty({ message, hint }) {
  return (
    <div className="center" style={{ padding: 48 }}>
      <p style={{ margin: 0, fontWeight: 500 }}>{message}</p>
      {hint && (
        <p className="faint" style={{ marginTop: 6, fontSize: 14 }}>{hint}</p>
      )}
    </div>
  );
}

export function errorText(error) {
  if (!error) return "";
  if (!error.response) return "Could not reach the server.";
  const data = error.response.data;
  if (data?.detail) return data.detail;
  // DRF validation errors arrive as { field: ["message", ...] }.
  if (data && typeof data === "object") {
    const parts = Object.entries(data).map(([k, v]) => {
      const msg = Array.isArray(v) ? v.join(" ") : String(v);
      return k === "non_field_errors" ? msg : `${k.replace(/_/g, " ")}: ${msg}`;
    });
    if (parts.length) return parts.join(" ");
  }
  return `Request failed (${error.response.status}).`;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert alert-bad">{errorText(error)}</div>;
}
