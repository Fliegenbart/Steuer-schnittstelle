FROM python:3.11-slim AS base

# System deps: Tesseract OCR (German), PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-deu libtesseract-dev \
    poppler-utils libmagic1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Non-root user for security
RUN useradd -r -u 1000 -s /bin/false steuerpilot \
    && mkdir -p /app/data /app/uploads \
    && chown -R steuerpilot:steuerpilot /app
USER steuerpilot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
