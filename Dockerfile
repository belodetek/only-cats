# ==========================================
# Stage 1: Build Environment
# ==========================================
FROM python:3.14-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install -r requirements.txt && \
    pip uninstall -y opencv-python || true

# ==========================================
# Stage 2: Minimal Runtime Image
# ==========================================
FROM python:3.14-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH="/install/lib/python3.14/site-packages:${PYTHONPATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libxcb1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /install /install
COPY camera_receiver.py .
COPY config.py .
COPY prey_runs/ ./prey_runs/

EXPOSE 8000

CMD ["uvicorn", "camera_receiver:app", "--host", "0.0.0.0", "--port", "8000"]
