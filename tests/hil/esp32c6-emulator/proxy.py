# pylint: disable=too-many-instance-attributes
"""QEMU ESP32-C6 virtual device."""

import asyncio
import os
import pty
import socket
import subprocess
import time
import tty
from collections import deque
from pathlib import Path
from typing import Any

# pylint: disable=import-error
import uvicorn
from fastapi import FastAPI

# pylint: enable=import-error
import config

DEFAULT_CONTROL_API_PORT = 9001
CONTROL_API_PORT = int(os.getenv("CONTROL_API_PORT", str(DEFAULT_CONTROL_API_PORT)))
QEMU_BIN = os.getenv("QEMU_BIN", "qemu-system-riscv32")
FLASH_IMG = os.getenv("FIRMWARE_FLASH_IMG", "/firmware/flash_image.bin")
QEMU_TCP_PORT = int(os.getenv("QEMU_TCP_PORT", "5555"))
VSERIAL_LINK = Path(config.serial_port)

app = FastAPI(title="ESP32-C6 QEMU HiL Controller")


class EmulatorBridge:
    """Manages QEMU lifecycle, PTY creation, and TX/RX serial traffic inspection."""

    def __init__(self) -> None:
        self.qemu_proc: subprocess.Popen | None = None
        self.master_fd: int = -1
        self.slave_name: str = ""
        self.qemu_sock: socket.socket | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=2000)
        self.rx_line_buf = bytearray()
        self.tx_line_buf = bytearray()
        self.disconnected = False

    def setup_pty(self) -> None:
        """Create a Linux PTY pair and symlink slave to VSERIAL_LINK."""
        self.teardown_pty()
        master_fd, slave_fd = pty.openpty()
        tty.setraw(master_fd)
        tty.setraw(slave_fd)
        os.set_blocking(master_fd, False)
        self.master_fd = master_fd
        self.slave_name = os.ttyname(slave_fd)
        os.chmod(self.slave_name, 0o666)

        VSERIAL_LINK.parent.mkdir(parents=True, exist_ok=True)
        VSERIAL_LINK.unlink(missing_ok=True)
        VSERIAL_LINK.symlink_to(self.slave_name)
        os.close(slave_fd)

    def teardown_pty(self) -> None:
        """Close PTY master and remove VSERIAL_LINK to simulate USB unplug."""
        VSERIAL_LINK.unlink(missing_ok=True)
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        self.slave_name = ""

    def set_disconnected(self, enabled: bool) -> None:
        """Simulate physical USB serial disconnect/reconnect by tearing down or recreating PTY."""
        if enabled == self.disconnected:
            return
        self.disconnected = enabled
        if enabled:
            self.teardown_pty()
        else:
            self.setup_pty()

    def start_qemu(self) -> None:
        """Launch QEMU ESP32-C6 with serial UART bound to localhost TCP."""
        self.stop_qemu()
        self.history.clear()
        self.rx_line_buf.clear()
        self.tx_line_buf.clear()
        cmd = [
            QEMU_BIN,
            "-nographic",
            "-machine",
            config.esp_chip,
            "-drive",
            f"file={FLASH_IMG},if=mtd,format=raw",
            "-serial",
            f"tcp:127.0.0.1:{QEMU_TCP_PORT},server,nowait",
        ]
        # pylint: disable=consider-using-with
        self.qemu_proc = subprocess.Popen(cmd)
        # pylint: enable=consider-using-with
        time.sleep(0.3)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(
                    ("127.0.0.1", QEMU_TCP_PORT), timeout=0.5
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setblocking(False)
                self.qemu_sock = sock
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("Timed out waiting for QEMU ESP32-C6 serial socket")

    def stop_qemu(self) -> None:
        """Terminate running QEMU process and close its serial socket."""
        sock, self.qemu_sock = self.qemu_sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if self.qemu_proc and self.qemu_proc.poll() is None:
            self.qemu_proc.terminate()
            self.qemu_proc.wait(timeout=5)
        self.qemu_proc = None

    def _record_bytes(self, direction: str, data: bytes) -> None:
        buf = self.tx_line_buf if direction == "APP_TO_ESP" else self.rx_line_buf
        buf.extend(data)
        while b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            buf[:] = rest
            self.history.append(
                {
                    "ts": round(time.time(), 3),
                    "dir": direction,
                    "line": line.decode("utf-8", errors="replace").strip(),
                }
            )
        if direction == "APP_TO_ESP" and data and b"\n" not in data:
            self.history.append(
                {
                    "ts": round(time.time(), 3),
                    "dir": direction,
                    "raw": data.decode("utf-8", errors="replace"),
                }
            )

    async def pump_forever(self) -> None:
        """Bidirectional non-blocking byte pump between PTY master and QEMU TCP."""
        while True:
            await asyncio.sleep(0.005)
            sock = self.qemu_sock
            if self.disconnected or self.master_fd < 0 or sock is None:
                continue

            try:
                from_app = os.read(self.master_fd, 4096)
                if from_app:
                    self._record_bytes("APP_TO_ESP", from_app)
                    sock.sendall(from_app)
            except (BlockingIOError, InterruptedError, OSError):
                pass

            try:
                from_esp = sock.recv(4096)
                if from_esp:
                    self._record_bytes("ESP_TO_APP", from_esp)
                    os.write(self.master_fd, from_esp)
            except (BlockingIOError, InterruptedError, OSError):
                pass


BRIDGE = EmulatorBridge()


@app.on_event("startup")
async def _startup() -> None:
    BRIDGE.setup_pty()
    BRIDGE.start_qemu()
    asyncio.create_task(BRIDGE.pump_forever())


@app.on_event("shutdown")
async def _shutdown() -> None:
    BRIDGE.stop_qemu()
    BRIDGE.teardown_pty()


@app.get("/health")
def health() -> dict[str, Any]:
    """Report QEMU process, PTY slave path, and link fault status."""
    return {
        "status": "ok",
        "qemu_running": BRIDGE.qemu_proc is not None
        and BRIDGE.qemu_proc.poll() is None,
        "pty_slave": BRIDGE.slave_name,
        "vserial_link": str(VSERIAL_LINK),
        "disconnected": BRIDGE.disconnected,
    }


@app.get("/serial/history")
def serial_history() -> dict[str, Any]:
    """Return captured serial TX/RX events."""
    return {"events": list(BRIDGE.history)}


@app.post("/serial/clear")
def serial_clear() -> dict[str, str]:
    """Clear captured serial TX/RX event buffer."""
    BRIDGE.history.clear()
    return {"status": "cleared"}


@app.post("/fault/disconnect")
def set_disconnect(enabled: bool = True) -> dict[str, bool]:
    """Enable or disable simulated USB serial disconnect."""
    BRIDGE.set_disconnected(enabled)
    return {"disconnected": BRIDGE.disconnected}


@app.post("/reboot")
def reboot_esp32() -> dict[str, str]:
    """Restart the QEMU ESP32-C6 virtual hardware."""
    BRIDGE.start_qemu()
    return {"status": "rebooted"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=CONTROL_API_PORT)
