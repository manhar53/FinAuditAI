import { useEffect, useState } from "react";
import { api, sampleUrl } from "../api.js";

const RULE_TAGS = {
  DUPLICATE_INVOICE: "Duplicate",
  AMOUNT_OUTLIER: "Outlier",
  MISSING_FIELD: "Missing field",
  DATE_INCONSISTENT: "Bad date",
  CATEGORY_MISMATCH: "Miscategorised",
};

export default function SampleGallery({ onChanged }) {
  const [manifest, setManifest] = useState(null);
  const [bundleState, setBundleState] = useState(null); // {done, total, anomalies}
  const [busyFile, setBusyFile] = useState(null);
  const [results, setResults] = useState({}); // filename -> {flagged, error}

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}samples/manifest.json`)
      .then((r) => r.json())
      .then(setManifest)
      .catch(() => setManifest({ samples: [], demoBundle: [] }));
  }, []);

  async function loadBundle() {
    const files = manifest.demoBundle;
    setBundleState({ done: 0, total: files.length, anomalies: 0 });
    let anomalies = 0;
    for (let i = 0; i < files.length; i++) {
      try {
        const res = await api.uploadSample(files[i]);
        anomalies += res.anomalies_flagged;
      } catch {
        /* keep going — one bad file shouldn't abort the tour */
      }
      setBundleState({ done: i + 1, total: files.length, anomalies });
    }
    onChanged();
  }

  async function runOne(sample) {
    setBusyFile(sample.file);
    try {
      let flagged = 0;
      // duplicate demo needs the original present first
      if (sample.secondFile) {
        await api.uploadSample(sample.file);
        const res = await api.uploadSample(sample.secondFile);
        flagged = res.anomalies_flagged;
      } else {
        const res = await api.uploadSample(sample.file);
        flagged = res.anomalies_flagged;
      }
      setResults((r) => ({ ...r, [sample.file]: { flagged } }));
      onChanged();
    } catch (e) {
      setResults((r) => ({ ...r, [sample.file]: { error: e.message } }));
    }
    setBusyFile(null);
  }

  if (!manifest) return null;

  return (
    <section className="panel sample-gallery" style={{ marginBottom: 16 }}>
      <h2>Try it with sample data</h2>
      <p style={{ color: "var(--text-secondary)", marginBottom: 12 }}>
        No financial data of your own? Load the bundled demo set to populate the whole
        dashboard, or send one sample at a time to watch a specific check fire. You can
        also download any file and upload it yourself below.
      </p>

      <div className="bundle-row">
        <button className="btn btn-primary" onClick={loadBundle} disabled={!!bundleState && bundleState.done < bundleState.total}>
          {bundleState && bundleState.done < bundleState.total
            ? `Loading… ${bundleState.done}/${bundleState.total}`
            : "Load demo dataset (12 files)"}
        </button>
        {bundleState && (
          <span className="bundle-status">
            {bundleState.done < bundleState.total
              ? `Processing — extraction runs per file, please wait…`
              : `Done — ${bundleState.done} files processed, ${bundleState.anomalies} anomalies flagged. Open the Overview and Anomalies tabs.`}
          </span>
        )}
      </div>

      <div className="sample-grid">
        {manifest.samples.map((s) => {
          const r = results[s.file];
          return (
            <div className="sample-card" key={s.file}>
              <div className="sample-card-head">
                <strong>{s.title}</strong>
                {s.rule && <span className="badge">{RULE_TAGS[s.rule] || s.rule}</span>}
              </div>
              <p className="sample-demo">{s.demonstrates}</p>
              <p className="sample-expect"><span className="sample-expect-label">Expect:</span> {s.expected}</p>
              {s.needsHistory && (
                <p className="sample-note">Tip: load the demo dataset first so this vendor has history to compare against.</p>
              )}
              <div className="sample-actions">
                <button className="btn btn-sm" onClick={() => runOne(s)} disabled={busyFile === s.file}>
                  {busyFile === s.file ? "Running…" : "Run through auditor"}
                </button>
                <a className="btn btn-sm" href={sampleUrl(s.file)} download>
                  Download
                </a>
              </div>
              {r?.flagged !== undefined && (
                <div className="sample-result">
                  {r.flagged > 0 ? `🚩 ${r.flagged} anomaly(ies) flagged` : "✓ processed, no anomalies"}
                </div>
              )}
              {r?.error && <div className="sample-result error">{r.error}</div>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
