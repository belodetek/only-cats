"""ESP32 firmware auto-flashing utility using esptool."""

import hashlib
import logging
import os
import subprocess
import time

logger = logging.getLogger("hello-dimitry")

DEFAULT_BIN_PATH = "firmware_bin/firmware_sketch.ino.bin"
DEFAULT_HASH_FILE = "firmware_bin/.last_flashed_hash"


def auto_flash_esp32_if_updated(
    port: str,
    chip: str = "esp32c3",
    baud: int = 460800,
    bin_path: str = DEFAULT_BIN_PATH,
    hash_file: str = DEFAULT_HASH_FILE,
) -> bool:
    """Flash firmware.bin over USB bootloader if the file has changed.

    Returns True if a flash was executed successfully, False otherwise.
    """
    if not os.path.exists(bin_path):
        logger.info(
            "No pre-compiled firmware found at %s. Skipping auto-flash.",
            bin_path,
        )
        return False

    with open(bin_path, "rb") as f:
        current_hash = hashlib.md5(f.read()).hexdigest()

    if os.path.exists(hash_file):
        with open(hash_file, "r", encoding="utf-8") as f:
            last_hash = f.read().strip()
        if current_hash == last_hash:
            logger.info(
                "ESP32 firmware matches current binary hash. Auto-flash skipped."
            )
            return False

    logger.warning(">>> New firmware detected! Flashing ESP32 on %s...", port)

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
        "0x10000",
        bin_path,
    ]

    try:
        res = subprocess.run(flash_cmd, capture_output=True, text=True, check=True)
        summary = res.stdout.strip().splitlines()[-1] if res.stdout else "Complete"
        logger.info("ESP32 flash successful: %s", summary)

        os.makedirs(os.path.dirname(os.path.abspath(hash_file)), exist_ok=True)
        with open(hash_file, "w", encoding="utf-8") as f:
            f.write(current_hash)

        time.sleep(2.0)  # Settle time after hardware reset
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        err_msg = exc.stderr if hasattr(exc, "stderr") and exc.stderr else str(exc)
        logger.error("ESP32 auto-flash failed:\n%s", err_msg)
        return False
