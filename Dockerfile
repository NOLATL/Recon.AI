# ── Stage: production image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer-cached; rebuilt only when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

EXPOSE 8000

# src.api.main is the module path; :app is the FastAPI instance name.
# Shell form so $PORT (injected by Railway and similar platforms) is honored.
CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
