"""Score the system against the generator's answer keys.

Run AFTER uploading all sample files:
    python sample_data/evaluate.py [--api http://localhost:8000]

Two sections:
  1. Detection (planted.json): precision/recall of anomaly flags. An "extra"
     detection counts as a false positive against the key, but each is listed
     so you can judge whether it's a mistake or a defensible catch.
  2. Extraction (ground_truth.json): field-level accuracy of what the
     Extraction Agent pulled out of each PDF/CSV row vs the true values the
     generator wrote into them. This is what makes the LLM extraction claim
     measurable instead of anecdotal.
"""
import argparse
import json
from pathlib import Path

import httpx

HERE = Path(__file__).parent


def match_key(rule_code: str, invoice_number: str | None, filename: str | None):
    return (rule_code, invoice_number or filename)


FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_amount", "category"]


def field_matches(field: str, truth, extracted) -> bool:
    if truth is None and extracted is None:
        return True
    if truth is None or extracted is None:
        return False
    if field == "total_amount":
        return abs(float(truth) - float(extracted)) < 0.01
    if field in ("vendor_name", "category"):
        return str(truth).strip().lower() == str(extracted).strip().lower()
    return str(truth).strip() == str(extracted).strip()


def extraction_report(documents: list[dict]):
    gt = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))
    pdf_docs = {d["filename"]: d for d in documents if d["file_type"] == "pdf"}
    csv_docs = {d["invoice_number"]: d for d in documents if d["file_type"] == "csv"}

    correct = {f: 0 for f in FIELDS}
    total = {f: 0 for f in FIELDS}
    mismatches = []

    def compare(label: str, truth: dict, doc: dict, fields):
        for f in fields:
            total[f] += 1
            if field_matches(f, truth.get(f), doc.get(f)):
                correct[f] += 1
            else:
                mismatches.append(f"{label} .{f}: expected {truth.get(f)!r}, got {doc.get(f)!r}")

    missing = 0
    for filename, truth in gt["pdfs"].items():
        doc = pdf_docs.get(filename)
        if not doc:
            missing += 1
            continue
        compare(filename, truth, doc, FIELDS)
    for ref, truth in gt["csv_rows"].items():
        doc = csv_docs.get(ref)
        if not doc:
            missing += 1
            continue
        compare(f"expenses.csv[{ref}]", truth, doc, ["vendor_name", "invoice_date", "total_amount", "category"])

    print("\n--- Extraction accuracy (vs ground_truth.json) ---")
    if missing:
        print(f"  ({missing} ground-truth files/rows not found in the DB — upload all samples first)")
    for f in FIELDS:
        if total[f]:
            print(f"  {f:<15} {correct[f]}/{total[f]}  ({correct[f] / total[f]:.0%})")
    overall_c, overall_t = sum(correct.values()), sum(total.values())
    if overall_t:
        print(f"  {'OVERALL':<15} {overall_c}/{overall_t}  ({overall_c / overall_t:.0%})")
    for m in mismatches:
        print(f"  MISMATCH: {m}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()

    expected = json.loads((HERE / "planted.json").read_text(encoding="utf-8"))
    anomalies = httpx.get(f"{args.api}/anomalies", params={"limit": 1000}, timeout=30).json()
    documents = httpx.get(f"{args.api}/documents", params={"limit": 1000}, timeout=30).json()
    doc_by_id = {d["id"]: d for d in documents}

    detections = {}
    for a in anomalies:
        doc = doc_by_id.get(a["document_id"], {})
        key = match_key(a["rule_code"], doc.get("invoice_number"), doc.get("filename"))
        detections.setdefault(key, []).append(a)

    tp, fn = [], []
    for exp in expected:
        key = match_key(exp["rule_code"], exp.get("invoice_number"), exp.get("filename"))
        (tp if key in detections else fn).append(exp)
        detections.pop(key, None)
    fp = [a for hits in detections.values() for a in hits]

    precision = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 0.0
    recall = len(tp) / len(expected) if expected else 0.0

    print(f"Planted anomalies: {len(expected)}")
    print(f"Caught (TP): {len(tp)}   Missed (FN): {len(fn)}   Extra (FP): {len(fp)}")
    print(f"Precision: {precision:.2f}   Recall: {recall:.2f}\n")

    for e in fn:
        print(f"  MISSED: {e}")
    for a in fp:
        doc = doc_by_id.get(a["document_id"], {})
        print(f"  EXTRA:  [{a['rule_code']}] {doc.get('filename')} — {a['explanation']}")

    if not fn and not fp:
        print("Perfect score: every planted anomaly caught, no extra flags.")

    extraction_report(documents)


if __name__ == "__main__":
    main()
