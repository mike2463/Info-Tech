"""Render and persist the outbound Customer Service notification.

Produces two artifacts:
  * ``outbound_email.txt``  – a human-readable, sectioned summary
  * ``outbound_email.json`` – a structured payload for downstream processing

The human summary is rendered deterministically from the extracted data (rather
than asking the model to re-type it) so nothing is hallucinated or dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .email_loader import InboundEmail
from .schema import InvoiceData


@dataclass
class NotificationResult:
    text_path: Path
    json_path: Path
    summary_text: str
    payload: dict


def _money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "—"
    cur = f" {currency}" if currency else ""
    return f"{value:,.2f}{cur}"


def _build_summary(
    invoice: InvoiceData, email: InboundEmail, extra_notes: str | None
) -> str:
    cur = invoice.currency
    lines: list[str] = []
    add = lines.append

    add("ACTION REQUIRED: Vendor invoice ready for processing")
    add("=" * 56)
    add("")
    add("To: Customer Service / Accounts Payable")
    add(f"Re: Invoice {invoice.invoice_number or '(number not found)'} "
        f"from {invoice.vendor_name or 'Unknown vendor'}")
    add("")

    add("INVOICE SUMMARY")
    add("-" * 56)
    add(f"  Vendor:            {invoice.vendor_name or '—'}")
    add(f"  Invoice number:    {invoice.invoice_number or '—'}")
    add(f"  Invoice date:      {invoice.invoice_date or '—'}")
    add(f"  Due date:          {invoice.due_date or '—'}")
    add(f"  Payment terms:     {invoice.payment_terms or '—'}")
    add(f"  Currency:          {cur or '—'}")
    add(f"  Customer account:  {invoice.customer_account or '—'}")
    add(f"  Customer PO:       {invoice.customer_po_number or '—'}")
    add(f"  Subtotal:          {_money(invoice.subtotal, cur)}")
    add(f"  Total tax:         {_money(invoice.total_tax, cur)}")
    add(f"  TOTAL DUE:         {_money(invoice.total_due, cur)}")
    add("")

    if invoice.taxes:
        add("TAX BREAKDOWN")
        add("-" * 56)
        for t in invoice.taxes:
            add(f"  {t.jurisdiction or '—'} | {t.tax_type or '—'} | "
                f"taxable {_money(t.taxable_amount, cur)} | tax {_money(t.tax_amount, cur)}")
        add("")

    if invoice.line_items:
        add(f"LINE ITEMS ({len(invoice.line_items)})")
        add("-" * 56)
        for li in invoice.line_items:
            qty = "—" if li.quantity is None else f"{li.quantity:g}"
            add(f"  {str(li.line or '?'):>2}. {li.sku or '—'} | {li.description or '—'}")
            add(f"      qty {qty} x {_money(li.unit_price, cur)} = {_money(li.line_total, cur)}")
        add("")

    if invoice.ship_to_sites:
        add("SHIP-TO / SITE ALLOCATIONS")
        add("-" * 56)
        for s in invoice.ship_to_sites:
            header = s.site or "Site"
            if s.cost_centre:
                header += f" ({s.cost_centre})"
            add(f"  {header}")
            if s.address:
                add(f"      {s.address}")
            for item in s.items:
                add(f"      - {item}")
            if s.delivery_window:
                add(f"      Delivery window: {s.delivery_window}")
            if s.delivery_service:
                add(f"      Delivery service: {s.delivery_service}")
        add("")

    if invoice.cost_centres:
        add("COST CENTRES FOR APPROVAL ROUTING")
        add("-" * 56)
        add("  " + ", ".join(invoice.cost_centres))
        add("")

    if invoice.important_notes:
        add("IMPORTANT NOTES")
        add("-" * 56)
        for n in invoice.important_notes:
            add(f"  - {n}")
        add("")

    add("SOURCE EMAIL")
    add("-" * 56)
    add(f"  From:    {email.from_name} <{email.from_address}>")
    add(f"  Subject: {email.subject}")
    add(f"  Sent:    {email.sent_datetime or '—'}")
    add("")

    if extra_notes:
        add("AGENT NOTES")
        add("-" * 56)
        add(f"  {extra_notes}")
        add("")

    if invoice.extraction_warnings:
        add("DATA QUALITY WARNINGS")
        add("-" * 56)
        for w in invoice.extraction_warnings:
            add(f"  ! {w}")
        add("")

    return "\n".join(lines).rstrip() + "\n"


def build_notification(
    invoice: InvoiceData,
    email: InboundEmail,
    output_dir: Path,
    extra_notes: str | None = None,
) -> NotificationResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_text = _build_summary(invoice, email, extra_notes)

    payload = {
        "notification_type": "invoice_intake",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recipient": "Customer Service / Accounts Payable",
        "agent_notes": extra_notes or None,
        "invoice": invoice.model_dump(),
        "source_email": email.to_summary_dict(),
    }

    text_path = output_dir / "outbound_email.txt"
    json_path = output_dir / "outbound_email.json"
    text_path.write_text(summary_text, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return NotificationResult(
        text_path=text_path,
        json_path=json_path,
        summary_text=summary_text,
        payload=payload,
    )
