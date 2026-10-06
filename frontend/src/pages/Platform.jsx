import { useCallback, useEffect, useState } from "react";
import { useList, useDebounced } from "../lib/useList";
import { NavLink, Navigate, useParams } from "react-router-dom";
import api from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHead, Loading, Empty, ErrorBox } from "../components/bits";
import Modal from "../components/Modal";
import Pager from "../components/Pager";
import { ResetPassword } from "./Settings";
import { ago } from "./Cards";

// The platform administrator's console: every school, user, reader and
// action in the system. The server only answers superusers; this page
// is hidden from everyone else as well.

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "schools",  label: "Schools" },
  { id: "users",    label: "Users" },
  { id: "readers",  label: "Readers" },
  { id: "activity", label: "Activity" },
];

const ROLES = ["owner", "admin", "lecturer", "viewer"];
const ROLE_LABEL = { owner: "Owner", admin: "Admin", lecturer: "Lecturer", viewer: "Viewer" };
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "-");

// Step into a school's dashboard as its owner would see it.
function openSchool(slug) {
  localStorage.setItem("org", slug);
  window.location.href = "/dashboard";
}

function Tile({ label, value, sub, tone }) {
  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="tile-label">{label}</div>
      <div className="tile-value" style={{ color: tone ? `var(--${tone})` : "inherit" }}>
        {value ?? "-"}
      </div>
      {sub && <small className="faint">{sub}</small>}
    </div>
  );
}

function StatusPill({ active, on = "active", off = "disabled" }) {
  return <span className={"pill " + (active ? "pill-ok" : "pill-bad")}>{active ? on : off}</span>;
}

// ---------------- overview ----------------

