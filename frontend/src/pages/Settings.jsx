import { useEffect, useState } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { PASSWORD_RULES, passwordOk, missingRules } from "../lib/password";
import { PageHead, Loading, Empty, ErrorBox, errorText } from "../components/bits";
import Modal from "../components/Modal";
import PasswordInput from "../components/PasswordInput";
import { initials } from "../components/Layout";
import Devices from "./Devices";
import { AdminActions } from "./Logs";
import { ago } from "./Cards";

const TABS = [
  { id: "profile",      label: "Profile" },
  { id: "password",     label: "Change password" },
  { id: "team",         label: "Staff",           admin: true },
  { id: "roles",        label: "Roles & privileges" },
  { id: "devices",      label: "Devices",         admin: true },
  { id: "organisation", label: "Organisation",    admin: true },
  { id: "audit",        label: "Audit log",       admin: true },
];

const ROLE_LABEL = { owner: "Owner", admin: "Admin", lecturer: "Lecturer", viewer: "Viewer" };

// What each role can do. Kept in step with the permission classes on the
// server; the server is what actually enforces it.
const PRIVILEGES = [
  ["See students, courses, timetable and reports",   true,  true,  true,  true],
  ["See lecture attendance and card swipes",          true,  true,  true,  false],
  ["Reports for their own courses only",              false, false, true,  false],
  ["Add and edit students, register cards",           true,  true,  false, false],
  ["Manage courses, enrolment and the timetable",     true,  true,  false, false],
  ["Add, place and remove readers",                   true,  true,  false, false],
  ["Add lecturers and viewers, reset their passwords", true, true,  false, false],
  ["Add or change admins and owners",                 true,  false, false, false],
  ["Change organisation settings, see the audit log", true,  true,  false, false],
];

function fieldError(error, key) {
  const v = error?.response?.data?.[key];
  return v ? <small className="field-error">{Array.isArray(v) ? v.join(" ") : v}</small> : null;
}

function Profile() {
  const { user, org, reload } = useAuth();
  const [form, setForm] = useState({
    full_name: [user?.first_name, user?.last_name].filter(Boolean).join(" "),
    email: user?.email ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await api.patch("/api/me/profile/", form);
      await reload();
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card settings-card">
      <div className="row" style={{ marginBottom: 20 }}>
        <span className="avatar avatar-lg">{initials(user)}</span>
        <div>
          <strong style={{ fontSize: 17 }}>{form.full_name || user?.username}</strong>
          <div className="faint" style={{ fontSize: 14 }}>
            {user?.username} · {ROLE_LABEL[org?.role] ?? org?.role} at {org?.name}
          </div>
        </div>
      </div>
      <form onSubmit={save} noValidate>
        {done && <div className="alert alert-ok">Profile saved.</div>}
        {error && !error.response?.data?.full_name && !error.response?.data?.email &&
          <div className="alert alert-bad">{errorText(error)}</div>}
        <div className="field">
          <label htmlFor="pname">Full name</label>
          <input id="pname" className="input" value={form.full_name} maxLength={300}
                 onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          {fieldError(error, "full_name")}
        </div>
        <div className="field">
          <label htmlFor="pmail">Email</label>
          <input id="pmail" className="input" type="email" value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />
          {fieldError(error, "email")}
        </div>
        <div className="field">
          <label>Username</label>
          <input className="input" value={user?.username ?? ""} disabled />
          <small className="faint" style={{ display: "block", marginTop: 6 }}>
            Your sign-in name cannot be changed.
          </small>
        </div>
        <button className="btn-solid" disabled={busy}>{busy ? "Saving..." : "Save profile"}</button>
      </form>
    </div>
  );
}

function PasswordRules({ value }) {
  return (
    <ul className="pw-rules" aria-live="polite">
      {PASSWORD_RULES.map((r) => {
        const met = r.test(value);
        const failed = !met && value.length > 0;
        return (
          <li key={r.label} className={met ? "met" : failed ? "unmet" : ""}>
            <span aria-hidden="true">{met ? "✓" : failed ? "✗" : "•"}</span>{r.label}
          </li>
        );
      })}
    </ul>
  );
}

function ChangePassword() {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [local, setLocal] = useState({});
  const [done, setDone] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    const problems = {};
    if (!form.current) problems.current = "Enter your current password.";
    if (!passwordOk(form.next))
      problems.next = `Still needed: ${missingRules(form.next).join(", ")}.`;
    if (form.next !== form.confirm) problems.confirm = "Passwords do not match.";
    setLocal(problems);
    if (Object.keys(problems).length) return;

    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await api.post("/api/me/password/", { current_password: form.current,
                                             new_password: form.next });
      setForm({ current: "", next: "", confirm: "" });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card settings-card">
      <form onSubmit={save} noValidate>
        {done && <div className="alert alert-ok">Password changed. Use it next time you sign in.</div>}
        <div className="field">
          <label htmlFor="cur">Current password</label>
          <PasswordInput id="cur" value={form.current} autoComplete="current-password"
                         invalid={!!local.current || !!error?.response?.data?.current_password}
                         onChange={set("current")} />
          {local.current && <small className="field-error">{local.current}</small>}
          {fieldError(error, "current_password")}
        </div>
        <div className="field">
          <label htmlFor="new">New password</label>
          <PasswordInput id="new" value={form.next} autoComplete="new-password"
                         invalid={!!local.next} onChange={set("next")} />
          <PasswordRules value={form.next} />
          {local.next && <small className="field-error">{local.next}</small>}
          {fieldError(error, "new_password")}
        </div>
        <div className="field">
          <label htmlFor="conf">Re-type new password</label>
          <PasswordInput id="conf" value={form.confirm} autoComplete="new-password"
                         invalid={!!local.confirm} onChange={set("confirm")} />
          {local.confirm && <small className="field-error">{local.confirm}</small>}
        </div>
        <button className="btn-solid" disabled={busy}>{busy ? "Changing..." : "Change password"}</button>
      </form>
    </div>
  );
}

