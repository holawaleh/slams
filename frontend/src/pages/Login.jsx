import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import PasswordInput from "../components/PasswordInput";
import ThemeToggle from "../components/ThemeToggle";
import "./Login.css";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const me = await login(username.trim(), password);
      if (!me.current_org && !me.user.is_platform_admin) {
        setError("This account is not a member of any institution. " +
                 "Create an account, or ask an admin to invite you.");
        return;
      }
      navigate("/dashboard");
    } catch (err) {
      // Neon wakes from idle slowly, so a timeout here is not the same
      // as bad credentials and should not say so.
      if (err.code === "ECONNABORTED" || !err.response) {
        setError("Could not reach the server. Check it is running.");
      } else if (err.response.status === 401) {
        setError("Wrong username or password.");
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
        <div className="auth-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2.2" strokeLinecap="round">
            <polyline points="4 13 9 18 20 6" />
          </svg>
          <span>SLAMS</span>
        </div>

        <h2 className="center">Admin Login</h2>
        <p className="muted center auth-sub">
          Enter your credentials to access the dashboard
        </p>

        {error && <div className="alert alert-bad">{error}</div>}

        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="u">Username</label>
            <div className="input-group">
              <span className="input-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </span>
              <input id="u" value={username} autoComplete="username"
                     autoCapitalize="off"
                     onChange={(e) => setUsername(e.target.value)} required />
            </div>
          </div>

          <div className="field">
            <label htmlFor="p">Password</label>
            <PasswordInput id="p" value={password} required
                           autoComplete="current-password"
                           onChange={(e) => setPassword(e.target.value)} />
          </div>

          <button type="submit" className="btn-solid btn-full" disabled={busy}>
            {busy ? "Signing in..." : (
              <>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                  <polyline points="10 17 15 12 10 7" />
                  <line x1="15" y1="12" x2="3" y2="12" />
                </svg>
                Login
              </>
            )}
          </button>
        </form>

        <div className="center auth-links">
          <Link to="/">&larr; Back to Home</Link>
        </div>
        <div className="center auth-links faint">
          New institution? <Link to="/register">Create an account</Link>
        </div>
      </div>
    </div>
  );
}
