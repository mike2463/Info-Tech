"""LLM-backed structured extraction.

A single, targeted call to the extraction model (default ``gpt-5-mini``) that
receives the PDF text layer *and* the embedded page image(s), and returns the
full :class:`InvoiceData` schema. Designed to be credit-frugal:

* one call (no loops, no speculative retries),
* low reasoning effort,
* a compact prompt (we send the already-extracted text, not the raw PDF),
* structured outputs so we don't pay for re-asking on malformed JSON.
"""

from __future__ import annotations

from openai import OpenAI

from .pdf_extract import PdfContent
from .schema import CRITICAL_FIELDS, InvoiceData


class ExtractionQualityError(RuntimeError):
    """The model returned parseable JSON, but the load-bearing fields a genuine
    read must produce (e.g. the image-only invoice number) are missing.

    Raised so that a degraded or failed vision read surfaces as a real failure
    (non-zero exit, no "success" notification) instead of a clean-looking
    notification full of blanks. This is the guard that prevents "appears to
    work when it does not".
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "Extraction returned no value for required field(s): "
            f"{', '.join(missing)}. "
            "The invoice number exists only inside the page-1 image, so an "
            "empty value means the vision read did not work. Refusing to "
            "report success."
        )


def validate_quality(data: InvoiceData) -> None:
    """Raise :class:`ExtractionQualityError` if critical fields are missing.

    Detects an *empty* extraction (the vision read produced nothing usable). It
    cannot detect a *wrong-but-non-empty* value (a hallucinated number) — that
    would require ground truth we do not have; see README for this limitation.
    """
    missing = data.missing_critical_fields()
    if missing:
        raise ExtractionQualityError(missing)

_SYSTEM_PROMPT = (
    "You are a precise invoice data-extraction engine. "
    "Extract fields ONLY from the supplied invoice text and image(s). "
    "Never invent values: if a field is absent, leave it null/empty. "
    "Numbers must be plain decimals with no currency symbols or thousands "
    "separators (e.g. 129150.06). Dates use ISO format YYYY-MM-DD."
)

_USER_INSTRUCTIONS = (
    "Extract the structured invoice data.\n\n"
    "CRITICAL: Some header fields (invoice number, invoice date, due date, "
    "total due, customer account, customer PO) may appear ONLY inside the "
    "attached image, not in the text. Read the image carefully for these.\n\n"
    "Guidance:\n"
    "- Capture every line item (line, sku, description, quantity, unit_price, "
    "line_total).\n"
    "- Capture each tax line with its jurisdiction, type, taxable amount, and "
    "tax amount, plus subtotal, total_tax and total_due.\n"
    "- Capture ship-to sites with their cost centre, address, per-site item "
    "allocations and delivery windows.\n"
    "- If due_date minus invoice_date is a whole number of days, set "
    "payment_terms accordingly (e.g. 'Net 30').\n"
    "- Put delivery windows, receiving requirements, damage-reporting rules and "
    "any duplicate/quote warnings into important_notes.\n"
    "- Set currency from the document (e.g. 'CAD').\n"
    "Here is the invoice TEXT layer:\n\n"
    "<<<INVOICE_TEXT>>>\n{text}\n<<<END_INVOICE_TEXT>>>"
)

# Generous enough for the full JSON + low reasoning; bounded to avoid runaways.
_MAX_OUTPUT_TOKENS = 6000


def extract_invoice(
    pdf: PdfContent,
    *,
    api_key: str,
    model: str,
    reasoning_effort: str = "low",
) -> InvoiceData:
    """Run the single structured-extraction call and return validated data."""
    client = OpenAI(api_key=api_key)

    warnings: list[str] = []

    user_content: list[dict] = [
        {"type": "input_text", "text": _USER_INSTRUCTIONS.format(text=pdf.text or "(no text layer)")}
    ]

    if pdf.has_images:
        # Attach embedded images (typically just the page-1 header image).
        for img in pdf.images:
            user_content.append({"type": "input_image", "image_url": img.data_url})
    else:
        warnings.append(
            "No embedded images found in the PDF; image-only fields "
            "(e.g. invoice number) may be missing."
        )

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        text_format=InvoiceData,
        reasoning={"effort": reasoning_effort},
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )

    data = response.output_parsed
    if data is None:
        # Structured parsing failed (e.g. truncated/refused). Surface clearly
        # instead of silently retrying and burning credits.
        raise RuntimeError(
            "Extraction model did not return parseable structured output "
            f"(status={getattr(response, 'status', 'unknown')})."
        )

    # Carry forward any extraction-time warnings.
    if warnings:
        data.extraction_warnings = [*warnings, *data.extraction_warnings]

    # Hard quality gate: if the load-bearing fields are empty the vision read
    # did not work — fail loudly instead of emitting a blank "success".
    validate_quality(data)

    # Non-fatal: surface any *other* image-header fields that came back empty,
    # so a partial read is visible without failing the whole run.
    partial = [f for f in data.missing_header_fields() if f not in CRITICAL_FIELDS]
    if partial:
        data.extraction_warnings.append(
            "Image-header field(s) empty after extraction: "
            f"{', '.join(partial)}; verify the page-1 image."
        )

    return data
