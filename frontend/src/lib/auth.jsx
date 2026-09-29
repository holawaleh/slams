import { createContext, useContext, useEffect, useState } from "react";
import api, { logout as clearSession } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [org, setOrg] = useState(null);
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);

  // On first load, ask the server who we are. The stored token may be
  // expired or revoked, so we never trust it without checking.
  useEffect(() => {
    if (!localStorage.getItem("access")) {
      setLoading(false);
      return;
    }
    api
      .get("/api/me/")
      .then(({ data }) => {
        setUser(data.user);
        setOrg(data.current_org);
        setOrgs(data.organizations || []);
        if (data.current_org) localStorage.setItem("org", data.current_org.slug);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function login(username, password) {
    // The previous user's org may not be one this user belongs to.
    localStorage.removeItem("org");
    const { data } = await api.post("/api/auth/login/", { username, password });
    localStorage.setItem("access", data.access);
    localStorage.setItem("refresh", data.refresh);
    const me = await api.get("/api/me/");
    setUser(me.data.user);
    setOrg(me.data.current_org);
    setOrgs(me.data.organizations || []);
    if (me.data.current_org)
      localStorage.setItem("org", me.data.current_org.slug);
    return me.data;
  }

  async function register(payload) {
    // A new owner starts clean: an org remembered from an earlier
    // session would otherwise ride along on the X-Org header.
    localStorage.removeItem("org");
    const { data } = await api.post("/api/auth/register/", payload);
    localStorage.setItem("access", data.tokens.access);
    localStorage.setItem("refresh", data.tokens.refresh);
    localStorage.setItem("org", data.org.slug);
    const me = await api.get("/api/me/");
    setUser(me.data.user);
    setOrg(me.data.current_org);
    setOrgs(me.data.organizations || []);
    return me.data;
  }

  function logout() {
    setUser(null);
    setOrg(null);
    setOrgs([]);
    clearSession();
  }

  const isPlatformAdmin = !!user?.is_platform_admin;
  const isAdmin = isPlatformAdmin || org?.role === "owner" || org?.role === "admin";

  return (
    <AuthContext.Provider
      value={{ user, org, orgs, loading, isAdmin, isPlatformAdmin,
               login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
