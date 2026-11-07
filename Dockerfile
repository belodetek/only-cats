# ==========================================
# Stage 1: Build Environment
# ==========================================
FROM python:3.14-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt && \
    pip uninstall -y opencv-python || true

RUN find /install/lib/python*/site-packages -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /install/lib/python*/site-packages -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /install/lib/python*/site-packages -name "*.pyc" -delete 2>/dev/null || true && \
    find /install/lib/python*/site-packages -name "*.pyo" -delete 2>/dev/null || true

# ==========================================
# Stage 2: Minimal Runtime Image
# ==========================================
FROM python:3.14-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YOLO_VERBOSE=False \
    ULTRALYTICS_AUTOINSTALL=False \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH="/install/lib/python3.14/site-packages:${PYTHONPATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* /var/tmp/*

WORKDIR /app

COPY --from=builder /install /install

COPY camera_receiver.py .
COPY config.py .
COPY flasher.py .
COPY prey_runs/ ./prey_runs/
COPY firmware_bin/ ./firmware_bin/

EXPOSE 8000

CMD ["uvicorn", "camera_receiver:app", "--host", "0.0.0.0", "--port", "8000"]
