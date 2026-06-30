"""Offline test of the data-quality gate (no API calls).

Directly addresses the "don't let a failure look like success" requirement:
an empty or degraded extraction must be rejected as a FAILURE, while a genuine
extraction passes. Run with:  uv run python tests/test_quality_gate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invoice_agent.extraction import ExtractionQualityError, validate_quality  # noqa: E402
from invoice_agent.schema import InvoiceData, LineItem  # noqa: E402


def _expect_rejected(data: InvoiceData, label: str) -> None:
    try:
        validate_quality(data)
    except ExtractionQualityError as exc:
        assert "invoice_number" in exc.missing, exc.missing
        print(f"[ok] {label}: rejected (missing={exc.missing})")
        return
    raise AssertionError(f"{label}: was NOT rejected — the masking gate failed")


def test_empty_extraction_is_a_failure() -> None:
    # Vision read produced nothing usable.
    _expect_rejected(InvoiceData(), "all-null extraction")


def test_image_canary_missing_is_a_failure() -> None:
    # Plausible text-derived fields, but the image-only invoice number is absent
    # (the exact degraded-vision case the audit identified).
    partial = InvoiceData(
        vendor_name="Northbridge Office Furnishings Inc.",
        currency="CAD",
        subtotal=113983.69,
        line_items=[LineItem(sku="CHR-ERG-8400-BLK", quantity=120)],
    )
    _expect_rejected(partial, "missing image canary (invoice_number)")


def test_missing_total_is_a_failure() -> None:
    try:
        validate_quality(InvoiceData(invoice_number="NBX-1"))  # no total_due
    except ExtractionQualityError as exc:
        assert "total_due" in exc.missing, exc.missing
        print(f"[ok] missing total_due: rejected (missing={exc.missing})")
        return
    raise AssertionError("missing total_due was NOT rejected")


def test_complete_extraction_passes() -> None:
    good = InvoiceData(invoice_number="NBX-260126-0174", total_due=129150.06)
    validate_quality(good)  # must not raise
    print("[ok] complete extraction passes the gate")


if __name__ == "__main__":
    test_empty_extraction_is_a_failure()
    test_image_canary_missing_is_a_failure()
    test_missing_total_is_a_failure()
    test_complete_extraction_passes()
    print("\nALL QUALITY-GATE CHECKS PASSED")
