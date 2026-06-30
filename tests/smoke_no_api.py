"""Offline smoke test — exercises everything except the OpenAI calls.

Run with:  uv run python tests/smoke_no_api.py

Verifies: imports, email parsing, PDF text+image extraction, schema, and the
deterministic notification rendering. Does NOT call the OpenAI API.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invoice_agent.email_loader import load_email  # noqa: E402
from invoice_agent.notify import build_notification  # noqa: E402
from invoice_agent.pdf_extract import extract_pdf  # noqa: E402
from invoice_agent.schema import InvoiceData, LineItem, SiteAllocation, TaxLine  # noqa: E402
# Importing the agent module verifies the Agents SDK symbols resolve.
import invoice_agent.agent  # noqa: F401,E402


def main() -> int:
    email = load_email(ROOT / "data" / "Email.json")
    assert email.subject and email.from_address, "email did not parse"
    assert email.first_pdf_attachment == "Invoice.pdf", email.first_pdf_attachment
    print(f"[ok] email parsed: from={email.from_address}, att={email.attachment_names}")

    pdf = extract_pdf(ROOT / "data" / "Invoice.pdf")
    assert pdf.page_count == 8, pdf.page_count
    assert pdf.has_images, "expected an embedded image"
    assert "Northbridge Office Furnishings" in pdf.text
    print(f"[ok] pdf parsed: pages={pdf.page_count}, images={len(pdf.images)}, "
          f"text_chars={len(pdf.text)}")

    # Fake an extraction result and render the notification deterministically.
    invoice = InvoiceData(
        vendor_name="Northbridge Office Furnishings Inc.",
        invoice_number="NBX-260126-0174",
        invoice_date="2026-01-26",
        due_date="2026-02-25",
        payment_terms="Net 30",
        currency="CAD",
        customer_account="004913-MLHG",
        customer_po_number="MLHG-PO-104772",
        subtotal=113983.69,
        total_tax=15166.37,
        total_due=129150.06,
        taxes=[TaxLine(jurisdiction="Ontario", tax_type="HST 13%",
                       taxable_amount=96338.71, tax_amount=12524.03)],
        line_items=[LineItem(line=1, sku="CHR-ERG-8400-BLK",
                             description="ErgoFlex 8400 Task Chair",
                             quantity=120, unit_price=357.88, line_total=42945.60)],
        ship_to_sites=[SiteAllocation(site="Toronto Operations Centre",
                                      cost_centre="TOR-OPS-221",
                                      items=["CHR-ERG-8400-BLK Qty 90"])],
        cost_centres=["TOR-OPS-221", "OTT-TRN-114", "MTL-ADM-038"],
        important_notes=["Possible duplicate: a preliminary quote was received in late December."],
    )

    with tempfile.TemporaryDirectory() as td:
        result = build_notification(invoice, email, Path(td), "Net 30; confirm PO match.")
        assert result.text_path.is_file() and result.json_path.is_file()
        txt = result.text_path.read_text(encoding="utf-8")
        assert "NBX-260126-0174" in txt
        assert "129,150.06 CAD" in txt
        assert "TOR-OPS-221" in txt
        print(f"[ok] notification rendered: {len(txt)} chars, "
              f"json keys={list(result.payload.keys())}")

    print("\nALL OFFLINE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
