"""The OpenAI Agents SDK agent and its two tools.

The agent (default ``gpt-5-nano``) performs a tiny, deterministic orchestration:
read the email, call the extraction tool, then call the notification tool. The
heavy lifting lives in the tools, and the large invoice payload is passed
between them via a shared run *context* object — never round-tripped through the
model — which keeps token usage low and avoids transcription errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool

from .config import Settings
from .email_loader import InboundEmail
from .extraction import ExtractionQualityError, extract_invoice
from .notify import NotificationResult, build_notification
from .pdf_extract import extract_pdf
from .schema import InvoiceData


@dataclass
class InvoiceRunContext:
    """Shared state threaded through the agent run (not seen by the model)."""

    settings: Settings
    email: InboundEmail
    pdf_path: Path
    invoice: InvoiceData | None = None
    notification: NotificationResult | None = None
    errors: list[str] = field(default_factory=list)


@function_tool
def extract_invoice_data(wrapper: RunContextWrapper[InvoiceRunContext]) -> str:
    """Load the attached PDF invoice and extract structured data from its text
    and embedded image(s). Stores the full result in the run context and returns
    a short confirmation. Call this once before sending the notification.
    """
    ctx = wrapper.context
    try:
        pdf = extract_pdf(ctx.pdf_path)
    except (FileNotFoundError, ValueError) as exc:
        ctx.errors.append(str(exc))
        return f"ERROR reading PDF: {exc}"

    try:
        invoice = extract_invoice(
            pdf,
            api_key=ctx.settings.openai_api_key,
            model=ctx.settings.extraction_model,
            reasoning_effort=ctx.settings.reasoning_effort,
        )
    except ExtractionQualityError as exc:
        # The vision read produced no usable invoice fields. Record it as a
        # failure (not a warning) and do NOT set ctx.invoice, so no "success"
        # notification can be produced and the run exits non-zero.
        ctx.errors.append(f"extraction quality check failed: {exc}")
        return f"ERROR: extraction did not produce the required fields: {exc}"
    except Exception as exc:  # surface API/parse errors to the agent cleanly
        ctx.errors.append(f"extraction failed: {exc}")
        return f"ERROR extracting invoice fields: {exc}"

    ctx.invoice = invoice
    # Return a compact confirmation only — keep tokens minimal.
    return (
        "Extracted invoice "
        f"{invoice.invoice_number or '(no number)'} from "
        f"{invoice.vendor_name or '(unknown vendor)'}: "
        f"{len(invoice.line_items)} line items, "
        f"total_due={invoice.total_due} {invoice.currency or ''}, "
        f"{len(invoice.ship_to_sites)} ship-to sites. "
        f"Warnings: {len(invoice.extraction_warnings)}."
    )


@function_tool
def send_to_customer_service(
    wrapper: RunContextWrapper[InvoiceRunContext], additional_notes: str = ""
) -> str:
    """Send the outbound notification to Customer Service. Writes a
    human-readable summary (outbound_email.txt) and a structured JSON payload
    (outbound_email.json). Pass ``additional_notes`` to include any email-specific
    context worth flagging (e.g. duplicate-quote warning, payment terms,
    cost-centre routing). Call this once, after extraction.
    """
    ctx = wrapper.context
    if ctx.invoice is None:
        return "ERROR: no invoice data available. Call extract_invoice_data first."

    result = build_notification(
        ctx.invoice, ctx.email, ctx.settings.output_dir, additional_notes or None
    )
    ctx.notification = result
    return (
        f"Notification sent. Wrote {result.text_path.name} and "
        f"{result.json_path.name} to {ctx.settings.output_dir}."
    )


_INSTRUCTIONS = (
    "You are an Accounts Payable intake agent. Your job is to turn an inbound "
    "vendor email + PDF invoice into a single, complete notification for "
    "Customer Service.\n\n"
    "Follow these steps exactly, and use each tool at most once:\n"
    "1. Call `extract_invoice_data` (it takes no arguments) to parse the PDF.\n"
    "2. Call `send_to_customer_service` once. In `additional_notes`, briefly "
    "flag email-specific context that AP needs but that may not be in the "
    "invoice — for example: the requested PO match and payment terms, the "
    "cost-centre approval routing, the appointment-based multi-site delivery, "
    "and especially any DUPLICATE / prior-quote warning mentioned in the email.\n"
    "3. Reply with a one-sentence confirmation naming the invoice number and "
    "total due.\n\n"
    "Never fabricate data. Do not re-call a tool that already succeeded. Keep "
    "your own messages short — the tools produce the detailed output."
)


def build_agent(settings: Settings) -> Agent[InvoiceRunContext]:
    """Construct the agent with low reasoning effort (credit-frugal)."""
    try:
        from openai.types.shared import Reasoning

        model_settings = ModelSettings(reasoning=Reasoning(effort="low"))
    except Exception:  # pragma: no cover - defensive across SDK versions
        model_settings = ModelSettings()

    return Agent[InvoiceRunContext](
        name="Invoice Intake Agent",
        instructions=_INSTRUCTIONS,
        model=settings.agent_model,
        tools=[extract_invoice_data, send_to_customer_service],
        model_settings=model_settings,
    )


def run_agent(settings: Settings, email: InboundEmail, pdf_path: Path) -> InvoiceRunContext:
    """Run the agent end-to-end and return the populated run context."""
    ctx = InvoiceRunContext(settings=settings, email=email, pdf_path=pdf_path)
    agent = build_agent(settings)

    # The model only needs lightweight pointers; the email body gives it the
    # context to write good `additional_notes`. The PDF is read by the tool.
    agent_input = (
        "Process this inbound vendor invoice email and notify Customer Service.\n\n"
        f"PDF attachment path (already located): {pdf_path.name}\n\n"
        "EMAIL:\n"
        f"From: {email.from_name} <{email.from_address}>\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body}"
    )

    # max_turns guards against runaway loops (assignment: be credit-mindful).
    Runner.run_sync(agent, agent_input, context=ctx, max_turns=6)
    return ctx
