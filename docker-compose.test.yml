---
services:
  sut:
    build: .
    command: >
      sh -c "pip install --no-cache-dir pytest pytest-asyncio &&
             pytest -v --tb=short tests/"
    environment:
      LOG_LEVEL: DEBUG
      APP_NAME: iwatch-ulock-test
      DATA_DIR: /tmp/test-data
      CAMERA_URL: https://192.168.10.108
      CAMERA_USER: test-user
      CAMERA_PASSWORD: test-password
      MODEL_WEIGHTS_PATH: /tmp/test-data/nonexistent_weights
      SERIAL_PORT: /dev/null
      CONF_THRESHOLD: "0.55"
      TARGET_CLASSES: prey
      LOCKOUT_DURATION_SEC: "5.0"
      COMMAND_INTERVAL_SEC: "0.05"
      DISPENSER_URL: http://ifeed:8000/dispense
      DISPENSER_USER: admin
      DISPENSER_PASSWORD: secret
      SIGNAL_API_URL: http://signal-api:8080
      SIGNAL_SENDER: "+12505550100"
      SIGNAL_RECIPIENTS: "group.testGroupId123="
    volumes:
      - .:/app
