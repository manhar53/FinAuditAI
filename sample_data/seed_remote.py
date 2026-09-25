"""Populate a running FinAudit API with the bundled sample documents.

Useful after a fresh deploy (the free Render tier resets its SQLite database on
every redeploy) so first-time visitors land on a populated dashboard instead of
empty charts.

Reads the sample files committed under frontend/public/samples, so it works from
a clean clone without regenerating anything. Paced to stay under the Gemini
free-tier rate limit; the API also retries 429s on its side.

    python sample_data/seed_remote.py --api https://your-api.onrender.com
"""
import argparse
import time
from pathlib import Path

import httpx

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "samples"

# order matters: build vendor history before the outlier/duplicate checks run
ORDER = [
    "INV-AI-1001.pdf", "INV-AI-1002.pdf", "INV-AI-1003.pdf", "INV-AI-1004.pdf",
    "INV-AI-1005.pdf", "INV-AI-1006.pdf", "INV-AI-1007.pdf",
    "INV-AI-1007_resubmitted.pdf", "INV-AI-1008.pdf",
    "INV-NC-1001.pdf", "INV-NC-1002.pdf", "INV-NC-1003.pdf", "INV-NC-1004.pdf",
    "INV-NC-1005.pdf", "INV-NC-1006.pdf",
    "INV-OS-1001.pdf", "INV-OS-1002.pdf", "INV-OS-1003.pdf", "INV-OS-1004.pdf",
    "INV-OS-1005.pdf", "INV-OS-1006.pdf", "INV-OS-1007.pdf",
    "INV-ST-1001.pdf", "INV-ST-1002.pdf", "INV-ST-1003.pdf", "INV-ST-1004.pdf",
    "INV-ST-1005.pdf", "INV-ST-1006.pdf", "INV-ST-1007.pdf",
    "nimbus_tax_invoice_0071.pdf", "officemart_memo_jul22.pdf",
    "officemart_no_number.pdf", "skyline_travel_invoice_088.pdf",
    "expenses.csv",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--pace", type=float, default=4.0, help="seconds between uploads")
    args = ap.parse_args()

    files = [SAMPLES_DIR / name for name in ORDER if (SAMPLES_DIR / name).exists()]
    total_docs = total_anoms = failures = 0
    start = time.time()

    for i, path in enumerate(files, 1):
        try:
            r = httpx.post(
                f"{args.api}/documents/upload",
                files={"file": (path.name, path.read_bytes())},
                timeout=180.0,
            )
            r.raise_for_status()
            res = r.json()
            total_docs += res["documents_created"]
            total_anoms += res["anomalies_flagged"]
            flag = f" -> {res['anomalies_flagged']} anomaly(ies)" if res["anomalies_flagged"] else ""
            print(f"[{i}/{len(files)}] {path.name}: {res['documents_created']} doc(s){flag}", flush=True)
        except Exception as e:
            failures += 1
            print(f"[{i}/{len(files)}] {path.name}: FAILED - {e}", flush=True)
        time.sleep(args.pace)

    print(f"\nDone in {time.time() - start:.0f}s: {total_docs} documents, "
          f"{total_anoms} anomalies, {failures} failures", flush=True)


if __name__ == "__main__":
    main()
