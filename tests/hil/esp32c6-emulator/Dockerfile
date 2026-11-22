# Stage 1: Compile XIAO_ESP32C6 firmware for QEMU UART0 (ARDUINO_USB_CDC_ON_BOOT=0)
FROM python:3.12-slim-bookworm AS fw-builder

ARG FQBN=esp32:esp32:XIAO_ESP32C6
ARG FW_VERSION=hil

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh && \
    arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json && \
    arduino-cli core install esp32:esp32 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /fw
COPY firmware/firmware_sketch /fw/firmware_sketch

RUN arduino-cli compile \
      --fqbn "${FQBN}" \
      --board-options "CDCOnBoot=default" \
      --build-property "build.extra_flags=-DARDUINO_USB_CDC_ON_BOOT=0 -DARDUINO_USB_MODE=1 -DFW_VERSION=\"${FW_VERSION}\"" \
      --output-dir /fw/out \
      /fw/firmware_sketch && \
    cp /fw/out/firmware_sketch.ino.merged.bin /fw/flash_image.bin && \
    truncate -s 4M /fw/flash_image.bin

# Stage 2: Espressif QEMU RISC-V (supports -M esp32c6) + PTY Tee Proxy
FROM python:3.12-slim-bookworm

# https://github.com/espressif/qemu/releases
ARG QEMU_VERSION=esp-develop-9.2.2-20261109
ARG TARGETARCH

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libglib2.0-0 \
        libpixman-1-0 \
        libslirp0 \
        libsdl2-2.0-0 \
        socat \
        xz-utils && \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) ARCH_SUFFIX="x86_64-linux-gnu" ;; \
        arm64) ARCH_SUFFIX="aarch64-linux-gnu" ;; \
        *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac; \
    espressif_release=$(echo ${QEMU_VERSION} | tr - _); \
    URL="https://github.com/espressif/qemu/releases/download/${QEMU_VERSION}/qemu-riscv32-softmmu-${espressif_release}-${ARCH_SUFFIX}.tar.xz"; \
    curl -fsSL "${URL}" -o /tmp/qemu.tar.xz; \
    tar -xf /tmp/qemu.tar.xz -C /opt; \
    rm -f /tmp/qemu.tar.xz; \
    ln -s /opt/qemu/bin/qemu-system-riscv32 /usr/local/bin/qemu-system-riscv32; \
    qemu-system-riscv32 --version

RUN pip install --no-cache-dir fastapi uvicorn

WORKDIR /emulator
COPY --from=fw-builder /fw/flash_image.bin /firmware/flash_image.bin
COPY tests/hil/esp32c6-emulator/proxy.py /emulator/proxy.py

CMD ["python3", "/emulator/proxy.py"]
