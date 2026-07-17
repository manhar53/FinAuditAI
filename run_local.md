# Exact commands to run FinAudit AI on this machine (Windows)

One-time setup is already done (`.venv` exists, sample data generated).

## Terminal 1 — API
```powershell
cd C:\Users\manha\FinAuditAI\backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
Check: http://localhost:8000/health (shows which LLM provider is live)
API docs: http://localhost:8000/docs

## Terminal 2 — React frontend
```powershell
cd C:\Users\manha\FinAuditAI\frontend
npm run dev
```
Opens http://localhost:5173 — the chatbot lives bottom-right on every tab.

## Demo flow
1. Make sure Ollama is running (`ollama list` should respond).
2. Documents tab: upload files from `sample_data\invoices\` and
   `sample_data\expenses.csv`, click **Process**.
3. Overview tab: metrics + charts populate.
4. Anomalies tab: compare against `sample_data\PLANTED_ANOMALIES.md` (the answer key);
   click "Show evidence" on a flag, try the Reviewed/Dismiss buttons.
5. Chatbot (bottom-right): try the example questions.
6. Score the system: `..\.venv\Scripts\python sample_data\evaluate.py`
   (detection precision/recall + extraction field accuracy).

## Reset the database
Stop the API, delete `backend\finaudit.db`, restart the API.

## Tests
```powershell
cd C:\Users\manha\FinAuditAI\backend
..\.venv\Scripts\python -m pytest tests -q
```