// A temporary password that already satisfies every rule.
function tempPassword() {
  const pick = (set, n) => Array.from(crypto.getRandomValues(new Uint32Array(n)),
                                      (x) => set[x % set.length]).join("");
  const raw = pick("ABCDEFGHJKLMNPQRSTUVWXYZ", 3) + pick("abcdefghijkmnpqrstuvwxyz", 4) +
              pick("23456789", 3) + pick("!@#-", 2);
  return raw.split("").sort(() => crypto.getRandomValues(new Uint8Array(1))[0] - 128).join("");
}

function allowedRoles(myRole) {
  return myRole === "owner" ? ["viewer", "lecturer", "admin", "owner"] : ["viewer", "lecturer"];
}

function AddStaff({ myRole, onClose, onDone }) {
  const [form, setForm] = useState({ full_name: "", username: "", email: "",
                                     role: "lecturer", password: tempPassword() });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/members/", { ...form, username: form.username.trim().toLowerCase() });
      setCreated({ ...form, username: form.username.trim().toLowerCase() });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <Modal title="Staff member added" onClose={onDone}>
        <p className="muted" style={{ marginTop: 0 }}>
          Give {created.full_name} these details. They should change the password
          after signing in, under Settings → Change password.
        </p>
        <dl className="facts">
          <div><dt>Username</dt><dd className="mono">{created.username}</dd></div>
          <div><dt>Temporary password</dt><dd className="mono">{created.password}</dd></div>
          <div><dt>Role</dt><dd>{ROLE_LABEL[created.role]}</dd></div>
        </dl>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn-solid" onClick={onDone}>Done</button>
        </div>
      </Modal>
    );
  }

  const known = ["full_name", "username", "email", "role", "password"];
  const general = error && !known.some((k) => error.response?.data?.[k]);

  return (
    <Modal title="Add staff" onClose={onClose} width={520}>
      <form onSubmit={save} noValidate>
        {general && <div className="alert alert-bad">{errorText(error)}</div>}
        <div className="field">
          <label htmlFor="sname">Full name</label>
          <input id="sname" className="input" autoFocus value={form.full_name} onChange={set("full_name")} />
          {fieldError(error, "full_name")}
        </div>
        <div className="form-2">
          <div className="field">
            <label htmlFor="suser">Username</label>
            <input id="suser" className="input" autoCapitalize="off" autoComplete="off"
                   placeholder="letters, numbers, . _ -" value={form.username} onChange={set("username")} />
            {fieldError(error, "username")}
          </div>
          <div className="field">
            <label htmlFor="srole">Role</label>
            <select id="srole" className="input" value={form.role} onChange={set("role")}>
              {allowedRoles(myRole).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
            {fieldError(error, "role")}
          </div>
        </div>
        <div className="field">
          <label htmlFor="smail">Email <span className="faint">(optional)</span></label>
          <input id="smail" className="input" type="email" value={form.email} onChange={set("email")} />
          {fieldError(error, "email")}
        </div>
        <div className="field">
          <label htmlFor="spw">Temporary password</label>
          <div className="row">
            <input id="spw" className="input mono" value={form.password} onChange={set("password")} />
            <button type="button" className="btn-ghost" style={{ flex: "0 0 auto" }}
                    onClick={() => setForm({ ...form, password: tempPassword() })}>New</button>
          </div>
          <PasswordRules value={form.password} />
          {fieldError(error, "password")}
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-solid" disabled={busy || !passwordOk(form.password)}>
            {busy ? "Adding..." : "Add staff"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ResetPassword({ member, onClose, onDone, url }) {
  const [password, setPassword] = useState(tempPassword());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.post(url || `/api/members/${member.id}/set_password/`, { password });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`New password for ${member.full_name || member.username}`} onClose={done ? onDone : onClose}>
      <ErrorBox error={error} />
      {done ? (
        <p>Password changed. Give them: <code className="mono">{password}</code></p>
      ) : (
        <>
          <div className="row">
            <input className="input mono" value={password} onChange={(e) => setPassword(e.target.value)} />
            <button type="button" className="btn-ghost" style={{ flex: "0 0 auto" }}
                    onClick={() => setPassword(tempPassword())}>New</button>
          </div>
          <PasswordRules value={password} />
        </>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        {done ? <button className="btn-solid" onClick={onDone}>Done</button> : (
          <>
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-solid" disabled={busy || !passwordOk(password)} onClick={save}>
              {busy ? "Saving..." : "Set password"}
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}

function Team() {
  const { user, org } = useAuth();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [resetting, setResetting] = useState(null);
  const [flash, setFlash] = useState("");
  const myRole = org?.role;
  const canManage = (role) => myRole === "owner" || ["lecturer", "viewer"].includes(role);

  const load = () => api.get("/api/members/", { params: { page_size: 200 } })
    .then(({ data }) => setRows(data.results ?? data)).catch(setError);
  useEffect(() => { load(); }, []);

  function note(msg) { setFlash(msg); setTimeout(() => setFlash(""), 4000); }

  async function changeRole(m, role) {
    setError(null);
    try {
      await api.patch(`/api/members/${m.id}/`, { role });
      note(`${m.full_name || m.username} is now ${ROLE_LABEL[role]}.`);
      load();
    } catch (err) {
      setError(err);
      load();
    }
  }

  async function remove(m) {
    if (!window.confirm(`Remove ${m.full_name || m.username} from ${org?.name}? They will no longer be able to sign in here.`))
      return;
    setError(null);
    try {
      await api.delete(`/api/members/${m.id}/`);
      note(`${m.full_name || m.username} removed.`);
      load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <div className="spread filters">
        <p className="muted" style={{ margin: 0 }}>
          People who can sign in to {org?.name}. {myRole === "admin" &&
            "As an admin you can manage lecturers and viewers; owners manage admins."}
        </p>
        <button className="btn-solid" onClick={() => setAdding(true)}>Add staff</button>
      </div>
      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error} />
      <div className="card" style={{ padding: 0 }}>
        {!rows ? <Loading what="staff" /> : rows.length === 0 ? <Empty message="Nobody yet." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Role</th><th>Last signed in</th><th /></tr></thead>
              <tbody>
                {rows.map((m) => {
                  const self = m.user === user?.id;
                  const editable = !self && canManage(m.role);
                  return (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.full_name || m.username}</strong>{self && <span className="pill" style={{ marginLeft: 8 }}>you</span>}
                        <small className="faint" style={{ display: "block" }}>
                          {m.username}{m.email ? ` · ${m.email}` : ""}
                        </small>
                      </td>
                      <td>
                        {editable ? (
                          <select className="input role-select" value={m.role}
                                  onChange={(e) => changeRole(m, e.target.value)}
                                  aria-label={`Role for ${m.username}`}>
                            {allowedRoles(myRole).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                          </select>
                        ) : <span className="pill">{ROLE_LABEL[m.role]}</span>}
                      </td>
                      <td className="muted">{m.last_login ? ago(m.last_login) : "never"}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {editable && (
                          <>
                            <button className="btn-ghost btn-sm" onClick={() => setResetting(m)}>Reset password</button>{" "}
                            <button className="btn-ghost btn-sm" onClick={() => remove(m)}>Remove</button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {adding && <AddStaff myRole={myRole} onClose={() => setAdding(false)}
                           onDone={() => { setAdding(false); load(); }} />}
      {resetting && <ResetPassword member={resetting} onClose={() => setResetting(null)}
                                   onDone={() => setResetting(null)} />}
    </>
  );
}

function Roles() {
  const { org } = useAuth();
  const roles = ["owner", "admin", "lecturer", "viewer"];
  return (
    <>
      <p className="muted" style={{ marginTop: 0 }}>
        What each role can do. You are {["owner", "admin"].includes(org?.role) ? "an" : "a"}{" "}
        {ROLE_LABEL[org?.role]?.toLowerCase()}.
      </p>
      <div className="card" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table className="matrix">
            <thead>
              <tr><th>Privilege</th>{roles.map((r) => (
                <th key={r} className={r === org?.role ? "mine" : ""}>{ROLE_LABEL[r]}</th>))}</tr>
            </thead>
            <tbody>
              {PRIVILEGES.map(([label, ...allowed]) => (
                <tr key={label}>
                  <td>{label}</td>
                  {allowed.map((ok, i) => (
                    <td key={roles[i]} className={roles[i] === org?.role ? "mine" : ""}>
                      {ok ? <span className="yes" aria-label="yes">✓</span>
                          : <span className="no" aria-label="no">–</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="faint" style={{ fontSize: 13, marginTop: 12 }}>
        Every organisation keeps at least one owner. Nobody can change their own role or remove themselves.
      </p>
    </>
  );
}

function Organisation() {
  const { reload } = useAuth();
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.get("/api/organization/").then(({ data }) => setForm({
      name: data.name, address: data.address ?? "", country: data.country,
      term: data.term, timezone: data.timezone,
      readers: `${data.device_count} of ${data.max_devices}`,
    })).catch(setError);
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const { readers: _r, ...body } = form;
      await api.patch("/api/organization/", body);
      await reload();
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!form) return error ? <ErrorBox error={error} /> : <Loading what="settings" />;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="card settings-card">
      <form onSubmit={save} noValidate>
        {done && <div className="alert alert-ok">Saved.</div>}
        {error && <div className="alert alert-bad">{errorText(error)}</div>}
        <div className="field">
          <label htmlFor="oname">Name</label>
          <input id="oname" className="input" value={form.name} onChange={set("name")} />
        </div>
        <div className="form-2">
          <div className="field">
            <label htmlFor="oterm">Current term</label>
            <input id="oterm" className="input" value={form.term} maxLength={16} onChange={set("term")} />
            <small className="faint" style={{ display: "block", marginTop: 6 }}>
              Enrolment and the timetable are kept per term.
            </small>
          </div>
          <div className="field">
            <label htmlFor="otz">Time zone</label>
            <input id="otz" className="input" value={form.timezone} onChange={set("timezone")}
                   list="tz-options" />
            <datalist id="tz-options">
              {["Africa/Lagos", "Africa/Accra", "Africa/Nairobi", "Africa/Johannesburg", "Europe/London", "UTC"]
                .map((z) => <option key={z} value={z} />)}
            </datalist>
          </div>
        </div>
        <div className="field">
          <label htmlFor="oaddr">Address</label>
          <input id="oaddr" className="input" value={form.address} maxLength={255}
                 onChange={set("address")} />
        </div>
        <div className="field">
          <label htmlFor="ocountry">Country</label>
          <input id="ocountry" className="input" value={form.country} onChange={set("country")} />
        </div>
        <p className="faint" style={{ fontSize: 13 }}>Readers in use: {form.readers}.</p>
        <button className="btn-solid" disabled={busy}>{busy ? "Saving..." : "Save"}</button>
      </form>
    </div>
  );
}

export default function Settings() {
  const { tab = "profile" } = useParams();
  const { isAdmin } = useAuth();
  const tabs = TABS.filter((t) => !t.admin || isAdmin);
  if (!tabs.some((t) => t.id === tab)) return <Navigate to="/settings/profile" replace />;

  return (
    <>
      <PageHead title="Settings" />
      <nav className="tabs" aria-label="Settings sections">
        {tabs.map((t) => (
          <NavLink key={t.id} to={`/settings/${t.id}`}
                   className={({ isActive }) => (isActive ? "on" : "")}>{t.label}</NavLink>
        ))}
      </nav>
      {tab === "profile" && <Profile />}
      {tab === "password" && <ChangePassword />}
      {tab === "team" && <Team />}
      {tab === "roles" && <Roles />}
      {tab === "devices" && <Devices embedded />}
      {tab === "organisation" && <Organisation />}
      {tab === "audit" && <AdminActions />}
    </>
  );
}
