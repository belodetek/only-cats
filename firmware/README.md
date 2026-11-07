# firmware_sketch
> examples use [XIAO ESP32-C6] micro-controller, adjust config for other variants

## cli

	# Seeed XIAO ESP32-C3: esp32:esp32:XIAO_ESP32C3
	# Seeed XIAO ESP32-S3: esp32:esp32:XIAO_ESP32S3
	# Seeed XIAO ESP32-C6: esp32:esp32:XIAO_ESP32C6
	FQBN=esp32:esp32:XIAO_ESP32C6

	arduino-cli config init
	arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
	arduino-cli core update-index
	arduino-cli core install esp32:esp32

## build
> for automatic flashing

	arduino-cli compile --fqbn ${FQBN} \
	  --build-property "build.extra_flags=-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1" \
	  --output-dir bin .

## upload
> initial flash (or manually)

	arduino-cli upload -p /dev/ttyACM0 --fqbn ${FQBN} firmware_sketch

[XIAO ESP32-C6]: https://www.seeedstudio.com/Seeed-Studio-XIAO-ESP32C6-p-5884.html
