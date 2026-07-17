"""Generate demo data: ~25 invoice PDFs + an expense-report CSV.

The data is realistic but synthetic, with anomalies planted on purpose so the
demo has a known answer key (written to PLANTED_ANOMALIES.md):
  - a duplicate invoice (same vendor + invoice number, uploaded twice)
  - a duplicate expense row in the CSV
  - two amount outliers (~5x the vendor's normal range)
  - an invoice with no invoice number (missing field)
  - a future-dated invoice
  - a travel invoice mislabelled as Office Supplies (category mismatch)

Run:  python sample_data/generate_samples.py
"""
import csv
import json
import random
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
INVOICE_DIR = OUT / "invoices"
random.seed(42)

TODAY = date(2026, 7, 15)
BILL_TO = "FinAudit Demo Corp, 12 MG Road, Bengaluru 560001"

# vendor -> (address, category, (normal_min, normal_max))
VENDORS = {
    "Acme IT Solutions": ("4th Floor, Cyber Towers, Hyderabad 500081", "IT Services", (85_000, 110_000)),
    "Nimbus Cloud Services": ("Plot 22, Electronic City, Bengaluru 560100", "Cloud Services", (40_000, 55_000)),
    "Skyline Travels": ("Shop 8, Connaught Place, New Delhi 110001", "Travel", (25_000, 45_000)),
    "OfficeMart Supplies": ("Warehouse 3, Bhiwandi, Thane 421302", "Office Supplies", (8_000, 15_000)),
}

ITEM_POOL = {
    "IT Services": ["Application support retainer", "Bug-fix sprint", "Security patch rollout", "Server maintenance"],
    "Cloud Services": ["Compute instances", "Object storage", "Managed database", "Bandwidth charges"],
    "Travel": ["Flight tickets DEL-BLR", "Hotel accommodation", "Airport transfers", "Travel insurance"],
    "Office Supplies": ["A4 paper cartons", "Printer toner", "Stationery assortment", "Whiteboard markers"],
    "Marketing": ["Social media campaign", "Ad creative design", "Influencer collaboration", "SEO retainer"],
}


def split_total(total: float, n: int) -> list[float]:
    """Split a total into n line-item amounts that sum exactly to it."""
    cuts = sorted(random.sample(range(1, 20), n - 1)) if n > 1 else []
    parts, prev = [], 0
    for c in cuts + [20]:
        parts.append(round(total * (c - prev) / 20, 2))
        prev = c
    parts[-1] = round(total - sum(parts[:-1]), 2)
    return parts


def draw_invoice(path: Path, vendor: str, address: str, inv_no: str | None,
                 inv_date: date, category: str, total: float, item_names: list[str]):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 60

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, vendor)
    c.setFont("Helvetica", 9)
    c.drawString(50, y - 14, address)
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(w - 50, y, "INVOICE")

    y -= 55
    c.setFont("Helvetica", 11)
    if inv_no:
        c.drawString(50, y, f"Invoice No: {inv_no}")
        y -= 16
    c.drawString(50, y, f"Invoice Date: {inv_date.strftime('%d-%m-%Y')}")
    y -= 16
    c.drawString(50, y, f"Bill To: {BILL_TO}")
    y -= 16
    c.drawString(50, y, f"Category: {category}")

    y -= 36
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Description")
    c.drawRightString(360, y, "Qty")
    c.drawRightString(455, y, "Unit Price")
    c.drawRightString(545, y, "Amount")
    c.line(50, y - 4, 545, y - 4)

    c.setFont("Helvetica", 10)
    amounts = split_total(total, len(item_names))
    for name, amt in zip(item_names, amounts):
        y -= 18
        c.drawString(50, y, name)
        c.drawRightString(360, y, "1")
        c.drawRightString(455, y, f"{amt:,.2f}")
        c.drawRightString(545, y, f"{amt:,.2f}")

    y -= 28
    c.line(50, y + 14, 545, y + 14)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(545, y, f"Total: Rs. {total:,.2f}")

    c.setFont("Helvetica", 8)
    c.drawString(50, 50, "Payment due within 30 days. This is a computer-generated invoice.")
    c.save()


