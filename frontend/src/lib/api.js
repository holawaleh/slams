import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
  timeout: 30000,
});

// Login, sign-up, refresh and invite acceptance. These are how a session
// starts, so an old session must never be sent with them or be allowed
// to end in a redirect to the login page.
const isAuthCall = (config) => (config.url || "").includes("/api/auth/");

// Seconds until a JWT expires, read from its payload. The signature is
// the server's business; this is only for knowing when to renew.
function secondsLeft(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const { exp } = JSON.parse(atob(part));
    return exp - Date.now() / 1000;
  } catch {
    return -1;
  }
}

// One renewal at a time, however many requests are waiting on it.
let renewing = null;
function renew() {
  const refresh = localStorage.getItem("refresh");
  if (!refresh) return Promise.reject(new Error("no refresh token"));
  renewing = renewing || axios
    .post(`${api.defaults.baseURL}/api/auth/refresh/`, { refresh })
    .then(({ data }) => {
      localStorage.setItem("access", data.access);
      if (data.refresh) localStorage.setItem("refresh", data.refresh);
      return data.access;
    })
    .finally(() => { renewing = null; });
  return renewing;
}

// Attach the access token to every request, renewing it first when it is
// about to run out. Renewing ahead of time means requests do not fail
// with a 401 first, which is what filled the browser console before.
api.interceptors.request.use(async (config) => {
  if (isAuthCall(config)) return config;
  let token = localStorage.getItem("access");
  if (token && secondsLeft(token) < 60 && localStorage.getItem("refresh")) {
    try {
      token = await renew();
    } catch {
      /* the response handler below deals with a dead session */
    }
  }
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const org = localStorage.getItem("org");
  if (org) config.headers["X-Org"] = org;
  return config;
});

// A 401 can still happen (the server was restarted with a new key, the
// laptop slept past the expiry). Renew once and retry; if that fails the
// session is over.
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    // A 401 from login means a wrong password, not an expired session:
    // hand it back to the form instead of reloading the page.
    if (!original || error.response?.status !== 401 || original._retried ||
        isAuthCall(original)) {
      return Promise.reject(error);
    }
    original._retried = true;
    try {
      const access = await renew();
      original.headers.Authorization = `Bearer ${access}`;
      return api(original);
    } catch (e) {
      logout();
      return Promise.reject(e);
    }
  }
);

export function logout() {
  localStorage.removeItem("access");
  localStorage.removeItem("refresh");
  localStorage.removeItem("org");
  window.location.href = "/login";
}

export default api;
