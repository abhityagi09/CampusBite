import axios from "axios";

export const TOKEN_KEY = "campusbite.token";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1",
  timeout: 15000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let unauthorizedHandler = null;
/** Called once when a request made WITH a token comes back 401 (expired / revoked). */
export const setUnauthorizedHandler = (fn) => {
  unauthorizedHandler = fn;
};

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const hadToken = Boolean(err.config?.headers?.Authorization);
    if (err.response?.status === 401 && hadToken && !err.config.url.includes("/auth/login")) {
      unauthorizedHandler?.();
    }
    return Promise.reject(err);
  }
);

const fieldOf = (loc = []) => loc.filter((p) => p !== "body" && p !== "query").join(".");

/** Human-readable message from any backend / network error. */
export function errorMessage(err) {
  if (!err) return "";
  if (!err.response) return "Cannot reach the server. Check your connection and try again.";
  const data = err.response.data || {};
  if (Array.isArray(data.errors) && data.errors.length) {
    return data.errors.map((e) => `${fieldOf(e.loc) || "Request"}: ${e.msg.replace(/^Value error, /, "")}`).join(" · ");
  }
  if (typeof data.detail === "string") return data.detail;
  return `Request failed (${err.response.status})`;
}

/** { field: message } from a 422 validation error, for inline form errors. */
export function fieldErrors(err) {
  const out = {};
  for (const e of err?.response?.data?.errors || []) {
    const f = fieldOf(e.loc);
    if (f && !out[f]) out[f] = e.msg.replace(/^Value error, /, "");
  }
  return out;
}

export const statusOf = (err) => err?.response?.status;
