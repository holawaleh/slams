import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import "./theme.css";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted" style={{ padding: 60 }}>Loading...</div>;
  return user ? children : <Navigate to="/login" replace />;
}

function Placeholder() {
  const { user, org, logout } = useAuth();
  return (
    <div style={{ padding: 40 }}>
      <h2>Signed in</h2>
      <p className="muted">
        {user?.username} at {org?.name} ({org?.role})
      </p>
      <button className="btn-ghost" onClick={logout}>Sign out</button>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="topbar-strip" />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<Protected><Placeholder /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
