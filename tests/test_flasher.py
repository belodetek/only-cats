# pylint: disable=import-error
"""Unit tests for flasher.py ESP32 descriptor parsing and auto-flash logic."""

import struct
from unittest.mock import patch

import config
import flasher


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _build_fake_firmware(
    version: str = "1.0.0",
    project: str = "ulock",
    build_time: str = "12:00:00",
    build_date: str = "Nov 16 2026",
    idf_ver: str = "v5.1",
    sha256: bytes = b"\xaa" * 32,
) -> bytes:
    """Construct a binary blob containing a valid esp_app_desc_t at DESC_OFFSET."""
    header = bytearray(flasher.DESC_OFFSET + flasher.DESC_SIZE)
    struct.pack_into("<I", header, flasher.DESC_OFFSET, flasher.ESP_APP_DESC_MAGIC)
    header[flasher.DESC_OFFSET + 16 : flasher.DESC_OFFSET + 16 + len(version)] = (
        version.encode()
    )
    header[flasher.DESC_OFFSET + 48 : flasher.DESC_OFFSET + 48 + len(project)] = (
        project.encode()
    )
    header[flasher.DESC_OFFSET + 80 : flasher.DESC_OFFSET + 80 + len(build_time)] = (
        build_time.encode()
    )
    header[flasher.DESC_OFFSET + 96 : flasher.DESC_OFFSET + 96 + len(build_date)] = (
        build_date.encode()
    )
    header[flasher.DESC_OFFSET + 112 : flasher.DESC_OFFSET + 112 + len(idf_ver)] = (
        idf_ver.encode()
    )
    header[flasher.DESC_OFFSET + 144 : flasher.DESC_OFFSET + 176] = sha256
    return bytes(header)


# pylint: enable=too-many-arguments,too-many-positional-arguments


def test_parse_app_descriptor_valid_and_invalid():
    """Verify valid magic word parses fields and bad magic returns None."""
    fw = _build_fake_firmware(version="2.3.4", project="cat-lock", sha256=b"\x11" * 32)
    desc = flasher.parse_app_descriptor(fw[flasher.DESC_OFFSET :])
    assert desc is not None
    assert desc.version == "2.3.4"
    assert desc.project_name == "cat-lock"
    assert desc.app_elf_sha256 == b"\x11" * 32

    assert flasher.parse_app_descriptor(b"\x00" * 200) is None
    assert flasher.parse_app_descriptor(b"short") is None


def test_auto_flash_skips_when_sha_matches(tmp_path, monkeypatch):
    """Verify esptool write_flash is skipped when on-chip SHA256 matches local binary."""
    bin_file = tmp_path / "fw.bin"
    fw_bytes = _build_fake_firmware(sha256=b"\xab" * 32)
    bin_file.write_bytes(fw_bytes)
    local_desc = flasher.parse_app_descriptor(fw_bytes[flasher.DESC_OFFSET :])

    monkeypatch.setattr(config, "firmware_bin_path", str(bin_file))

    with patch(
        "flasher.read_chip_descriptor", return_value=local_desc
    ) as mock_read, patch("flasher.flash_firmware") as mock_flash:
        flashed = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=config.firmware_bin_path,
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is False
    mock_read.assert_called_once_with(
        port=config.serial_port,
        chip=config.esp_chip,
        baud=config.esp_flash_baud,
    )
    mock_flash.assert_not_called()


def test_auto_flash_writes_on_sha_mismatch(tmp_path, monkeypatch):
    """Verify esptool write_flash runs when local binary SHA256 differs from chip."""
    bin_file = tmp_path / "fw.bin"
    local_fw = _build_fake_firmware(sha256=b"\xbb" * 32)
    chip_fw = _build_fake_firmware(sha256=b"\xcc" * 32)
    bin_file.write_bytes(local_fw)
    chip_desc = flasher.parse_app_descriptor(chip_fw[flasher.DESC_OFFSET :])

    monkeypatch.setattr(config, "firmware_bin_path", str(bin_file))

    with patch("flasher.read_chip_descriptor", return_value=chip_desc), patch(
        "flasher.flash_firmware", return_value=True
    ) as mock_flash:
        flashed = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=config.firmware_bin_path,
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is True
    mock_flash.assert_called_once_with(
        config.serial_port,
        config.esp_chip,
        config.esp_flash_baud,
        str(bin_file),
    )
