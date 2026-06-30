"""Configuration and environment loading.

Secrets (the OpenAI API key) are read from a ``.env`` file. We never hard-code
keys and never log their values. The assignment restricts model usage to
``gpt-5-mini`` and ``gpt-5-nano`` only; that constraint is enforced here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Only these two models are permitted by the assignment.
ALLOWED_MODELS = ("gpt-5-mini", "gpt-5-nano")

# Project root = two levels up from this file (src/invoice_agent/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_environment() -> None:
    """Load environment variables from the first ``.env`` we can find.

    Search order (first match wins, existing process env always takes priority):
      1. ``.env`` in the project root
      2. ``data/.env`` (the provided key lives here in this repo)
      3. ``.env`` in the current working directory
    """
    candidates = [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "data" / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            # override=False: never clobber a value already set in the real
            # environment (e.g. injected by Docker / CI).
            load_dotenv(candidate, override=False)


def _validate_model(name: str, value: str) -> str:
    if value not in ALLOWED_MODELS:
        raise ValueError(
            f"{name}={value!r} is not permitted. "
            f"Allowed models: {', '.join(ALLOWED_MODELS)}."
        )
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from the environment."""

    openai_api_key: str
    agent_model: str
    extraction_model: str
    reasoning_effort: str
    output_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_environment()

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to a .env file "
                "(see .env.example) or export it in your environment."
            )

        # gpt-5-nano is plenty for the simple two-step orchestration and is the
        # cheaper model; gpt-5-mini handles the vision/text extraction.
        agent_model = _validate_model(
            "AGENT_MODEL", os.getenv("AGENT_MODEL", "gpt-5-nano").strip()
        )
        extraction_model = _validate_model(
            "EXTRACTION_MODEL", os.getenv("EXTRACTION_MODEL", "gpt-5-mini").strip()
        )

        reasoning_effort = os.getenv("REASONING_EFFORT", "low").strip() or "low"

        output_dir = Path(
            os.getenv("OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))
        ).resolve()

        return cls(
            openai_api_key=api_key,
            agent_model=agent_model,
            extraction_model=extraction_model,
            reasoning_effort=reasoning_effort,
            output_dir=output_dir,
        )
