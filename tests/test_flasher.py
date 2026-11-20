# pylint: disable=import-error
"""Unit tests for flasher.py ESP32 descriptor parsing and auto-flash logic."""

import struct
from unittest.mock import patch

import config
import flasher


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _build_fake_firmware(
    version: str = "a1b2c3d",
    project: str = "only-cats-lock",
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
    """Verify valid magic word parses short Git SHA and bad magic returns None."""
    fw = _build_fake_firmware(
        version="2f9e81c", project="only-cats-lock", sha256=b"\x11" * 32
    )
    desc = flasher.parse_app_descriptor(fw[flasher.DESC_OFFSET :])
    assert desc is not None
    assert desc.version == "2f9e81c"
    assert desc.project_name == "only-cats-lock"
    assert desc.app_elf_sha256 == b"\x11" * 32

    assert flasher.parse_app_descriptor(b"\x00" * 200) is None
    assert flasher.parse_app_descriptor(b"short") is None


def test_auto_flash_skips_when_sha_matches(tmp_path, monkeypatch):
    """Verify esptool write_flash is skipped and descriptors are returned on match."""
    bin_file = tmp_path / "fw.bin"
    fw_bytes = _build_fake_firmware(version="a1b2c3d", sha256=b"\xab" * 32)
    bin_file.write_bytes(fw_bytes)
    expected_desc = flasher.parse_app_descriptor(fw_bytes[flasher.DESC_OFFSET :])

    monkeypatch.setattr(config, "firmware_bin_path", str(bin_file))

    with patch(
        "flasher.read_chip_descriptor", return_value=expected_desc
    ) as mock_read, patch("flasher.flash_firmware") as mock_flash:
        flashed, active_desc, local_desc = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=config.firmware_bin_path,
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is False
    assert active_desc == expected_desc
    assert local_desc == expected_desc
    assert active_desc is not None and active_desc.version == "a1b2c3d"
    mock_read.assert_called_once_with(
        port=config.serial_port,
        chip=config.esp_chip,
        baud=config.esp_flash_baud,
    )
    mock_flash.assert_not_called()


def test_auto_flash_writes_on_sha_mismatch(tmp_path, monkeypatch):
    """Verify esptool write_flash runs on SHA mismatch and returns updated descriptor."""
    bin_file = tmp_path / "fw.bin"
    local_fw = _build_fake_firmware(version="new1234", sha256=b"\xbb" * 32)
    chip_fw = _build_fake_firmware(version="old0000", sha256=b"\xcc" * 32)
    bin_file.write_bytes(local_fw)
    chip_desc = flasher.parse_app_descriptor(chip_fw[flasher.DESC_OFFSET :])

    monkeypatch.setattr(config, "firmware_bin_path", str(bin_file))

    with patch("flasher.read_chip_descriptor", return_value=chip_desc), patch(
        "flasher.flash_firmware", return_value=True
    ) as mock_flash:
        flashed, active_desc, local_desc = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=config.firmware_bin_path,
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is True
    assert active_desc is not None and active_desc.version == "new1234"
    assert local_desc is not None and local_desc.version == "new1234"
    mock_flash.assert_called_once_with(
        config.serial_port,
        config.esp_chip,
        config.esp_flash_baud,
        str(bin_file),
    )


def test_auto_flash_initial_provision_and_missing_binary(tmp_path):
    """Verify unprovisioned chip flashes initial image and missing binary still reads chip."""
    bin_file = tmp_path / "fw.bin"
    local_fw = _build_fake_firmware(version="init789", sha256=b"\xdd" * 32)
    bin_file.write_bytes(local_fw)

    with patch("flasher.read_chip_descriptor", return_value=None), patch(
        "flasher.flash_firmware", return_value=True
    ) as mock_flash:
        flashed, active_desc, local_desc = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=str(bin_file),
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is True
    assert active_desc is not None and active_desc.version == "init789"
    assert local_desc is not None and local_desc.version == "init789"
    mock_flash.assert_called_once()

    missing_bin = tmp_path / "does_not_exist.bin"
    existing_chip_desc = flasher.parse_app_descriptor(local_fw[flasher.DESC_OFFSET :])
    with patch("flasher.read_chip_descriptor", return_value=existing_chip_desc):
        flashed, active_desc, local_desc = flasher.auto_flash_esp32_if_updated(
            port=config.serial_port,
            bin_path=str(missing_bin),
            chip=config.esp_chip,
            baud=config.esp_flash_baud,
        )

    assert flashed is False
    assert active_desc == existing_chip_desc
    assert local_desc is None
