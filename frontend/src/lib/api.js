import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
});

// Attach the access token to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const org = localStorage.getItem("org");
  if (org) config.headers["X-Org"] = org;
  return config;
});

// On a 401, try the refresh token once before giving up. Without this a
// user is thrown back to the login page every time the access token
// expires, which is every few minutes.
let refreshing = null;

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status !== 401 || original._retried) {
      return Promise.reject(error);
    }
    const refresh = localStorage.getItem("refresh");
    if (!refresh) {
      logout();
      return Promise.reject(error);
    }
    original._retried = true;
    try {
      refreshing =
        refreshing ||
        axios.post(`${api.defaults.baseURL}/api/auth/refresh/`, { refresh });
      const { data } = await refreshing;
      refreshing = null;
      localStorage.setItem("access", data.access);
      original.headers.Authorization = `Bearer ${data.access}`;
      return api(original);
    } catch (e) {
      refreshing = null;
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
