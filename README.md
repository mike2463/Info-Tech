# Invoice-Intake Agent

An [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) agent that
ingests an inbound vendor **email**, reads its **PDF invoice** attachment,
extracts the key invoice/purchase data — **including fields that exist only
inside an image embedded in the PDF** — and produces a ready-to-send
notification for Customer Service (a human-readable summary **and** a structured
JSON payload).

The agent uses exactly two tools:

1. **`extract_invoice_data`** — loads the PDF, pulls the text layer *and* the
   embedded image(s) with [PyMuPDF](https://pymupdf.readthedocs.io/), then makes
   a single vision+text extraction call and returns a structured result.
2. **`send_to_customer_service`** — renders the outbound summary + JSON payload
   and writes them to disk (behaves like a "send notification" tool).

---

## How it works

```
data/Email.json ─┐
                 ├─►  Agent (gpt-5-nano)
data/Invoice.pdf ┘        │
                          ├─ tool 1: extract_invoice_data ──► gpt-5-mini (text + page-1 image) ──► InvoiceData
                          └─ tool 2: send_to_customer_service ─► outputs/outbound_email.{txt,json}
```

The large extracted payload is passed between tools through a shared run
**context object**, not back through the model — this keeps token usage low and
avoids transcription errors.

### Why vision is required

The provided invoice deliberately hides its header fields (invoice number,
invoice date, due date, total due, customer account, customer PO) inside a
raster image on page 1; they are **not** in the PDF text layer. The extraction
tool sends that embedded image to the model so those fields are recovered.

---

## Setup

Prerequisites: [`uv`](https://docs.astral.sh/uv/) (and optionally Docker).

```bash
uv sync
```

### Configure secrets

Secrets are read from a `.env` file (never committed — it is in `.gitignore`).
Copy the example and add your key, or place it at `data/.env`:

```bash
cp .env.example .env
# then edit .env:  OPENAI_API_KEY=sk-...
```

The app looks for the key in `.env`, then `data/.env`, then the current
environment.

---

## Run

Single command (uses `./data/Email.json` and its referenced attachment):

```bash
uv run python main.py --email ./data/Email.json
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--email` | `./data/Email.json` | Inbound email JSON |
| `--pdf` | the email's attachment | Override the invoice PDF path |
| `--output-dir` | `./outputs` | Where to write the notification |

### Run in Docker

The daemon must be running. Build + run with Compose (reads `data/.env`, mounts
`./data` read-only and `./outputs` for results):

```bash
docker compose run --rm agent
```

Or with plain Docker:

```bash
docker build -t invoice-intake-agent .
docker run --rm --env-file ./data/.env \
  -v "$(pwd)/data:/app/data:ro" -v "$(pwd)/outputs:/app/outputs" \
  invoice-intake-agent --email ./data/Email.json
```

---

## Output

Both files are written to `./outputs/` (and previewed on stdout):

| File | Contents |
|------|----------|
| `outbound_email.txt` | Human-readable, sectioned summary for Customer Service |
| `outbound_email.json` | Structured payload (invoice fields + source email) for downstream processing |

Extracted fields include: vendor, invoice number, invoice/due dates, payment
terms, currency, customer PO & account, subtotal/taxes (with jurisdiction
breakdown)/total, the full line-item table, per-site ship-to allocations with
delivery windows, cost centres, and important notes (delivery windows,
receiving requirements, duplicate-quote warning).

The agent also prints which models were used and the resolved input paths.

---

## Models & cost discipline

Only `gpt-5-mini` and `gpt-5-nano` are used (enforced in `config.py`):

- **`gpt-5-nano`** drives the two-step agent orchestration.
- **`gpt-5-mini`** performs the single vision+text extraction call.

To respect the API key's strict usage limits, the design avoids waste:
one extraction call (no speculative retries), `reasoning_effort=low`, a compact
prompt (the already-extracted text rather than the raw PDF), structured outputs,
and a `max_turns` guard on the agent loop.

Override models/effort via env vars (`AGENT_MODEL`, `EXTRACTION_MODEL`,
`REASONING_EFFORT`) — still constrained to the allowed models.

---

## Error handling

- Missing/invalid email JSON, missing PDF attachment, and unreadable/empty PDFs
  produce clear messages and a non-zero exit code.
- If the PDF has no embedded image, extraction degrades to text-only and records
  a warning (image-only fields may be blank) instead of crashing.
- API/SDK errors are surfaced rather than silently retried.

---

## Project layout

```
main.py                     # entrypoint: uv run python main.py --email ...
src/invoice_agent/
  config.py                 # env loading + model allow-list
  email_loader.py           # parse the inbound email JSON
  pdf_extract.py            # PyMuPDF: text + embedded images
  schema.py                 # Pydantic invoice schema
  extraction.py             # single vision+text extraction call
  notify.py                 # render summary + JSON, write files
  agent.py                  # Agents SDK agent + the two tools + run context
  cli.py                    # argument parsing / orchestration
tests/smoke_no_api.py       # offline checks (no API calls)
Dockerfile, docker-compose.yml
```

---

## Offline check

Validates parsing, extraction plumbing, and rendering without calling the API:

```bash
uv run python tests/smoke_no_api.py
```
