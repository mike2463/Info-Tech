"""Pydantic schema for the structured invoice payload.

This is the contract returned by the extraction tool and embedded in the
outbound Customer Service notification. Every field is optional so partial
extraction (e.g. a missing image) degrades gracefully rather than crashing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    line: int | None = Field(None, description="Line number on the invoice")
    sku: str | None = Field(None, description="Stock keeping unit / item code")
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None


class TaxLine(BaseModel):
    jurisdiction: str | None = Field(None, description="e.g. Ontario, Québec")
    tax_type: str | None = Field(None, description="e.g. HST 13%, GST 5%, QST 9.975%")
    taxable_amount: float | None = None
    tax_amount: float | None = None


class SiteAllocation(BaseModel):
    site: str | None = Field(None, description="Site name / label")
    cost_centre: str | None = None
    address: str | None = None
    items: list[str] = Field(
        default_factory=list,
        description="Per-site item allocations as short strings, e.g. 'CHR-ERG-8400-BLK Qty 90'",
    )
    delivery_window: str | None = None
    delivery_service: str | None = None


class InvoiceData(BaseModel):
    """Full structured invoice extraction result."""

    # Header / identity (several of these live only inside the page-1 image)
    vendor_name: str | None = None
    invoice_number: str | None = Field(
        None, description="May be present ONLY inside an embedded PDF image"
    )
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = Field(None, description="e.g. Net 30")
    currency: str | None = None
    customer_name: str | None = None
    customer_account: str | None = None
    customer_po_number: str | None = None

    # Money
    subtotal: float | None = None
    total_tax: float | None = None
    total_due: float | None = None
    taxes: list[TaxLine] = Field(default_factory=list)

    # Lines and logistics
    line_items: list[LineItem] = Field(default_factory=list)
    ship_to_sites: list[SiteAllocation] = Field(default_factory=list)
    cost_centres: list[str] = Field(default_factory=list)

    # Free-form context
    important_notes: list[str] = Field(
        default_factory=list,
        description="Delivery windows, receiving requirements, duplicate warnings, etc.",
    )

    # Bookkeeping about the extraction itself (not from the document)
    extraction_warnings: list[str] = Field(default_factory=list)