function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api.get("/api/platform/summary/").then((r) => setData(r.data)).catch(setError);
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="the summary" />;

  const max = Math.max(1, ...data.daily.map((d) => d.taps));
  return (
    <>
      <div style={{ display: "grid", gap: 14, marginBottom: 20,
                    gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
        <Tile label="Schools" value={data.schools.total}
              sub={`${data.schools.active} active · ${data.schools.new_30d} new in 30 days`} />
        <Tile label="Users" value={data.users.total}
              sub={`${data.users.signed_in_7d} signed in this week · ${data.users.total - data.users.active} disabled`} />
        <Tile label="Students" value={data.students} sub={`${data.cards} active cards`} />
        <Tile label="Readers online" value={`${data.readers.online} / ${data.readers.total}`}
              tone={data.readers.total && !data.readers.online ? "bad" : null} />
        <Tile label="Taps today" value={data.taps.today}
              sub={`${data.taps.d7} this week · ${data.taps.d30} in 30 days`} />
        <Tile label="Attendance marked" value={data.attendance_30d} sub="last 30 days" />
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <h3>Card taps per day, last 30 days</h3>
        <div className="bars" role="img"
             aria-label={`Taps per day, highest ${max}`}>
          {data.daily.map((d) => (
            <div key={d.date} className="bar"
                 title={`${new Date(d.date).toLocaleDateString()}: ${d.taps} taps, ${d.sign_ins} sign-ins`}>
              <span style={{ height: `${(d.taps / max) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="spread faint" style={{ fontSize: 12, marginTop: 6 }}>
          <span>{new Date(data.daily[0].date).toLocaleDateString()}</span>
          <span>today</span>
        </div>
      </div>

      <div className="card">
        <h3>Busiest schools, last 30 days</h3>
        {data.top_schools.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>No card taps anywhere yet.</p>
        ) : (
          <table>
            <thead><tr><th>School</th><th>Taps</th></tr></thead>
            <tbody>
              {data.top_schools.map((s) => (
                <tr key={s.id}><td>{s.name}</td><td>{s.taps}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ---------------- schools ----------------

function SchoolDetail({ id, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");

  const load = useCallback(() => {
    api.get(`/api/platform/orgs/${id}/`).then(({ data }) => {
      setData(data);
      setForm({ name: data.name, address: data.address, country: data.country,
                term: data.term, timezone: data.timezone,
                max_devices: data.max_devices, max_students: data.max_students });
    }).catch(setError);
  }, [id]);
  useEffect(load, [load]);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    setBusy(true); setError(null); setFlash("");
    try {
      await api.patch(`/api/platform/orgs/${id}/`, form);
      setFlash("Saved.");
      onChanged();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <Modal title={data?.name || "School"} onClose={onClose} width={720}>
      <ErrorBox error={error} />
      {flash && <div className="alert alert-ok">{flash}</div>}
      {!data || !form ? <Loading what="the school" /> : (
        <>
          <dl className="facts">
            <div><dt>Code</dt><dd className="mono">{data.slug}</dd></div>
            <div><dt>Status</dt><dd><StatusPill active={data.active} /></dd></div>
            <div><dt>Registered</dt><dd>{new Date(data.created_at).toLocaleDateString()}</dd></div>
            <div><dt>Students</dt><dd>{data.student_count}</dd></div>
            <div><dt>Courses</dt><dd>{data.course_count}</dd></div>
            <div><dt>Taps, 30 days</dt><dd>{data.taps_30d}</dd></div>
            <div><dt>Last tap</dt><dd>{ago(data.last_tap)}</dd></div>
            <div><dt>Last staff action</dt><dd>{ago(data.last_action)}</dd></div>
          </dl>

          <form onSubmit={save}>
            <div className="form-2">
              <div className="field"><label htmlFor="sn">Name</label>
                <input id="sn" className="input" value={form.name} onChange={set("name")} /></div>
              <div className="field"><label htmlFor="sa">Address</label>
                <input id="sa" className="input" value={form.address} onChange={set("address")} /></div>
              <div className="field"><label htmlFor="sc">Country</label>
                <input id="sc" className="input" value={form.country} onChange={set("country")} /></div>
              <div className="field"><label htmlFor="sz">Time zone</label>
                <input id="sz" className="input" value={form.timezone} onChange={set("timezone")} /></div>
              <div className="field"><label htmlFor="st">Current term</label>
                <input id="st" className="input" maxLength={16} value={form.term} onChange={set("term")} /></div>
              <div className="field"><label htmlFor="sd">Reader limit</label>
                <input id="sd" className="input" type="number" min={0} value={form.max_devices}
                       onChange={set("max_devices")} /></div>
              <div className="field"><label htmlFor="ss">Student limit</label>
                <input id="ss" className="input" type="number" min={0} value={form.max_students}
                       onChange={set("max_students")} /></div>
            </div>
            <button className="btn-solid" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button>
          </form>

          <h3 style={{ marginTop: 24 }}>Staff ({data.members.length})</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Role</th><th>Last signed in</th></tr></thead>
              <tbody>
                {data.members.map((m) => (
                  <tr key={m.id}>
                    <td><strong>{m.full_name || m.username}</strong>
                      <small className="faint" style={{ display: "block" }}>
                        {m.username}{m.email ? ` · ${m.email}` : ""}
                      </small></td>
                    <td><span className="pill">{ROLE_LABEL[m.role]}</span>
                      {!m.is_active && <> <StatusPill active={false} /></>}</td>
                    <td className="muted">{ago(m.last_login)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 style={{ marginTop: 24 }}>Readers ({data.readers.length})</h3>
          {data.readers.length === 0 ? <p className="muted">No readers.</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Reader</th><th>Venue</th><th>Status</th></tr></thead>
                <tbody>
                  {data.readers.map((d) => (
                    <tr key={d.id}>
                      <td><strong>{d.name}</strong>
                        <small className="faint mono" style={{ display: "block" }}>{d.hardware_id}</small></td>
                      <td>{d.venue || <span className="faint">not placed</span>}</td>
                      <td><StatusPill active={d.online} on="online" off={`seen ${ago(d.last_seen)}`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        {data?.active && <button className="btn-ghost" onClick={() => openSchool(data.slug)}>Open its dashboard</button>}
        <button className="btn-solid" onClick={onClose}>Close</button>
      </div>
    </Modal>
  );
}

function Schools() {
  const [q, setQ] = useState("");
  const search = useDebounced(q);
  const [status, setStatus] = useState("");
  const params = { search: search || undefined, active: status || undefined, ordering: "name" };
  const { rows, count, page, setPage, loading, error, reload: load } = useList("/api/platform/orgs/", params);
  const [opened, setOpened] = useState(null);
  const [problem, setProblem] = useState(null);
  const [flash, setFlash] = useState("");

  async function toggle(o) {
    const verb = o.active ? "Disable" : "Re-enable";
    if (o.active && !window.confirm(
      `Disable ${o.name}? Nobody in it can sign in and its readers stop counting until you re-enable it.`)) return;
    setProblem(null);
    try {
      await api.patch(`/api/platform/orgs/${o.id}/`, { active: !o.active });
      setFlash(`${verb}d ${o.name}.`);
      load();
    } catch (err) { setProblem(err); }
  }

  async function remove(o) {
    const typed = window.prompt(
      `Delete ${o.name} and ALL its data: ${o.student_count} students, ${o.course_count} courses, ` +
      `every lecture, tap and audit entry. This cannot be undone.\n\nType the school code "${o.slug}" to confirm.`);
    if (typed === null) return;
    if (typed.trim() !== o.slug) { setProblem({ response: { data: { detail: "The code did not match; nothing was deleted." } } }); return; }
    setProblem(null);
    try {
      await api.delete(`/api/platform/orgs/${o.id}/`, { params: { confirm: o.slug } });
      setFlash(`Deleted ${o.name}.`);
      load();
    } catch (err) { setProblem(err); }
  }

  return (
    <>
      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "1 1 240px", maxWidth: 360 }} placeholder="Search schools"
               value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search schools" />
        <select className="input" style={{ flex: "0 0 160px" }} value={status}
                onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All schools</option>
          <option value="true">Active</option>
          <option value="false">Disabled</option>
        </select>
      </div>
      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || problem} />
      <div className="card" style={{ padding: 0 }}>
        {loading && rows.length === 0 ? <Loading what="schools" /> : rows.length === 0 ? <Empty message="No schools match." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>School</th><th>Staff</th><th>Students</th><th>Readers</th>
                <th>Taps, 30 d</th><th>Last activity</th><th>Status</th><th /></tr></thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id}>
                    <td><button className="link-btn" onClick={() => setOpened(o.id)}><strong>{o.name}</strong></button>
                      <small className="faint" style={{ display: "block" }}>
                        {o.slug}{o.address ? ` · ${o.address}` : ""}
                      </small></td>
                    <td>{o.member_count}</td>
                    <td>{o.student_count}</td>
                    <td>{o.device_count}</td>
                    <td>{o.taps_30d}</td>
                    <td className="muted">{ago(o.last_tap && o.last_action
                      ? (o.last_tap > o.last_action ? o.last_tap : o.last_action)
                      : o.last_tap || o.last_action)}</td>
                    <td><StatusPill active={o.active} /></td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn-ghost btn-sm" onClick={() => setOpened(o.id)}>Details</button>{" "}
                      {o.active && <><button className="btn-ghost btn-sm" onClick={() => openSchool(o.slug)}>Open</button>{" "}</>}
                      <button className="btn-ghost btn-sm" onClick={() => toggle(o)}>{o.active ? "Disable" : "Enable"}</button>{" "}
                      <button className="btn-ghost btn-sm danger" onClick={() => remove(o)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
      {opened && <SchoolDetail id={opened} onClose={() => setOpened(null)} onChanged={load} />}
    </>
  );
}

// ---------------- users ----------------

function EditUser({ user, onClose, onChanged }) {
  const { user: me } = useAuth();
  const [form, setForm] = useState({
    first_name: user.first_name, last_name: user.last_name,
    username: user.username, email: user.email, is_superuser: user.is_superuser,
  });
  const [memberships, setMemberships] = useState(user.memberships);
  const [schools, setSchools] = useState([]);
  const [add, setAdd] = useState({ org: "", role: "lecturer" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");
  const self = user.id === me?.id;

  useEffect(() => {
    api.get("/api/platform/orgs/", { params: { page_size: 200, ordering: "name" } })
      .then((r) => setSchools(r.data.results)).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function run(fn, message) {
    setBusy(true); setError(null); setFlash("");
    try { await fn(); if (message) setFlash(message); onChanged(); }
    catch (err) { setError(err); }
    finally { setBusy(false); }
  }

  const save = (e) => {
    e.preventDefault();
    run(() => api.patch(`/api/platform/users/${user.id}/`, form), "Saved.");
  };

  const changeRole = (m, role) => run(async () => {
    await api.patch(`/api/platform/memberships/${m.id}/`, { role });
    setMemberships(memberships.map((x) => (x.id === m.id ? { ...x, role } : x)));
  }, `Now ${ROLE_LABEL[role].toLowerCase()} in ${m.org_name}.`);

  const removeFrom = (m) => {
    if (!window.confirm(`Take ${user.username} out of ${m.org_name}?`)) return;
    run(async () => {
      await api.delete(`/api/platform/memberships/${m.id}/`);
      setMemberships(memberships.filter((x) => x.id !== m.id));
    }, `Removed from ${m.org_name}.`);
  };

  const addTo = () => run(async () => {
    const r = await api.post(`/api/platform/users/${user.id}/add_membership/`, add);
    setMemberships(r.data.memberships);
    setAdd({ org: "", role: "lecturer" });
  }, "Added to the school.");

  const inSchool = new Set(memberships.map((m) => m.org));

  return (
    <Modal title={`Edit ${user.username}`} onClose={onClose} width={640}>
      <ErrorBox error={error} />
      {flash && <div className="alert alert-ok">{flash}</div>}
      <form onSubmit={save}>
        <div className="form-2">
          <div className="field"><label htmlFor="uf">First name</label>
            <input id="uf" className="input" value={form.first_name} onChange={set("first_name")} /></div>
          <div className="field"><label htmlFor="ul">Last name</label>
            <input id="ul" className="input" value={form.last_name} onChange={set("last_name")} /></div>
          <div className="field"><label htmlFor="uu">Username</label>
            <input id="uu" className="input" value={form.username} onChange={set("username")} /></div>
          <div className="field"><label htmlFor="ue">Email</label>
            <input id="ue" className="input" type="email" value={form.email} onChange={set("email")} /></div>
        </div>
        <label className="row" style={{ fontWeight: 400, marginBottom: 16 }}>
          <input type="checkbox" checked={form.is_superuser} disabled={self}
                 onChange={set("is_superuser")} style={{ flex: "0 0 auto" }} />
          Platform administrator (can see and change every school)
        </label>
        <button className="btn-solid" disabled={busy}>{busy ? "Saving..." : "Save changes"}</button>
      </form>

      <h3 style={{ marginTop: 24 }}>Schools</h3>
      {memberships.length === 0 ? <p className="muted">Not in any school.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>School</th><th>Role</th><th /></tr></thead>
            <tbody>
              {memberships.map((m) => (
                <tr key={m.id}>
                  <td>{m.org_name}{!m.org_active && <> <StatusPill active={false} /></>}</td>
                  <td>
                    <select className="input role-select" value={m.role} disabled={busy}
                            onChange={(e) => changeRole(m, e.target.value)}
                            aria-label={`Role in ${m.org_name}`}>
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </select>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn-ghost btn-sm" disabled={busy} onClick={() => removeFrom(m)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
        <select className="input" style={{ flex: "1 1 200px" }} value={add.org}
                onChange={(e) => setAdd({ ...add, org: e.target.value })} aria-label="School">
          <option value="">Add to a school...</option>
          {schools.filter((s) => !inSchool.has(s.id)).map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select className="input" style={{ flex: "0 0 140px" }} value={add.role}
                onChange={(e) => setAdd({ ...add, role: e.target.value })} aria-label="Role">
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select>
        <button className="btn-ghost" disabled={busy || !add.org} onClick={addTo}>Add</button>
      </div>

      <div className="row" style={{ justifyContent: "flex-end", marginTop: 20 }}>
        <button className="btn-solid" onClick={onClose}>Done</button>
      </div>
    </Modal>
  );
}

function Users() {
  const { user: me } = useAuth();
  const [q, setQ] = useState("");
  const search = useDebounced(q);
  const [status, setStatus] = useState("");
  const { rows, count, page, setPage, loading, error, reload: load } = useList("/api/platform/users/", {
    search: search || undefined,
    is_active: status === "active" ? true : status === "disabled" ? false : undefined,
    is_superuser: status === "platform" ? true : undefined,
  });
  const [editing, setEditing] = useState(null);
  const [resetting, setResetting] = useState(null);
  const [problem, setProblem] = useState(null);
  const [flash, setFlash] = useState("");

  async function toggle(u) {
    if (u.is_active && !window.confirm(`Disable ${u.username}? They are signed out and cannot sign in until re-enabled.`)) return;
    setProblem(null);
    try {
      await api.patch(`/api/platform/users/${u.id}/`, { is_active: !u.is_active });
      setFlash(`${u.is_active ? "Disabled" : "Re-enabled"} ${u.username}.`);
      load();
    } catch (err) { setProblem(err); }
  }

  async function remove(u) {
    if (!window.confirm(`Delete the account ${u.username} for good? Their past actions stay in the audit logs.`)) return;
    setProblem(null);
    try {
      await api.delete(`/api/platform/users/${u.id}/`);
      setFlash(`Deleted ${u.username}.`);
      load();
    } catch (err) { setProblem(err); }
  }

  return (
    <>
      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "1 1 240px", maxWidth: 360 }}
               placeholder="Search name, username, email or school"
               value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search users" />
        <select className="input" style={{ flex: "0 0 180px" }} value={status}
                onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All users</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
          <option value="platform">Platform admins</option>
        </select>
      </div>
      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || problem} />
      <div className="card" style={{ padding: 0 }}>
        {loading && rows.length === 0 ? <Loading what="users" /> : rows.length === 0 ? <Empty message="No users match." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>User</th><th>Schools</th><th>Last signed in</th><th>Joined</th><th>Status</th><th /></tr></thead>
              <tbody>
                {rows.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id}>
                      <td><strong>{u.full_name || u.username}</strong>
                        {u.is_superuser && <span className="pill" style={{ marginLeft: 8 }}>platform admin</span>}
                        {self && <span className="pill" style={{ marginLeft: 8 }}>you</span>}
                        <small className="faint" style={{ display: "block" }}>
                          {u.username}{u.email ? ` · ${u.email}` : ""}
                        </small></td>
                      <td>{u.memberships.length === 0 ? <span className="faint">none</span> :
                        u.memberships.map((m) => (
                          <div key={m.id} style={{ fontSize: 14 }}>
                            {m.org_name} <span className="faint">· {ROLE_LABEL[m.role]}</span>
                          </div>
                        ))}</td>
                      <td className="muted">{ago(u.last_login)}</td>
                      <td className="muted">{new Date(u.date_joined).toLocaleDateString()}</td>
                      <td><StatusPill active={u.is_active} /></td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button className="btn-ghost btn-sm" onClick={() => setEditing(u)}>Edit</button>{" "}
                        <button className="btn-ghost btn-sm" onClick={() => setResetting(u)}>Password</button>{" "}
                        {!self && <>
                          <button className="btn-ghost btn-sm" onClick={() => toggle(u)}>{u.is_active ? "Disable" : "Enable"}</button>{" "}
                          <button className="btn-ghost btn-sm danger" onClick={() => remove(u)}>Delete</button>
                        </>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
      {editing && <EditUser user={editing} onClose={() => { setEditing(null); load(); }} onChanged={() => {}} />}
      {resetting && <ResetPassword member={{ ...resetting, full_name: resetting.full_name }}
                                   url={`/api/platform/users/${resetting.id}/set_password/`}
                                   onClose={() => setResetting(null)} onDone={() => setResetting(null)} />}
    </>
  );
}

// ---------------- readers ----------------

function Readers() {
  const [q, setQ] = useState("");
  const search = useDebounced(q);
  const { rows, count, page, setPage, loading, error, reload: load } = useList("/api/platform/devices/", { search: search || undefined });
  const [problem, setProblem] = useState(null);
  const [flash, setFlash] = useState("");

  async function remove(d) {
    if (!window.confirm(`Remove ${d.name} from ${d.org_name}? It stops working straight away and can then be paired to any school.`)) return;
    setProblem(null);
    try {
      await api.delete(`/api/platform/devices/${d.id}/`);
      setFlash(`Removed ${d.name}.`);
      load();
    } catch (err) { setProblem(err); }
  }

  return (
    <>
      <div className="row filters">
        <input className="input" style={{ flex: "1 1 240px", maxWidth: 360 }}
               placeholder="Search reader, hardware ID or school"
               value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search readers" />
      </div>
      {flash && <div className="alert alert-ok">{flash}</div>}
      <ErrorBox error={error || problem} />
      <div className="card" style={{ padding: 0 }}>
        {loading && rows.length === 0 ? <Loading what="readers" /> : rows.length === 0 ? <Empty message="No readers." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Reader</th><th>School</th><th>Venue</th><th>Status</th>
                <th>Taps, 30 d</th><th>Firmware</th><th /></tr></thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td><strong>{d.name}</strong>
                      <small className="faint mono" style={{ display: "block" }}>{d.hardware_id}</small></td>
                    <td>{d.org_name}</td>
                    <td>{d.venue_code || <span className="faint">not placed</span>}</td>
                    <td><StatusPill active={d.online} on="online" off={`seen ${ago(d.last_seen)}`} />
                      {d.queue_depth > 0 && <small className="faint" style={{ display: "block" }}>{d.queue_depth} taps waiting</small>}</td>
                    <td>{d.taps_30d}</td>
                    <td className="muted mono">{d.firmware || "-"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn-ghost btn-sm danger" onClick={() => remove(d)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
    </>
  );
}

// ---------------- activity ----------------

function Activity() {
  const [q, setQ] = useState("");
  const search = useDebounced(q);
  const [org, setOrg] = useState("");
  const [schools, setSchools] = useState([]);
  const { rows, count, page, setPage, loading, error } = useList("/api/platform/activity/", {
    search: search || undefined, org: org || undefined,
  });

  useEffect(() => {
    api.get("/api/platform/orgs/", { params: { page_size: 200, ordering: "name" } })
      .then((r) => setSchools(r.data.results)).catch(() => {});
  }, []);

  return (
    <>
      <div className="row filters" style={{ flexWrap: "wrap" }}>
        <input className="input" style={{ flex: "1 1 240px", maxWidth: 360 }}
               placeholder="Search who or what" value={q}
               onChange={(e) => setQ(e.target.value)} aria-label="Search activity" />
        <select className="input" style={{ flex: "0 0 220px" }} value={org}
                onChange={(e) => setOrg(e.target.value)} aria-label="School">
          <option value="">Every school</option>
          {schools.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
      <ErrorBox error={error} />
      <div className="card" style={{ padding: 0 }}>
        {loading && rows.length === 0 ? <Loading what="activity" /> : rows.length === 0 ? <Empty message="Nothing recorded." /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>School</th><th>Done by</th><th>Action taken</th></tr></thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }} title={a.ip || ""}>{when(a.created_at)}</td>
                    <td>{a.org_name}</td>
                    <td>{a.actor_name || <span className="faint">-</span>}</td>
                    <td>{a.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Pager page={page} setPage={setPage} count={count} />
    </>
  );
}

export default function Platform() {
  const { tab = "overview" } = useParams();
  const { isPlatformAdmin } = useAuth();
  if (!isPlatformAdmin) return <Navigate to="/dashboard" replace />;
  if (!TABS.some((t) => t.id === tab)) return <Navigate to="/platform" replace />;

  return (
    <>
      <PageHead title="Platform admin" subtitle="Every school, user and reader in SLAMS" />
      <nav className="tabs" aria-label="Platform sections">
        {TABS.map((t) => (
          <NavLink key={t.id} to={t.id === "overview" ? "/platform" : `/platform/${t.id}`} end
                   className={({ isActive }) => (isActive ? "on" : "")}>{t.label}</NavLink>
        ))}
      </nav>
      {tab === "overview" && <Overview />}
      {tab === "schools" && <Schools />}
      {tab === "users" && <Users />}
      {tab === "readers" && <Readers />}
      {tab === "activity" && <Activity />}
    </>
  );
}

