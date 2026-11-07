"""ESP32 firmware auto-flasher using on-chip esp_app_desc_t descriptor validation."""

import logging
import os
import struct
import subprocess
import tempfile
import time
from typing import NamedTuple, Optional

logger = logging.getLogger("flasher-esp32")

DEFAULT_BIN_PATH = "firmware_bin/firmware_sketch.ino.bin"
APP_OFFSET = 0x10000  # Default factory / app0 partition offset
DESC_OFFSET = 0x20  # Offset within image to esp_app_desc_t
DESC_SIZE = 256  # Size of header block to read
ESP_APP_DESC_MAGIC = 0xABCD5432


class AppDescriptor(NamedTuple):
    """Parsed representation of ESP-IDF esp_app_desc_t header."""

    magic: int
    version: str
    project_name: str
    time: str
    date: str
    idf_ver: str
    app_elf_sha256: bytes


def parse_app_descriptor(data: bytes) -> Optional[AppDescriptor]:
    """Parse raw bytes starting at esp_app_desc_t offset into an AppDescriptor."""
    if len(data) < 144:
        return None

    # esp_app_desc_t format:
    # uint32_t magic_word
    # uint32_t secure_version
    # uint32_t reserv1[2]
    # char version[32]
    # char project_name[32]
    # char time[16]
    # char date[16]
    # char idf_ver[32]
    # uint8_t app_elf_sha256[32]
    try:
        magic = struct.unpack_from("<I", data, 0)[0]
        if magic != ESP_APP_DESC_MAGIC:
            return None

        version = data[16:48].split(b"\x00")[0].decode("utf-8", errors="ignore")
        project = data[48:80].split(b"\x00")[0].decode("utf-8", errors="ignore")
        build_time = data[80:96].split(b"\x00")[0].decode("utf-8", errors="ignore")
        build_date = data[96:112].split(b"\x00")[0].decode("utf-8", errors="ignore")
        idf_ver = data[112:144].split(b"\x00")[0].decode("utf-8", errors="ignore")
        sha256 = data[144:176] if len(data) >= 176 else b""

        return AppDescriptor(
            magic=magic,
            version=version,
            project_name=project,
            time=build_time,
            date=build_date,
            idf_ver=idf_ver,
            app_elf_sha256=sha256,
        )
    except (struct.error, ValueError):
        return None


def get_local_descriptor(bin_path: str) -> Optional[AppDescriptor]:
    """Extract app descriptor from local compiled binary."""
    if not os.path.exists(bin_path):
        return None

    try:
        with open(bin_path, "rb") as f:
            f.seek(DESC_OFFSET)
            chunk = f.read(DESC_SIZE)
            return parse_app_descriptor(chunk)
    except OSError as exc:
        logger.error("Failed to read local binary %s: %s", bin_path, exc)
        return None


def read_chip_descriptor(
    port: str, chip: str = "esp32c3", baud: int = 460800
) -> Optional[AppDescriptor]:
    """Read descriptor segment off physical ESP32 flash without rewriting firmware."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp_file:
        tmp_name = tmp_file.name

    try:
        # Read only 256 bytes starting at APP_OFFSET + DESC_OFFSET
        cmd = [
            "python",
            "-m",
            "esptool",
            "--port",
            port,
            "--chip",
            chip,
            "--baud",
            str(baud),
            "--before",
            "default_reset",
            "--after",
            "hard_reset",
            "read_flash",
            hex(APP_OFFSET + DESC_OFFSET),
            str(DESC_SIZE),
            tmp_name,
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.debug("Read flash output: %s", res.stdout)

        with open(tmp_name, "rb") as f:
            data = f.read()

        return parse_app_descriptor(data)

    except (subprocess.CalledProcessError, OSError) as exc:
        err = exc.stderr if hasattr(exc, "stderr") and exc.stderr else str(exc)
        logger.warning("Could not read chip descriptor over serial: %s", err.strip())
        return None
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def flash_firmware(port: str, chip: str, baud: int, bin_path: str) -> bool:
    """Execute esptool to flash the complete application binary."""
    logger.warning(">>> Writing firmware binary (%s) to ESP32 on %s...", bin_path, port)
    flash_cmd = [
        "python",
        "-m",
        "esptool",
        "--port",
        port,
        "--chip",
        chip,
        "--baud",
        str(baud),
        "--before",
        "default_reset",
        "--after",
        "hard_reset",
        "write_flash",
        "-z",
        hex(APP_OFFSET),
        bin_path,
    ]

    try:
        res = subprocess.run(flash_cmd, capture_output=True, text=True, check=True)
        summary = res.stdout.strip().splitlines()[-1] if res.stdout else "Done"
        logger.info("ESP32 flash completed successfully: %s", summary)
        time.sleep(2.0)  # Settle time after hardware reboot
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("ESP32 flashing failed:\n%s", exc.stderr or exc.stdout)
        return False


def auto_flash_esp32_if_updated(
    port: str,
    chip: str = "esp32c3",
    baud: int = 460800,
    bin_path: str = DEFAULT_BIN_PATH,
) -> bool:
    """Compare on-chip descriptor with local binary; flash on mismatch or missing image.

    Returns True if the chip was flashed, False if already up-to-date or skipped.
    """
    if not os.path.exists(bin_path):
        logger.info("No firmware binary found at %s. Skipping auto-flash.", bin_path)
        return False

    local_desc = get_local_descriptor(bin_path)
    if not local_desc:
        logger.error(
            "Local file %s is not a valid ESP32 application binary (missing magic header).",
            bin_path,
        )
        return False

    logger.info(
        "Local build info: project='%s', built=%s %s, idf=%s",
        local_desc.project_name,
        local_desc.date,
        local_desc.time,
        local_desc.idf_ver,
    )

    chip_desc = read_chip_descriptor(port=port, chip=chip, baud=baud)

    if chip_desc is None:
        logger.warning(
            "No valid ESP32 application descriptor found on chip (unflashed or corrupted). "
            "Proceeding with initial flash."
        )
        return flash_firmware(port, chip, baud, bin_path)

    logger.info(
        "On-chip build info: project='%s', built=%s %s, idf=%s",
        chip_desc.project_name,
        chip_desc.date,
        chip_desc.time,
        chip_desc.idf_ver,
    )

    # Compare SHA256 build hash, date, and time
    needs_flash = False
    if local_desc.app_elf_sha256 and chip_desc.app_elf_sha256:
        needs_flash = local_desc.app_elf_sha256 != chip_desc.app_elf_sha256
    else:
        needs_flash = (
            local_desc.date != chip_desc.date or local_desc.time != chip_desc.time
        )

    if needs_flash:
        logger.warning(
            ">>> Firmware mismatch detected between local binary and target ESP32. Updating..."
        )
        return flash_firmware(port, chip, baud, bin_path)

    logger.info("ESP32 on-chip firmware is identical to local build. Flashing skipped.")
    return False
