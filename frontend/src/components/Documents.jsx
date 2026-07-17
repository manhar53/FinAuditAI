import { useEffect, useRef, useState } from "react";
import { api, inr } from "../api.js";

function DocumentDetail({ id }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.documentDetail(id).then(setDetail).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!detail) return <p className="empty">Loading…</p>;

  return (
    <div className="doc-detail">
      {detail.line_items.length > 0 && (
        <>
          <div className="detail-title">Line items</div>
          <table>
            <thead>
              <tr>
                <th>Description</th>
                <th className="num">Qty</th>
                <th className="num">Unit price</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {detail.line_items.map((li) => (
                <tr key={li.id}>
                  <td>{li.description}</td>
                  <td className="num">{li.quantity ?? "–"}</td>
                  <td className="num">{li.unit_price != null ? inr(li.unit_price) : "–"}</td>
                  <td className="num">{li.amount != null ? inr(li.amount) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="detail-title">Anomalies on this document</div>
      {detail.anomalies.length === 0 ? (
        <p style={{ color: "var(--text-secondary)" }}>None — passed all checks.</p>
      ) : (
        detail.anomalies.map((a) => (
          <div key={a.id} className="doc-anomaly">
            <span className={`sev ${a.severity}`} /> {a.explanation}
          </div>
        ))
      )}
    </div>
  );
}

export default function Documents({ version, onChanged }) {
  const [docs, setDocs] = useState([]);
  const [vendor, setVendor] = useState("");
  const [status, setStatus] = useState("All");
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState(null);

  const fileInput = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [uploadLog, setUploadLog] = useState([]);

  useEffect(() => {
    api
      .documents({ vendor, status })
      .then((d) => { setDocs(d); setError(null); })
      .catch((e) => setError(e.message));
  }, [vendor, status, version]);

  async function handleUpload() {
    const files = Array.from(fileInput.current?.files || []);
    if (!files.length) return;
    setUploading(true);
    setUploadLog([]);
    for (const file of files) {
      try {
        const res = await api.upload(file);
        setUploadLog((log) => [
          ...log,
          { name: file.name, ok: true, flagged: res.anomalies_flagged, summaries: res.anomaly_summaries },
        ]);
      } catch (e) {
        setUploadLog((log) => [...log, { name: file.name, ok: false, error: e.message }]);
      }
    }
    setUploading(false);
    fileInput.current.value = "";
    onChanged();
  }

  return (
    <>
      <section className="panel" style={{ marginBottom: 16 }}>
        <h2>Upload documents</h2>
        <p style={{ color: "var(--text-secondary)", marginBottom: 10 }}>
          Invoice PDFs (with a text layer) or expense-report CSVs. Each file runs through
          extraction and all five anomaly checks; results appear below immediately.
        </p>
        <div className="filters" style={{ marginBottom: uploadLog.length ? 12 : 0 }}>
          <input type="file" ref={fileInput} multiple accept=".pdf,.csv" />
          <button className="btn btn-primary" onClick={handleUpload} disabled={uploading}>
            {uploading ? "Processing… (LLM extraction, ~1 min per PDF)" : "Process"}
          </button>
        </div>
        {uploadLog.map((r, i) => (
          <div key={i} className="upload-result">
            {r.ok ? (
              <>
                {r.flagged > 0 ? "🚩" : "✓"} {r.name}
                {r.flagged > 0 && ` — ${r.flagged} anomal${r.flagged === 1 ? "y" : "ies"}`}
                {r.summaries?.map((s, j) => (
                  <div key={j} className="expl">{s}</div>
                ))}
              </>
            ) : (
              <span className="error">{r.name}: {r.error}</span>
            )}
          </div>
        ))}
      </section>

      <div className="filters">
        <div>
          <label>Vendor contains</label>
          <input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="e.g. Acme" />
        </div>
        <div>
          <label>Status</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["All", "processed", "needs_review", "failed"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {docs.length === 0 ? (
        <p className="empty">No documents yet — upload PDFs or CSVs above.</p>
      ) : (
        <section className="panel">
          <p style={{ color: "var(--text-secondary)", marginBottom: 8 }}>
            Click a row to see line items and flags. The “Extraction” column records how each
            document was parsed — LLM, deterministic parser, or both.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>File</th>
                  <th>Vendor</th>
                  <th>Invoice no</th>
                  <th>Date</th>
                  <th className="num">Amount (₹)</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Extraction</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <>
                    <tr
                      key={d.id}
                      className="clickable"
                      onClick={() => setExpanded(expanded === d.id ? null : d.id)}
                    >
                      <td>{d.id}</td>
                      <td>{d.filename}</td>
                      <td>{d.vendor_name}</td>
                      <td>{d.invoice_number || "–"}</td>
                      <td>{d.invoice_date || "–"}</td>
                      <td className="num">{d.total_amount != null ? inr(d.total_amount) : "–"}</td>
                      <td>{d.category}</td>
                      <td>
                        <span className={`badge ${d.status === "needs_review" ? "badge-flag" : ""}`}>
                          {d.status === "needs_review" ? "needs review" : d.status}
                        </span>
                      </td>
                      <td><span className="badge">{d.extraction_method}</span></td>
                    </tr>
                    {expanded === d.id && (
                      <tr key={`${d.id}-detail`}>
                        <td colSpan={9}>
                          <DocumentDetail id={d.id} />
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
