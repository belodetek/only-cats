# onlyCat(s)
> Border Services Agency, preventing contraband entering the catflap.

Multi-arch project deployed to balenaCloud using Flowzone with default AMD64 arch.

## ESP32
> examples use [XIAO ESP32-C6] micro-controller, adjust config for other variants

### for upload
> initial flash (or manually)

	# Seeed XIAO ESP32-C3: esp32:esp32:XIAO_ESP32C3
	# Seeed XIAO ESP32-S3: esp32:esp32:XIAO_ESP32S3
	# Seeed XIAO ESP32-C6: esp32:esp32:XIAO_ESP32C6
	fqbn=esp32:esp32:XIAO_ESP32C6

	arduino-cli config init
	arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
	arduino-cli core update-index
	arduino-cli core install esp32:esp32

	arduino-cli compile --fqbn ${fqbn} \
	  --build-property "build.extra_flags=-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1" \
	  firmware_sketch

	arduino-cli upload -p /dev/ttyACM0 --fqbn esp32:esp32:${mc_variant} firmware_sketch

### build binary
> for automatic flashing

	arduino-cli compile --fqbn ${fqbn} \
	  --build-property "build.extra_flags=-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1" \
	  --output-dir ./firmware_bin firmware_sketch

## train

	python3.12 -m venv .venv
	source .venv/bin/activate

	pip install --upgrade pip
	pip install ultralytics torch torchvision numpy

	# https://universe.roboflow.com/flappie/prey-detection
	unzip -q Prey-detection.v1i.yolov11.zip -d training/prey_dataset
	# training
	# ├── prey_dataset
	# │   ├── data.yaml
	# │   ├── README.dataset.txt
	# │   ├── README.roboflow.txt
	# │   ├── test
	# │   │   ├── images
	# │   │   └── labels
	# │   ├── train
	# │   │   ├── images
	# │   │   └── labels
	# │   └── valid
	# │       ├── images
	# │       └── labels
	# └── train.py

    pushd training

	cp prey_data.yaml prey_dataset/data.yaml

	python train.py

	# find the last generated weights
	find ../runs -type f -name best.pt | xargs -I{} cp {} ../prey_runs/yolo11_prey/weights


[XIAO ESP32-C6]: https://www.seeedstudio.com/Seeed-Studio-XIAO-ESP32C6-p-5884.html
