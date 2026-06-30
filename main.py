"""Runnable entrypoint.

    uv run python main.py --email ./data/Email.json
"""

from invoice_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
