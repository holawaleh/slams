import { Link } from "react-router-dom";
import "./Landing.css";

export default function Landing() {
  return (
    <div className="landing">
      <div className="landing-inner">
        <svg className="landing-cap" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 3 1 9l11 6 9-4.91V17h2V9M5 13.18v4L12 21l7-3.82v-4L12 17z" />
        </svg>
        <h1>Smart Lecture Attendance Management System</h1>
        <p className="landing-sub">
          Comprehensive admin dashboard for students data management
        </p>
        <Link to="/login" className="btn btn-solid landing-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
            <polyline points="10 17 15 12 10 7" />
            <line x1="15" y1="12" x2="3" y2="12" />
          </svg>
          Login to Dashboard
        </Link>
        <p className="faint landing-note">Authorized personnel only</p>
      </div>
    </div>
  );
}
