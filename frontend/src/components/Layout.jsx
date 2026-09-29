import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import ThemeToggle from "./ThemeToggle";
import "./Layout.css";

const NAV = [
  { to: "/dashboard",  label: "Overview",   icon: "grid" },
  { to: "/students",   label: "Students",   icon: "users" },
  { to: "/cards",      label: "Cards",      icon: "card", admin: true },
  { to: "/unknown",    label: "New cards",  icon: "alert", admin: true },
  { to: "/courses",    label: "Courses",    icon: "book" },
  { to: "/timetable",  label: "Timetable",  icon: "clock" },
  { to: "/sessions",   label: "Lectures",   icon: "play" },
  { to: "/attendance", label: "Attendance", icon: "check" },
  { to: "/devices",    label: "Devices",    icon: "chip", admin: true },
  { to: "/members",    label: "Team",       icon: "team", admin: true },
];

function Icon({ name }) {
  const common = {
    width: 18, height: 18, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: 2,
    strokeLinecap: "round", strokeLinejoin: "round",
  };
  const paths = {
    grid: <><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></>,
    users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /></>,
    card: <><rect x="1" y="4" width="22" height="16" rx="2" /><line x1="1" y1="10" x2="23" y2="10" /></>,
    alert: <><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
    book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>,
    clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
    play: <><circle cx="12" cy="12" r="10" /><polygon points="10 8 16 12 10 16 10 8" /></>,
    check: <><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>,
    chip: <><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" /><line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" /></>,
    team: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

export default function Layout() {
  const { user, org, orgs, isAdmin, isPlatformAdmin, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const navigate = useNavigate();

  const items = NAV.filter((n) => !n.admin || isAdmin);
  const initials =
    ((user?.first_name?.[0] || "") + (user?.last_name?.[0] || "")).toUpperCase() ||
    user?.username?.slice(0, 2).toUpperCase() || "?";

  return (
    <div className="shell">
      <aside className={"sidebar" + (open ? " open" : "")}>
        <div className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2.4" strokeLinecap="round">
              <polyline points="4 13 9 18 20 6" />
            </svg>
          </div>
          <div className="brand-text">
            <strong>SLAMS</strong>
            <span className="faint">{org?.name}</span>
          </div>
        </div>

        <nav>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} onClick={() => setOpen(false)}
                     className={({ isActive }) =>
                       "navlink" + (isActive ? " active" : "")}>
              <Icon name={n.icon} />
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot faint">{org?.term}</div>
      </aside>

      {open && <div className="scrim" onClick={() => setOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <button className="btn-ghost menu-btn" onClick={() => setOpen(!open)}
                  aria-label="Menu">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>

          <div className="grow" />

          <ThemeToggle />

          <div className="account">
            <button className="btn-ghost account-btn"
                    onClick={() => setMenu(!menu)}>
              <span className="avatar">{initials}</span>
              <span className="account-name">
                {user?.username}
                <small className="faint">
                  {isPlatformAdmin ? "platform admin" : org?.role}
                </small>
              </span>
            </button>

            {menu && (
              <>
                <div className="scrim bare" onClick={() => setMenu(false)} />
                <div className="menu card">
                  {orgs.length > 1 && (
                    <>
                      <div className="menu-head faint">Organisation</div>
                      {orgs.map((o) => (
                        <button key={o.slug} className="menu-item"
                                onClick={() => {
                                  localStorage.setItem("org", o.slug);
                                  window.location.reload();
                                }}>
                          {o.name}
                          {o.slug === org?.slug && <span className="pill">current</span>}
                        </button>
                      ))}
                      <div className="menu-sep" />
                    </>
                  )}
                  <button className="menu-item"
                          onClick={() => { setMenu(false); navigate("/settings"); }}>
                    Settings
                  </button>
                  {isPlatformAdmin && (
                    <a className="menu-item" target="_blank" rel="noreferrer"
                       href={`${api.defaults.baseURL}/admin/`}>
                      All users &amp; data (Django admin)
                    </a>
                  )}
                  <button className="menu-item danger" onClick={logout}>
                    Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
