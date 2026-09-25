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
  // fetch a bundled sample from /public/samples and send it through the real
  // upload pipeline — same code path as a user-provided file
  uploadSample: async (filename) => {
    const res = await fetch(`${import.meta.env.BASE_URL}samples/${filename}`);
    if (!res.ok) throw new Error(`Sample ${filename} not found (${res.status})`);
    const blob = await res.blob();
    return api.upload(new File([blob], filename, { type: blob.type }));
  },
};

export const sampleUrl = (filename) => `${import.meta.env.BASE_URL}samples/${filename}`;

export const inr = (n) =>
  n === null || n === undefined
    ? "–"
    : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
