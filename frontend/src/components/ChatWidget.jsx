import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const EXAMPLES = [
  "Which vendor had the most flagged invoices this month?",
  "Show me all anomalies above ₹50,000",
  "How much did we spend by category?",
  "Why was Acme IT Solutions flagged?",
];

const STORAGE_KEY = "finaudit-chat";

function RowsTable({ rows }) {
  if (!rows?.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="table-wrap chat-rows">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 8).map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{typeof r[c] === "number" ? r[c].toLocaleString("en-IN") : String(r[c] ?? "–")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 8 && <div className="chat-more">…and {rows.length - 8} more rows</div>}
    </div>
  );
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [chat, setChat] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
    } catch {
      return [];
    }
  });
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chat.slice(-40)));
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat, open]);

  async function submit(q) {
    const text = (q || question).trim();
    if (!text || busy) return;
    setQuestion("");
    setBusy(true);
    setChat((c) => [...c, { role: "user", content: text }]);
    try {
      const res = await api.query(text);
      setChat((c) => [...c, { role: "assistant", content: res.answer, rows: res.rows, tool: res.tool_used }]);
    } catch (e) {
      setChat((c) => [...c, { role: "assistant", content: `Query failed: ${e.message}` }]);
    }
    setBusy(false);
  }

  if (!open) {
    return (
      <button className="chat-fab" onClick={() => setOpen(true)} title="Ask FinAudit">
        Ask FinAudit
      </button>
    );
  }

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <strong>Ask FinAudit</strong>
        <div>
          {chat.length > 0 && (
            <button className="btn btn-sm" onClick={() => setChat([])} style={{ marginRight: 6 }}>
              Clear
            </button>
          )}
          <button className="btn btn-sm" onClick={() => setOpen(false)}>Close</button>
        </div>
      </div>

      <div className="chat-body">
        {chat.length === 0 && (
          <div className="chat-empty">
            <p>Ask about vendors, spend or flagged anomalies. Try:</p>
            {EXAMPLES.map((ex) => (
              <button key={ex} className="btn btn-sm chat-example" onClick={() => submit(ex)} disabled={busy}>
                {ex}
              </button>
            ))}
          </div>
        )}
        {chat.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.content}
            <RowsTable rows={m.rows} />
            {m.tool && <div className="tool">tool: {m.tool}</div>}
          </div>
        ))}
        {busy && <div className="msg">Thinking… (local model, ~5–15s)</div>}
        <div ref={bottomRef} />
      </div>

      <div className="ask-row chat-input">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="e.g. total spend on travel this year"
          autoFocus
        />
        <button className="btn btn-primary" onClick={() => submit()} disabled={busy}>
          Ask
        </button>
      </div>
    </div>
  );
}
