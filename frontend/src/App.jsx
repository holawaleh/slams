import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Overview from "./pages/Overview";
import Students from "./pages/Students";
import Courses, { CourseDetail } from "./pages/Courses";
import Timetable from "./pages/Timetable";
import Cards from "./pages/Cards";
import Reports, { CourseReport } from "./pages/Reports";
import Settings from "./pages/Settings";
import Platform from "./pages/Platform";
import "./theme.css";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading)
    return <div className="center muted" style={{ padding: 60 }}>Loading...</div>;
  return user ? children : <Navigate to="/login" replace />;
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
            <Route path="/dashboard"   element={<Overview />} />
            <Route path="/students"    element={<Students />} />
            <Route path="/cards"       element={<Cards />} />
            <Route path="/courses"     element={<Courses />} />
            <Route path="/courses/:id" element={<CourseDetail />} />
            <Route path="/timetable"   element={<Timetable />} />
            <Route path="/reports"     element={<Reports />} />
            <Route path="/reports/:id" element={<CourseReport />} />
            <Route path="/settings"    element={<Navigate to="/settings/profile" replace />} />
            <Route path="/settings/:tab" element={<Settings />} />
            <Route path="/platform"      element={<Platform />} />
            <Route path="/platform/:tab" element={<Platform />} />
            <Route path="/profile"     element={<Navigate to="/settings/profile" replace />} />

            {/* Old addresses, kept so bookmarks still land somewhere useful. */}
            <Route path="/unknown"    element={<Navigate to="/cards?tab=activity" replace />} />
            <Route path="/logs"       element={<Navigate to="/cards?tab=activity" replace />} />
            <Route path="/attendance" element={<Navigate to="/reports" replace />} />
            <Route path="/sessions"   element={<Navigate to="/reports" replace />} />
            <Route path="/devices"    element={<Navigate to="/settings/devices" replace />} />
            <Route path="/members"    element={<Navigate to="/settings/team" replace />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
