import { useEffect, useState } from "react";
import { api } from "./api.js";
import Anomalies from "./components/Anomalies.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import Documents from "./components/Documents.jsx";
import Overview from "./components/Overview.jsx";

const TABS = ["Overview", "Documents", "Anomalies"];

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(false);
  // bumped after uploads / triage / manual refresh so data tabs refetch
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((v) => v + 1);

  useEffect(() => {
    api.health().then((h) => { setHealth(h); setHealthError(false); }).catch(() => setHealthError(true));
  }, [version]);

  const healthDot = healthError ? "down" : health?.llm_available ? "ok" : "warn";
  const healthText = healthError
    ? "API unreachable"
    : health
      ? health.llm_available
        ? `LLM: ${health.llm_provider}`
        : "no LLM — fallback mode"
      : "connecting…";

  return (
    <>
      <header className="header">
        <h1>FinAudit AI</h1>
        <span className="health">
          <span className={`dot ${healthDot}`} /> {healthText}
        </span>
        <button className="btn btn-sm" onClick={refresh} title="Refetch all data">
          Refresh
        </button>
      </header>
      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      <main className="container">
        {tab === "Overview" && <Overview version={version} />}
        {tab === "Documents" && <Documents version={version} onChanged={refresh} />}
        {tab === "Anomalies" && <Anomalies version={version} onChanged={refresh} />}
      </main>
      <ChatWidget />
    </>
  );
}
