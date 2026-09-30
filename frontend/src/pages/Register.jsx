import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { PASSWORD_RULES, passwordOk, missingRules, MIN_LENGTH } from "../lib/password";
import PasswordInput from "../components/PasswordInput";
import ThemeToggle from "../components/ThemeToggle";
import "./Login.css";

const TEXT_FIELDS = [
  { name: "org_name",   label: "School",           autoComplete: "organization",
    placeholder: "e.g. Computer Science" },
  { name: "address",    label: "Address",          autoComplete: "street-address",
    placeholder: "Street, town, state" },
  { name: "username",   label: "Username",         autoComplete: "username",
    placeholder: "letters, numbers, . _ -",
    hint: "You will use this to log in." },
  { name: "email",      label: "Email",            autoComplete: "email",
    type: "email" },
];

const EMPTY = { org_name: "", address: "", username: "", email: "",
                password: "", confirm: "" };

const EMAIL_RX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function Register() {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const set = (name) => (e) => setForm({ ...form, [name]: e.target.value });
  const mismatch = form.confirm.length > 0 && form.confirm !== form.password;

  async function submit(e) {
    e.preventDefault();
    setError("");
    const local = {};
    for (const f of TEXT_FIELDS) {
      if (!form[f.name].trim()) local[f.name] = "Required.";
    }
    if (form.email.trim() && !EMAIL_RX.test(form.email.trim()))
      local.email = "Enter a valid email address.";
    if (!passwordOk(form.password))
      local.password = `Still needed: ${missingRules(form.password).join(", ")}.`;
    if (form.confirm !== form.password)
      local.confirm = "Passwords do not match.";
    setErrors(local);
    if (Object.keys(local).length) return;

    setBusy(true);
    try {
      const { confirm: _confirm, ...payload } = form;
      payload.username = payload.username.trim().toLowerCase();
      payload.org_name = payload.org_name.trim();
      payload.address = payload.address.trim();
      payload.email = payload.email.trim().toLowerCase();
      await register(payload);
      navigate("/dashboard");
    } catch (err) {
      if (err.code === "ECONNABORTED" || !err.response) {
        setError("Could not reach the server. Check it is running.");
      } else if (err.response.status === 429) {
        setError("Too many sign-ups from this network. Try again later.");
      } else if (err.response.status === 400 && err.response.data) {
        const out = {};
        for (const [k, v] of Object.entries(err.response.data)) {
          out[k] = Array.isArray(v) ? v.join(" ") : String(v);
        }
        setErrors(out);
        if (out.non_field_errors || out.detail)
          setError(out.non_field_errors || out.detail);
      } else {
        setError(err.response.data?.detail || "Something went wrong.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <ThemeToggle floating />
      <div className="auth-card card">
        <h2 className="center">Create an account</h2>
        <p className="muted center auth-sub">
          Register your Department
        </p>

        {error && <div className="alert alert-bad">{error}</div>}

        <form onSubmit={submit} noValidate>
          {TEXT_FIELDS.map((f) => (
            <div className="field" key={f.name}>
              <label htmlFor={f.name}>{f.label}</label>
              <input id={f.name} className="input" type={f.type || "text"}
                     value={form[f.name]} autoComplete={f.autoComplete}
                     placeholder={f.placeholder}
                     autoCapitalize={f.name === "username" ? "off" : undefined}
                     aria-invalid={!!errors[f.name] || undefined}
                     onChange={set(f.name)} />
              {errors[f.name] ? <small className="field-error">{errors[f.name]}</small>
                : f.hint && <small className="faint" style={{ display: "block", marginTop: 6 }}>{f.hint}</small>}
            </div>
          ))}

          <div className="field">
            <label htmlFor="password">Password</label>
            <PasswordInput id="password" value={form.password}
                           autoComplete="new-password"
                           invalid={!!errors.password}
                           onChange={set("password")} />
            <ul className="pw-rules" aria-live="polite">
              {PASSWORD_RULES.map((r, i) => {
                const met = r.test(form.password);
                // Once typing has started, an unmet rule is a failure, not
                // a neutral bullet - otherwise it is easy to miss the one
                // rule that is holding the form up.
                const failed = !met && form.password.length > 0;
                return (
                  <li key={r.label} className={met ? "met" : failed ? "unmet" : ""}>
                    <span aria-hidden="true">{met ? "✓" : failed ? "✗" : "•"}</span>
                    {r.label}
                    {i === 0 && form.password.length > 0 && (
                      <span className="pw-count">({form.password.length}/{MIN_LENGTH})</span>
                    )}
                  </li>
                );
              })}
            </ul>
            {errors.password && <small className="field-error">{errors.password}</small>}
          </div>

          <div className="field">
            <label htmlFor="confirm">Re-type password</label>
            <PasswordInput id="confirm" value={form.confirm}
                           autoComplete="new-password"
                           invalid={mismatch || !!errors.confirm}
                           onChange={set("confirm")} />
            {mismatch ? (
              <small className="field-error">Passwords do not match.</small>
            ) : form.confirm && (
              <small className="field-error" style={{ color: "var(--ok)" }}>
                Passwords match.
              </small>
            )}
          </div>

          <button type="submit" className="btn-solid btn-full" disabled={busy}>
            {busy ? "Creating..." : "Create account"}
          </button>
        </form>

        <div className="center auth-links faint">
          Already registered? <Link to="/login">Log in with your username</Link>
        </div>
      </div>
    </div>
  );
}
