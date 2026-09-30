import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import api from "../lib/api";
import ThemeToggle from "./ThemeToggle";
import "./Layout.css";

const NAV = [
  { to: "/dashboard",  label: "Overview",  icon: "grid" },
  { to: "/students",   label: "Students",  icon: "users" },
  { to: "/cards",      label: "Cards",     icon: "card", admin: true },
  { to: "/courses",    label: "Courses",   icon: "book" },
  { to: "/timetable",  label: "Timetable", icon: "clock" },
  { to: "/reports",    label: "Reports",   icon: "chart" },
  { to: "/settings",   label: "Settings",  icon: "gear" },
];

export function Icon({ name, size = 18 }) {
  const common = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: 2,
    strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
  };
  const paths = {
    grid: <><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></>,
    users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /></>,
    card: <><rect x="1" y="4" width="22" height="16" rx="2" /><line x1="1" y1="10" x2="23" y2="10" /></>,
    book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></>,
    clock: <><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></>,
    chart: <><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" /></>,
    gear: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></>,
    logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></>,
    user: <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>,
    pin: <><line x1="12" y1="17" x2="12" y2="22" /><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24z" /></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

export function initials(user) {
  return ((user?.first_name?.[0] || "") + (user?.last_name?.[0] || "")).toUpperCase() ||
    user?.username?.slice(0, 2).toUpperCase() || "?";
}

// The sidebar hides itself: on a desktop it sits as a slim strip of icons
// and slides out while the pointer is over it; on a phone it is a drawer
// that closes as soon as a page is chosen. Pinning keeps it open.
export default function Layout() {
  const { user, org, orgs, isAdmin, isPlatformAdmin, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [pinned, setPinned] = useState(() => {
    try { return localStorage.getItem("sidebarPinned") === "1"; } catch { return false; }
  });
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => { setOpen(false); setMenu(false); }, [location.pathname]);

  function togglePin() {
    const next = !pinned;
    setPinned(next);
    try { localStorage.setItem("sidebarPinned", next ? "1" : "0"); } catch { /* optional */ }
  }

  const items = NAV.filter((n) => !n.admin || isAdmin);
  const role = isPlatformAdmin ? "platform admin" : org?.role;
  const name = [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.username;

  return (
    <div className={"shell" + (pinned ? " pinned" : "")}>
      <aside className={"sidebar" + (open ? " open" : "")} aria-label="Main">
        <div className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2.4" strokeLinecap="round">
              <polyline points="4 13 9 18 20 6" />
            </svg>
          </div>
          <div className="brand-text sb-label">
            <strong>SLAMS</strong>
            <span className="faint">{org?.name}</span>
          </div>
          <button type="button" className={"pin-btn sb-label" + (pinned ? " on" : "")}
                  onClick={togglePin} title={pinned ? "Let the menu hide itself" : "Keep the menu open"}
                  aria-pressed={pinned}>
            <Icon name="pin" size={15} />
          </button>
        </div>

        <nav>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} title={n.label}
                     className={({ isActive }) => "navlink" + (isActive ? " active" : "")}>
              <Icon name={n.icon} />
              <span className="sb-label">{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <Link to="/settings/profile" className="me" title="Your profile">
            <span className="avatar">{initials(user)}</span>
            <span className="me-text sb-label">
              <strong>{name}</strong>
              <small className="faint">{role}{org?.term ? ` · ${org.term}` : ""}</small>
            </span>
          </Link>
          <button type="button" className="navlink signout" onClick={logout} title="Sign out">
            <Icon name="logout" />
            <span className="sb-label">Sign out</span>
          </button>
        </div>
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
            <button className="btn-ghost account-btn" onClick={() => setMenu(!menu)}
                    aria-haspopup="menu" aria-expanded={menu}>
              <span className="avatar">{initials(user)}</span>
              <span className="account-name">
                {user?.username}
                <small className="faint">{role}</small>
              </span>
            </button>

            {menu && (
              <>
                <div className="scrim bare" onClick={() => setMenu(false)} />
                <div className="menu card" role="menu">
                  <div className="menu-head faint">{user?.email || user?.username}</div>
                  <button className="menu-item" onClick={() => navigate("/settings/profile")}>
                    Profile
                  </button>
                  <button className="menu-item" onClick={() => navigate("/settings/password")}>
                    Change password
                  </button>
                  <button className="menu-item" onClick={() => navigate("/settings")}>
                    Settings
                  </button>
                  {orgs.length > 1 && (
                    <>
                      <div className="menu-sep" />
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
                    </>
                  )}
                  {isPlatformAdmin && (
                    <a className="menu-item" target="_blank" rel="noreferrer"
                       href={`${api.defaults.baseURL}/admin/`}>
                      All users &amp; data (Django admin)
                    </a>
                  )}
                  <div className="menu-sep" />
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
