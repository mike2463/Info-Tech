"""Command-line entrypoint.

    uv run python main.py --email ./data/Email.json

Resolves the PDF attachment relative to the email file (the email names its
attachment), runs the agent, and reports where the outbound notification was
written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import run_agent
from .config import PROJECT_ROOT, Settings
from .email_loader import load_email


def _resolve_pdf(email, explicit_pdf: str | None) -> Path:
    """Find the invoice PDF: explicit flag > attachment next to the email > data/."""
    if explicit_pdf:
        p = Path(explicit_pdf)
        if not p.is_file():
            raise FileNotFoundError(f"--pdf path not found: {p}")
        return p

    attachment = email.first_pdf_attachment
    search: list[Path] = []
    if email.source_path is not None and attachment:
        search.append(email.source_path.parent / attachment)
    if attachment:
        search.append(PROJECT_ROOT / "data" / attachment)
    search.append(PROJECT_ROOT / "data" / "Invoice.pdf")

    for candidate in search:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "Could not locate the invoice PDF. The email references "
        f"{attachment!r}; looked in: {', '.join(str(s) for s in search)}. "
        "Pass --pdf to specify it explicitly."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invoice-agent",
        description="Ingest an inbound email + PDF invoice and notify Customer Service.",
    )
    parser.add_argument(
        "--email",
        default=str(PROJECT_ROOT / "data" / "Email.json"),
        help="Path to the inbound email JSON (default: ./data/Email.json).",
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help="Path to the invoice PDF. Defaults to the email's attachment.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for outbound_email.txt/json (default: ./outputs).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 1. Settings / secrets (clear error if the API key is missing).
    try:
        settings = Settings.from_env()
    except (RuntimeError, ValueError) as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        return 2

    if args.output_dir:
        settings = Settings(
            openai_api_key=settings.openai_api_key,
            agent_model=settings.agent_model,
            extraction_model=settings.extraction_model,
            reasoning_effort=settings.reasoning_effort,
            output_dir=Path(args.output_dir).resolve(),
        )

    # 2. Load inputs.
    try:
        email = load_email(args.email)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[email error] {exc}", file=sys.stderr)
        return 2

    try:
        pdf_path = _resolve_pdf(email, args.pdf)
    except FileNotFoundError as exc:
        print(f"[attachment error] {exc}", file=sys.stderr)
        return 2

    print(f"Email:   {Path(args.email).resolve()}")
    print(f"PDF:     {pdf_path}")
    print(f"Models:  agent={settings.agent_model}, extraction={settings.extraction_model}")
    print(f"Output:  {settings.output_dir}")
    print("-" * 56)
    print("Running agent...")

    # 3. Run the agent.
    try:
        ctx = run_agent(settings, email, pdf_path)
    except Exception as exc:  # network/API/SDK errors
        print(f"[agent error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # 4. Report.
    if ctx.errors:
        print("\nThe run reported issues:", file=sys.stderr)
        for e in ctx.errors:
            print(f"  - {e}", file=sys.stderr)

    if ctx.notification is None:
        print(
            "\n[failure] No notification was produced. See errors above.",
            file=sys.stderr,
        )
        return 1

    print("\n" + "=" * 56)
    print("OUTBOUND NOTIFICATION (preview)")
    print("=" * 56)
    print(ctx.notification.summary_text)
    print("=" * 56)
    print(f"Wrote: {ctx.notification.text_path}")
    print(f"Wrote: {ctx.notification.json_path}")

    # The exit code is a hard quality gate: any recorded error makes this a
    # non-zero exit even if a notification file was written for inspection, so a
    # degraded run can never present as a clean success.
    if ctx.errors:
        print(
            "\n[failure] Completed with errors (see above); exit code is non-zero.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
