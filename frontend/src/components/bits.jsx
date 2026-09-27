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

export function ErrorBox({ error }) {
  if (!error) return null;
  const msg = !error.response
    ? "Could not reach the server."
    : error.response.data?.detail || `Request failed (${error.response.status}).`;
  return <div className="alert alert-bad">{msg}</div>;
}
