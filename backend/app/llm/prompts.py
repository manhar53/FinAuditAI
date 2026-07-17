"""All prompts in one place, so the agent behaviour is inspectable."""

EXTRACTION_SYSTEM = (
    "You are a precise financial document parser. You output only valid JSON, "
    "no markdown fences, no commentary."
)

EXTRACTION_PROMPT = """Extract structured fields from this invoice text.

Rules:
- Respond with ONLY a JSON object, nothing else.
- Use null for any field you cannot find. Never invent values.
- Labels vary between vendors: the invoice number may be called "Invoice No",
  "Bill No", "Ref", "Memo no" or similar; the total may be called "Total",
  "Amount Due", "Grand Total", "Net Payable" or similar. The vendor name is the
  company issuing the invoice, not words like "TAX INVOICE" or the "Bill To" party.
- "invoice_date" must be in YYYY-MM-DD format (the date may be written in words).
- "total_amount" must be a plain number (no currency symbols or commas).
- "category" must be one of: "IT Services", "Cloud Services", "Travel", "Office Supplies", "Marketing", "Other".
  If no category is printed, infer it from the line items.

JSON shape:
{{
  "vendor_name": string|null,
  "invoice_number": string|null,
  "invoice_date": string|null,
  "total_amount": number|null,
  "currency": string|null,
  "category": string|null,
  "line_items": [{{"description": string, "quantity": number, "unit_price": number, "amount": number}}]
}}

Invoice text:
---
{text}
---
"""

ROUTER_SYSTEM = (
    "You route financial-audit questions to the right query tool. "
    "You output only valid JSON, no markdown fences, no commentary."
)

ROUTER_PROMPT = """Pick the best tool for the user's question and fill its parameters.

Available tools:
{tool_catalog}

Rules:
- Respond with ONLY a JSON object: {{"tool": "<tool_name>", "params": {{...}}}}
- Omit parameters the question doesn't specify (defaults apply).
- Amounts like "Rs 50,000" or "50k" become plain numbers (50000).
- Dates must be YYYY-MM-DD. Today is {today}.
- "this month" means from the 1st of the current month to today.

Examples:
Q: which vendor had the most flagged invoices this month?
A: {{"tool": "top_vendors_by_anomalies", "params": {{"start_date": "{month_start}"}}}}
Q: show me all anomalies above 50000
A: {{"tool": "anomalies_above_amount", "params": {{"min_amount": 50000}}}}
Q: how much did we spend on travel?
A: {{"tool": "spend_by_category", "params": {{}}}}
Q: what is the monthly spend trend?
A: {{"tool": "spend_over_time", "params": {{}}}}

User question: {question}
"""

RAG_ANSWER_SYSTEM = (
    "You are a financial audit assistant. Answer only from the provided context. "
    "If the context does not contain the answer, say so plainly."
)

RAG_ANSWER_PROMPT = """Context (flagged anomalies and document records from the audit database):
---
{context}
---

Question: {question}

Answer concisely in 2-4 sentences. For every flag you mention, name its specific rule in
plain words (duplicate invoice, amount outlier, missing field, inconsistent date, or
category mismatch) and cite the exact vendor, amount and invoice number from the context.
Do not use vague words like "discrepancies" or "inconsistencies" in place of the rule.
"""
