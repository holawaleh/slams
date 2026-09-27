import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import "./Login.css";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
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
            <div className="input-group">
              <span className="input-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              </span>
              <input id="p" type={show ? "text" : "password"} value={password}
                     autoComplete="current-password"
                     onChange={(e) => setPassword(e.target.value)} required />
              <button type="button" className="reveal"
                      onClick={() => setShow(!show)}
                      aria-label={show ? "Hide password" : "Show password"}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
                  <circle cx="12" cy="12" r="3" />
                  {show && <line x1="3" y1="21" x2="21" y2="3" />}
                </svg>
              </button>
            </div>
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
