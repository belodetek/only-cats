"""config class"""

import os

level = os.getenv("LOG_LEVEL", "INFO")
app_name = os.getenv("APP_NAME", "iwatch-ulock")

camera_url = os.getenv(
    "CAMERA_URL"
)  # http(s)://10.42.84.168 (from client request if unset)
camera_user = os.getenv("CAMERA_USER", "admin")  # recommend creating a read-only user
camera_password = os.getenv("CAMERA_PASSWORD")
camera_channel = int(os.getenv("CAMERA_CHANNEL", "0"))

model_weights_path = os.getenv("MODEL_WEIGHTS_PATH", "weights/best_openvino_model")
data_root = os.getenv("DATA_DIR", "/data")
images_dir = os.path.join(data_root, os.getenv("IMAGES_DIR", "images"))
labels_dir = os.path.join(data_root, os.getenv("LABELS_DIR", "labels"))

conf_threshold = float(os.getenv("CONF_THRESHOLD", "0.55"))
target_classes = os.getenv("TARGET_CLASSES", "prey")
target_classes = {item.strip() for item in target_classes.split(",") if item.strip()}

# Seeed XIAO ESP32-C3: esp32c3
# Seeed XIAO ESP32-S3: esp32s3
# Seeed XIAO ESP32-C6: esp32c6
esp_chip = os.getenv("ESP_CHIP", "esp32c6")

esp_flash_baud = int(os.getenv("ESP_FLASH_BAUD", "460800"))
firmware_bin_path = os.getenv("FIRMWARE_BIN_PATH", "flash/firmware_sketch.ino.bin")
serial_port = os.getenv("SERIAL_PORT", "/dev/ttyACM0")
baud_rate = int(os.getenv("BAUD_RATE", "115200"))

command_interval_sec = float(os.getenv("COMMAND_INTERVAL_SEC", "1.0"))
lockout_duration_sec = float(os.getenv("LOCKOUT_DURATION_SEC", "300.0"))
