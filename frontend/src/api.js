// Single access point to the FastAPI backend. The frontend never knows
// anything about the database or agents — only these HTTP endpoints.
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body.slice(0, 200)}`);
  }
  return res.json();
}

const qs = (params) => {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== "All")
  );
  const s = new URLSearchParams(clean).toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => request("/health"),
  summary: () => request("/stats/summary"),
  trends: () => request("/stats/trends"),
  breakdown: (by) => request(`/stats/breakdown?by=${by}`),
  documents: (filters = {}) => request(`/documents${qs(filters)}`),
  documentDetail: (id) => request(`/documents/${id}`),
  anomalies: (filters = {}) => request(`/anomalies${qs(filters)}`),
  updateAnomaly: (id, status) =>
    request(`/anomalies/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),
  query: (question) =>
    request("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/documents/upload", { method: "POST", body: form });
  },
};

export const inr = (n) =>
  n === null || n === undefined
    ? "–"
    : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
