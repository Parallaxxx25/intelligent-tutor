# Multi-stage build — the compile toolchain (needed for a couple of wheels
# without prebuilt manylinux binaries on some platforms) never ships in the
# final image.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt


FROM python:3.12-slim

# WORKDIR must be /app — backend/config.py's SLIDE_MATERIAL_DIR
# ("slide-material") and CHROMA_PERSIST_DIR ("./.chroma") are relative paths
# resolved against the process's cwd, not the package location.
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY SQL-Server-Sample-Database/ ./SQL-Server-Sample-Database/
COPY sql-problem/ ./sql-problem/

# slide-material/ is .gitignored (course PDFs, not meant for git history) —
# absent from every fresh clone, so it can't be COPYed unconditionally
# without breaking the build for everyone. Create it empty; SLIDE_MATERIAL_DIR
# still resolves to a valid (empty) path. To actually enable slide RAG, bind-
# mount the real directory at runtime: `-v ./slide-material:/app/slide-material`
# (or the compose equivalent) alongside SLIDE_RAG_ENABLED=true.
RUN mkdir -p slide-material

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
