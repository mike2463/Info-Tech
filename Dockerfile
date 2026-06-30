# Invoice-intake agent — containerised with uv.
# Base image ships uv + CPython 3.12 (Debian bookworm slim).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv tuning: bytecode-compile for faster startup, copy (not hardlink) so the
# install works across mounted volumes, and use the image's interpreter.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Install third-party dependencies first (best layer caching). This step is
#    independent of our source code, so it is only re-run when deps change.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# 2) Add the project source and install the package itself.
COPY README.md ./
COPY src ./src
COPY main.py ./
RUN uv sync --no-dev

# data/ (inputs incl. .env) and outputs/ are provided at runtime via volumes.
ENTRYPOINT ["uv", "run", "python", "main.py"]
CMD ["--email", "./data/Email.json"]
