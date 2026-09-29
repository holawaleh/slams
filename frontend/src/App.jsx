import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Overview from "./pages/Overview";
import UnknownCards from "./pages/UnknownCards";
import Students from "./pages/Students";
import Courses, { CourseDetail } from "./pages/Courses";
import "./theme.css";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading)
    return <div className="center muted" style={{ padding: 60 }}>Loading...</div>;
  return user ? children : <Navigate to="/login" replace />;
}

function Soon({ title }) {
  return (
    <>
      <h2>{title}</h2>
      <p className="muted">Not built yet.</p>
    </>
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
          <Route path="/register" element={<Register />} />

          <Route element={<Protected><Layout /></Protected>}>
            <Route path="/dashboard"  element={<Overview />} />
            <Route path="/students"   element={<Students />} />
            <Route path="/cards"      element={<Soon title="Cards" />} />
            <Route path="/unknown"    element={<UnknownCards />} />
            <Route path="/courses"    element={<Courses />} />
            <Route path="/courses/:id" element={<CourseDetail />} />
            <Route path="/timetable"  element={<Soon title="Timetable" />} />
            <Route path="/sessions"   element={<Soon title="Lectures" />} />
            <Route path="/attendance" element={<Soon title="Attendance" />} />
            <Route path="/devices"    element={<Soon title="Devices" />} />
            <Route path="/members"    element={<Soon title="Team" />} />
            <Route path="/settings"   element={<Soon title="Settings" />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
