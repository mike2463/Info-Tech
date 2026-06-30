"""Load and parse the inbound email JSON (Microsoft Graph message shape)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InboundEmail:
    """A lightweight view over the provided email JSON."""

    subject: str
    body: str
    from_name: str
    from_address: str
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)
    sent_datetime: str | None = None
    source_path: Path | None = None

    @property
    def first_pdf_attachment(self) -> str | None:
        for name in self.attachment_names:
            if name.lower().endswith(".pdf"):
                return name
        return self.attachment_names[0] if self.attachment_names else None

    def to_summary_dict(self) -> dict:
        """Compact, model-friendly view of the email (no raw bytes)."""
        return {
            "subject": self.subject,
            "from": f"{self.from_name} <{self.from_address}>",
            "to": self.to,
            "cc": self.cc,
            "sent": self.sent_datetime,
            "attachments": self.attachment_names,
            "body": self.body,
        }


def _addresses(recipients: list[dict]) -> list[str]:
    out: list[str] = []
    for r in recipients or []:
        ea = (r or {}).get("EmailAddress", {})
        addr = ea.get("Address")
        name = ea.get("Name")
        if addr and name:
            out.append(f"{name} <{addr}>")
        elif addr:
            out.append(addr)
    return out


def load_email(path: str | Path) -> InboundEmail:
    """Parse the email JSON file into an :class:`InboundEmail`.

    Raises
    ------
    FileNotFoundError
        If the email file does not exist.
    ValueError
        If the file is not valid JSON or is missing the ``Message`` envelope.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Email file not found: {p}")

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Email file is not valid JSON: {p} ({exc})") from exc

    # Accept both the {"Message": {...}} envelope and a bare message object.
    msg = raw.get("Message", raw) if isinstance(raw, dict) else None
    if not isinstance(msg, dict):
        raise ValueError(f"Unexpected email structure in {p}")

    body_obj = msg.get("Body", {}) or {}
    body = body_obj.get("Content", "") if isinstance(body_obj, dict) else str(body_obj)

    from_ea = (msg.get("From", {}) or {}).get("EmailAddress", {}) or {}

    attachments = [
        a.get("Name", "")
        for a in (msg.get("Attachments", []) or [])
        if isinstance(a, dict) and a.get("Name")
    ]

    return InboundEmail(
        subject=msg.get("Subject", "") or "",
        body=body or "",
        from_name=from_ea.get("Name", "") or "",
        from_address=from_ea.get("Address", "") or "",
        to=_addresses(msg.get("ToRecipients", [])),
        cc=_addresses(msg.get("CcRecipients", [])),
        attachment_names=attachments,
        sent_datetime=msg.get("SentDateTime"),
        source_path=p,
    )
