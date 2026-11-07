"""config class"""

import os

level = os.getenv("LOG_LEVEL", "INFO")
app_name = os.getenv("APP_NAME", "iwatch-ulock")

camera_url = os.getenv("CAMERA_URL")  # http(s)://10.42.84.168
camera_user = os.getenv("CAMERA_USER", "admin")
camera_password = os.getenv("CAMERA_PASSWORD")
camera_channel = int(os.getenv("CAMERA_CHANNEL", "0"))

model_weights_path = os.getenv(
    "MODEL_WEIGHTS_PATH", "prey_runs/yolo11_prey/weights/best.pt"
)
conf_threshold = float(os.getenv("CONF_THRESHOLD", "0.55"))
target_classes = os.getenv("TARGET_CLASSES", "prey,0")
target_classes = {item.strip() for item in target_classes.split(",") if item.strip()}

serial_port = os.getenv("SERIAL_PORT", "/dev/ttyACM0")
baud_rate = int(os.getenv("BAUD_RATE", "115200"))
esp_chip = os.getenv("ESP_CHIP", "esp32c3")
esp_flash_baud = int(os.getenv("ESP_FLASH_BAUD", "460800"))
firmware_bin_path = os.getenv(
    "FIRMWARE_BIN_PATH", "firmware_bin/firmware_sketch.ino.bin"
)
firmware_hash_file = os.getenv("FIRMWARE_HASH_FILE", "firmware_bin/.last_flashed_hash")

command_interval_sec = float(os.getenv("COMMAND_INTERVAL_SEC", "1.0"))
lockout_duration_sec = float(os.getenv("LOCKOUT_DURATION_SEC", "300.0"))