def draw_messy_invoice(path: Path, variant: dict):
    """Alternative layouts with labels the regex extractor does NOT know
    ('Bill No', 'Amount Due', spelled-out dates, no Category line) — these
    documents are parseable only via the LLM path."""
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 70
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(w / 2, y, variant["title"])
    y -= 30
    c.setFont("Helvetica-Bold", 13)
    c.drawString(60, y, variant["vendor"])
    c.setFont("Helvetica", 10)
    for line in variant["header_lines"]:
        y -= 16
        c.drawString(60, y, line)
    y -= 30
    for item, amt in variant["items"]:
        c.drawString(70, y, f"- {item}")
        c.drawRightString(520, y, f"{amt:,.2f}")
        y -= 18
    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(60, y, variant["total_line"])
    c.save()


def main():
    INVOICE_DIR.mkdir(exist_ok=True)
    planted: list[str] = []
    expected: list[dict] = []  # machine-readable answer key for evaluate.py
    truth_pdfs: dict[str, dict] = {}   # filename -> true fields (extraction eval)
    truth_csv: dict[str, dict] = {}    # reference_no -> true fields
    counter = {v: 1000 for v in VENDORS}

    def record(filename: str, vendor: str, inv_no, inv_date: date, category, total: float,
               category_on_document: bool = True):
        truth_pdfs[filename] = {
            "vendor_name": vendor,
            "invoice_number": inv_no,
            "invoice_date": inv_date.isoformat(),
            "total_amount": total,
            "category": category,
            "category_on_document": category_on_document,
        }

    def next_no(vendor: str) -> str:
        counter[vendor] += 1
        tag = "".join(word[0] for word in vendor.split()[:2]).upper()
        return f"INV-{tag}-{counter[vendor]}"

    def items_for(category: str, n: int) -> list[str]:
        return random.sample(ITEM_POOL[category], n)

    # --- normal history: 6 invoices per vendor, Jan-Jun 2026 ---
    for vendor, (addr, category, (lo, hi)) in VENDORS.items():
        for month in range(1, 7):
            total = round(random.uniform(lo, hi) / 500) * 500
            d = date(2026, month, random.randint(3, 27))
            no = next_no(vendor)
            draw_invoice(INVOICE_DIR / f"{no}.pdf", vendor, addr, no, d, category,
                         float(total), items_for(category, random.randint(2, 3)))
            record(f"{no}.pdf", vendor, no, d, category, float(total))

    # --- planted anomalies (mostly in July so "this month" queries pop) ---
    acme_addr, acme_cat, _ = VENDORS["Acme IT Solutions"]

    dup_no = next_no("Acme IT Solutions")
    draw_invoice(INVOICE_DIR / f"{dup_no}.pdf", "Acme IT Solutions", acme_addr, dup_no,
                 date(2026, 7, 3), acme_cat, 98_500.0, items_for(acme_cat, 2))
    draw_invoice(INVOICE_DIR / f"{dup_no}_resubmitted.pdf", "Acme IT Solutions", acme_addr, dup_no,
                 date(2026, 7, 3), acme_cat, 98_500.0, items_for(acme_cat, 2))
    planted.append(f"DUPLICATE_INVOICE — {dup_no}.pdf and {dup_no}_resubmitted.pdf share invoice number {dup_no}")
    expected.append({"rule_code": "DUPLICATE_INVOICE", "invoice_number": dup_no})
    record(f"{dup_no}.pdf", "Acme IT Solutions", dup_no, date(2026, 7, 3), acme_cat, 98_500.0)
    record(f"{dup_no}_resubmitted.pdf", "Acme IT Solutions", dup_no, date(2026, 7, 3), acme_cat, 98_500.0)

    out_no = next_no("Acme IT Solutions")
    draw_invoice(INVOICE_DIR / f"{out_no}.pdf", "Acme IT Solutions", acme_addr, out_no,
                 date(2026, 7, 8), acme_cat, 480_000.0, items_for(acme_cat, 3))
    planted.append(f"AMOUNT_OUTLIER — {out_no}.pdf: Rs. 4,80,000 vs Acme's normal Rs. 85k-110k")
    expected.append({"rule_code": "AMOUNT_OUTLIER", "invoice_number": out_no})
    record(f"{out_no}.pdf", "Acme IT Solutions", out_no, date(2026, 7, 8), acme_cat, 480_000.0)

    om_addr, om_cat, _ = VENDORS["OfficeMart Supplies"]
    draw_invoice(INVOICE_DIR / "officemart_no_number.pdf", "OfficeMart Supplies", om_addr, None,
                 date(2026, 7, 6), om_cat, 11_500.0, items_for(om_cat, 2))
    planted.append("MISSING_FIELD — officemart_no_number.pdf has no invoice number")
    expected.append({"rule_code": "MISSING_FIELD", "filename": "officemart_no_number.pdf"})
    record("officemart_no_number.pdf", "OfficeMart Supplies", None, date(2026, 7, 6), om_cat, 11_500.0)

    fut_no = next_no("OfficeMart Supplies")
    draw_invoice(INVOICE_DIR / f"{fut_no}.pdf", "OfficeMart Supplies", om_addr, fut_no,
                 date(2027, 1, 15), om_cat, 12_000.0, items_for(om_cat, 2))
    planted.append(f"DATE_INCONSISTENT — {fut_no}.pdf is dated 15-01-2027 (in the future)")
    expected.append({"rule_code": "DATE_INCONSISTENT", "invoice_number": fut_no})
    record(f"{fut_no}.pdf", "OfficeMart Supplies", fut_no, date(2027, 1, 15), om_cat, 12_000.0)

    sky_addr, _, _ = VENDORS["Skyline Travels"]
    mis_no = next_no("Skyline Travels")
    draw_invoice(INVOICE_DIR / f"{mis_no}.pdf", "Skyline Travels", sky_addr, mis_no,
                 date(2026, 7, 10), "Office Supplies", 38_000.0, items_for("Travel", 2))
    planted.append(f"CATEGORY_MISMATCH — {mis_no}.pdf: travel line items labelled 'Office Supplies'")
    expected.append({"rule_code": "CATEGORY_MISMATCH", "invoice_number": mis_no})
    # extraction truth is what the document SAYS (Office Supplies) — the
    # semantic wrongness is the Validation Agent's job to catch, not extraction's
    record(f"{mis_no}.pdf", "Skyline Travels", mis_no, date(2026, 7, 10), "Office Supplies", 38_000.0)

    # --- messy layouts: regex-unparseable, LLM-extraction-only ---
    messy = [
        {
            "file": "nimbus_tax_invoice_0071.pdf",
            "title": "TAX INVOICE",
            "vendor": "Nimbus Cloud Services",
            "header_lines": ["Plot 22, Electronic City, Bengaluru 560100",
                             "Bill No: NCS/2026/0071", "Invoice dated July 3, 2026"],
            "items": [("Compute instances", 28_500.0), ("Object storage", 19_000.0)],
            "total_line": "Amount Due: Rs. 47,500.00",
            "truth": ("Nimbus Cloud Services", "NCS/2026/0071", date(2026, 7, 3), "Cloud Services", 47_500.0),
        },
        {
            "file": "skyline_travel_invoice_088.pdf",
            "title": "TRAVEL INVOICE",
            "vendor": "Skyline Travels",
            "header_lines": ["Shop 8, Connaught Place, New Delhi 110001",
                             "Ref #: SKY-2026-088", "Date of Issue: 08/07/2026"],
            "items": [("Flight tickets DEL-BLR", 26_500.0), ("Hotel accommodation", 15_000.0)],
            "total_line": "Grand Total (INR) 41,500.00",
            "truth": ("Skyline Travels", "SKY-2026-088", date(2026, 7, 8), "Travel", 41_500.0),
        },
        {
            "file": "officemart_memo_jul22.pdf",
            "title": "PURCHASE MEMO",
            "vendor": "OfficeMart Supplies",
            "header_lines": ["Warehouse 3, Bhiwandi, Thane 421302",
                             "Memo no. OM/JUL/22", "Dt. 11-07-2026"],
            "items": [("Printer toner", 6_250.0), ("A4 paper cartons", 3_500.0)],
            "total_line": "Net Payable Rs 9,750.00",
            "truth": ("OfficeMart Supplies", "OM/JUL/22", date(2026, 7, 11), "Office Supplies", 9_750.0),
        },
    ]
    for m in messy:
        draw_messy_invoice(INVOICE_DIR / m["file"], m)
        vendor, no, d, cat, total = m["truth"]
        record(m["file"], vendor, no, d, cat, total, category_on_document=False)

    # --- expense-report CSV: BrightSpark Marketing history + 2 planted rows ---
    rows = []
    ref = 5000
    for month in range(1, 8):
        for _ in range(3 if month < 7 else 2):
            ref += 1
            amount = round(random.uniform(60_000, 80_000) / 500) * 500
            # current-month rows must not land after TODAY, or the (correct)
            # future-date rule flags them as unplanted extras
            max_day = min(26, TODAY.day - 1) if month == TODAY.month else 26
            rows.append({
                "date": date(2026, month, random.randint(2, max_day)).isoformat(),
                "vendor": "BrightSpark Marketing",
                "category": "Marketing",
                "description": random.choice(ITEM_POOL["Marketing"]),
                "amount": amount,
                "reference_no": f"EXP-{ref}",
            })
    dup_row = dict(rows[-1])
    rows.append(dup_row)
    planted.append(f"DUPLICATE_INVOICE — expenses.csv: reference {dup_row['reference_no']} appears twice")
    expected.append({"rule_code": "DUPLICATE_INVOICE", "invoice_number": dup_row["reference_no"]})
    rows.append({
        "date": "2026-07-12", "vendor": "BrightSpark Marketing", "category": "Marketing",
        "description": "Influencer collaboration", "amount": 350_000, "reference_no": f"EXP-{ref + 1}",
    })
    planted.append("AMOUNT_OUTLIER — expenses.csv EXP-%d: Rs. 3,50,000 vs BrightSpark's normal Rs. 60k-80k" % (ref + 1))
    expected.append({"rule_code": "AMOUNT_OUTLIER", "invoice_number": f"EXP-{ref + 1}"})

    with open(OUT / "expenses.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "vendor", "category", "description", "amount", "reference_no"])
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        truth_csv[row["reference_no"]] = {
            "vendor_name": row["vendor"],
            "invoice_date": row["date"],
            "total_amount": float(row["amount"]),
            "category": row["category"],
        }

    answer_key = "# Planted anomalies (demo answer key)\n\n" + "\n".join(f"- {p}" for p in planted) + "\n"
    (OUT / "PLANTED_ANOMALIES.md").write_text(answer_key, encoding="utf-8")
    (OUT / "planted.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    (OUT / "ground_truth.json").write_text(
        json.dumps({"pdfs": truth_pdfs, "csv_rows": truth_csv}, indent=2), encoding="utf-8"
    )

    n_pdfs = len(list(INVOICE_DIR.glob("*.pdf")))
    print(f"Generated {n_pdfs} invoice PDFs in {INVOICE_DIR}")
    print(f"Generated expenses.csv with {len(rows)} rows")
    print("Answer key written to PLANTED_ANOMALIES.md:")
    for p in planted:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
