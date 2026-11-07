# ==========================================
# Stage 1: Build Environment
# ==========================================
FROM python:3.12-slim-bookworm AS builder

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
    pip wheel \
        --wheel-dir=/wheels \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# optionally remove GUI OpenCV wheel (if pulled as a transitive dependency)
RUN rm -f /wheels/opencv_python-[0-9]*.whl || true

# ==========================================
# Stage 2: Minimal Runtime Image
# ==========================================
FROM python:3.12-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YOLO_VERBOSE=False \
    ULTRALYTICS_AUTOINSTALL=False

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --no-deps --find-links=/wheels /wheels/* \
    && rm -rf /wheels

COPY camera_receiver.py config.py flasher.py prey_runs firmware_bin ./

EXPOSE 8000

CMD ["uvicorn", "camera_receiver:app", "--host", "0.0.0.0", "--port", "8000"]
