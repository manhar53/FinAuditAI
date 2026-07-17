import { useEffect, useState } from "react";
import { api } from "../api.js";

const RULE_LABELS = {
  DUPLICATE_INVOICE: "Duplicate invoice",
  AMOUNT_OUTLIER: "Amount outlier",
  MISSING_FIELD: "Missing field",
  DATE_INCONSISTENT: "Date inconsistent",
  CATEGORY_MISMATCH: "Category mismatch",
};

const DETAIL_LABELS = {
  median: "Typical amount (median)",
  mad: "Spread (MAD)",
  effective_mad: "Spread used (after floor)",
  n: "History size",
  scope: "Compared against",
  duplicate_of_document_id: "Duplicate of document #",
  missing_fields: "Missing fields",
  declared: "Declared category",
  suggested: "Suggested category",
  invoice_date: "Invoice date",
};

function Evidence({ details }) {
  const entries = Object.entries(details || {}).filter(([k]) => k !== "keyword_votes");
  if (!entries.length) return null;
  return (
    <div className="evidence">
      {entries.map(([k, v]) => (
        <div key={k} className="evidence-row">
          <span className="evidence-key">{DETAIL_LABELS[k] || k}</span>
          <span>
            {typeof v === "number"
              ? v.toLocaleString("en-IN")
              : Array.isArray(v)
                ? v.join(", ")
                : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function Anomalies({ version, onChanged }) {
  const [rows, setRows] = useState([]);
  const [severity, setSeverity] = useState("All");
  const [rule, setRule] = useState("All");
  const [triage, setTriage] = useState("open");
  const [minAmount, setMinAmount] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .anomalies({ severity, rule_code: rule, status: triage, min_amount: minAmount || undefined })
      .then((r) => { setRows(r); setError(null); })
      .catch((e) => setError(e.message));
  }, [severity, rule, triage, minAmount, version]);

  async function setStatus(id, status) {
    await api.updateAnomaly(id, status);
    onChanged();
  }

  const counts = rows.reduce((acc, a) => ({ ...acc, [a.severity]: (acc[a.severity] || 0) + 1 }), {});

  return (
    <>
      <div className="filters">
        <div>
          <label>Severity</label>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {["All", "high", "medium", "low"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label>Rule</label>
          <select value={rule} onChange={(e) => setRule(e.target.value)}>
            <option>All</option>
            {Object.keys(RULE_LABELS).map((r) => (
              <option key={r} value={r}>{RULE_LABELS[r]}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Triage status</label>
          <select value={triage} onChange={(e) => setTriage(e.target.value)}>
            {["open", "reviewed", "dismissed", "All"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label>Min document amount (₹)</label>
          <input
            type="number"
            value={minAmount}
            onChange={(e) => setMinAmount(e.target.value)}
            placeholder="0"
            style={{ width: 140 }}
          />
        </div>
        <div className="sev-counts">
          {["high", "medium", "low"].map((s) =>
            counts[s] ? (
              <span key={s} className="badge">
                <span className={`sev ${s}`} style={{ display: "inline-block", marginRight: 4, marginTop: 0 }} />
                {counts[s]} {s}
              </span>
            ) : null
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {rows.length === 0 ? (
        <p className="empty">
          {triage === "open"
            ? "No open anomalies — everything has been triaged, or nothing has been flagged yet."
            : "No anomalies match these filters."}
        </p>
      ) : (
        rows.map((a) => (
          <div className="anomaly" key={a.id}>
            <span className={`sev ${a.severity}`} />
            <div className="body">
              <div className="meta">
                {RULE_LABELS[a.rule_code] || a.rule_code} · {a.severity} · document #{a.document_id}
                {a.score != null && ` · z=${a.score}`} · {a.status}
              </div>
              {a.explanation}
              <div>
                <button
                  className="link-btn"
                  onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                >
                  {expanded === a.id ? "Hide evidence" : "Show evidence"}
                </button>
              </div>
              {expanded === a.id && <Evidence details={a.details} />}
            </div>
            {a.status === "open" && (
              <div className="actions">
                <button className="btn btn-sm" onClick={() => setStatus(a.id, "reviewed")} title="Confirm as a real issue">
                  Reviewed
                </button>
                <button className="btn btn-sm" onClick={() => setStatus(a.id, "dismissed")} title="Mark as a false alarm">
                  Dismiss
                </button>
              </div>
            )}
          </div>
        ))
      )}
    </>
  );
}
