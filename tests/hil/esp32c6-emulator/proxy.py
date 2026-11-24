# pylint: disable=too-many-instance-attributes
"""QEMU ESP32-C6 virtual device."""

import asyncio
import os
import pty
import shutil
import socket
import subprocess
import time
import tty
from collections import deque
from contextlib import asynccontextmanager
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

# ESP32-C6 GPIO_STRAP_REG values:
#   0x08 -> boot:0x8 (SPI_FAST_FLASH_BOOT)
#   0x04 -> boot:0x4 (DOWNLOAD(USB/UART0/SDIO_FEI_FEO))
STRAP_FLASH_BOOT = 0x08
STRAP_DOWNLOAD_BOOT = 0x04

# esptool SLIP frames: SYNC (cmd 0x08) and FLASH_END (cmd 0x04 / 0x12)
SLIP_SYNC_PREFIX = b"\xc0\x00\x08"
SLIP_FLASH_END_FRAME = b"\xc0\x00\x04\x04\x00"
SLIP_FLASH_DEFL_END_FRAME = b"\xc0\x00\x12\x04\x00"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Copy compiled UART0 binary, start PTY + QEMU, and run byte pump."""
    src_bin = Path("/fw/out/firmware_sketch.ino.bin")
    if src_bin.is_file():
        VSERIAL_LINK.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_bin, VSERIAL_LINK.parent / "firmware_sketch.ino.bin")
    BRIDGE.setup_pty()
    BRIDGE.start_qemu(download_mode=False)
    task = asyncio.create_task(BRIDGE.pump_forever())
    try:
        yield
    finally:
        task.cancel()
        BRIDGE.stop_qemu()
        BRIDGE.teardown_pty()


app = FastAPI(title="ESP32-C6 QEMU HiL Controller", lifespan=lifespan)


class EmulatorBridge:
    """Manages QEMU lifecycle, PTY creation, and TX/RX serial traffic inspection."""

    def __init__(self) -> None:
        self.qemu_proc: subprocess.Popen | None = None
        self.master_fd: int = -1
        self.keepalive_slave_fd: int = -1
        self.slave_name: str = ""
        self.qemu_sock: socket.socket | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=2000)
        self.rx_line_buf = bytearray()
        self.tx_line_buf = bytearray()
        self.tx_slip_buf = bytearray()
        self.disconnected = False
        self.download_mode = False
        self.slip_rx_synced = False

    def setup_pty(self) -> None:
        """Create a Linux PTY pair and symlink slave to VSERIAL_LINK."""
        self.teardown_pty()
        master_fd, slave_fd = pty.openpty()
        tty.setraw(master_fd)
        tty.setraw(slave_fd)
        os.set_blocking(master_fd, False)
        self.master_fd = master_fd
        self.keepalive_slave_fd = slave_fd
        self.slave_name = os.ttyname(slave_fd)
        os.chmod(self.slave_name, 0o666)

        VSERIAL_LINK.parent.mkdir(parents=True, exist_ok=True)
        VSERIAL_LINK.unlink(missing_ok=True)
        VSERIAL_LINK.symlink_to(self.slave_name)

    def teardown_pty(self) -> None:
        """Close PTY fds and remove VSERIAL_LINK to simulate USB unplug."""
        VSERIAL_LINK.unlink(missing_ok=True)
        for attr in ("keepalive_slave_fd", "master_fd"):
            fd = getattr(self, attr)
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, -1)
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

    def start_qemu(self, download_mode: bool = False) -> None:
        """Launch QEMU ESP32-C6 with serial UART bound to localhost TCP."""
        self.stop_qemu()
        self.download_mode = download_mode
        self.slip_rx_synced = False
        self.rx_line_buf.clear()
        self.tx_line_buf.clear()
        self.tx_slip_buf.clear()
        strap_val = STRAP_DOWNLOAD_BOOT if download_mode else STRAP_FLASH_BOOT
        cmd = [
            QEMU_BIN,
            "-accel",
            "tcg,thread=multi",
            "-nographic",
            "-machine",
            config.esp_chip,
            "-drive",
            f"file={FLASH_IMG},if=mtd,format=raw",
            "-global",
            f"driver=esp32c6.gpio,property=strap_mode,value={strap_val}",
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
        self.stop_qemu()
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

    async def _enter_download_mode_and_wait_banner(self) -> None:
        """Reboot QEMU into UART download mode (strap_mode=0x04) and consume ROM banner."""
        self.start_qemu(download_mode=True)
        deadline = time.monotonic() + 5.0
        banner = bytearray()
        while time.monotonic() < deadline:
            sock = self.qemu_sock
            if sock is None:
                return
            try:
                chunk = sock.recv(4096)
                if chunk:
                    self._record_bytes("ESP_TO_APP", chunk)
                    banner.extend(chunk)
                    if (
                        b"waiting for download" in banner
                        and b"\n" in banner.split(b"waiting for download", 1)[1]
                    ):
                        return
            except (BlockingIOError, InterruptedError, OSError):
                pass
            await asyncio.sleep(0.01)

    def _extract_sync_frame(self, from_app: bytes) -> bytes | None:
        """Buffer TX bytes in flash-boot mode and return the SLIP SYNC frame if seen."""
        self.tx_slip_buf.extend(from_app)
        if len(self.tx_slip_buf) > 128:
            del self.tx_slip_buf[:-128]
        if SLIP_SYNC_PREFIX not in self.tx_slip_buf:
            return None
        idx = self.tx_slip_buf.rfind(SLIP_SYNC_PREFIX)
        tail = bytes(self.tx_slip_buf[idx:])
        end = tail.find(b"\xc0", 1)
        self.tx_slip_buf.clear()
        return tail[: end + 1] if end != -1 else b""

    async def _pump_tx(self) -> None:
        """Read bytes from PTY master and forward them to QEMU's UART socket."""
        try:
            from_app = os.read(self.master_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError as exc:
            self._record_bytes("BRIDGE_ERR", f"tx: {exc}\n".encode())
            return

        if not from_app:
            return
        self._record_bytes("APP_TO_ESP", from_app)

        try:
            if not self.download_mode:
                sync_frame = self._extract_sync_frame(from_app)
                if sync_frame is not None:
                    await self._enter_download_mode_and_wait_banner()
                    if self.qemu_sock is not None and sync_frame:
                        self.qemu_sock.sendall(sync_frame)
                    return

            if self.qemu_sock is not None:
                self.qemu_sock.sendall(from_app)
            if self.download_mode and (
                SLIP_FLASH_END_FRAME in from_app
                or SLIP_FLASH_DEFL_END_FRAME in from_app
            ):
                await asyncio.sleep(0.3)
                self.start_qemu(download_mode=False)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as exc:
            self._record_bytes("BRIDGE_ERR", f"tx: {exc}\n".encode())

    def _pump_rx(self) -> None:
        """Read bytes from QEMU's UART socket and write them to the PTY master."""
        sock = self.qemu_sock
        if sock is None:
            return
        try:
            from_esp = sock.recv(4096)
            if not from_esp:
                return
            self._record_bytes("ESP_TO_APP", from_esp)
            if self.download_mode and not self.slip_rx_synced:
                if b"\xc0" not in from_esp:
                    return
                from_esp = from_esp[from_esp.index(b"\xc0") :]
                self.slip_rx_synced = True
            os.write(self.master_fd, from_esp)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as exc:
            self._record_bytes("BRIDGE_ERR", f"rx: {exc}\n".encode())

    async def pump_forever(self) -> None:
        """Bidirectional non-blocking byte pump between PTY master and QEMU TCP."""
        while True:
            await asyncio.sleep(0.005)
            if self.disconnected or self.master_fd < 0 or self.qemu_sock is None:
                continue
            await self._pump_tx()
            self._pump_rx()


BRIDGE = EmulatorBridge()


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
        "download_mode": BRIDGE.download_mode,
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
    BRIDGE.start_qemu(download_mode=False)
    return {"status": "rebooted"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=CONTROL_API_PORT)
