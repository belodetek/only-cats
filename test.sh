#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.test.yml}"
MODE="${1:-unit}"
ACTIVE_PROFILE=""

cleanup() {
  local exit_code=$?
  echo ">>> Cleaning up test stack..."
  if [[ -n ${ACTIVE_PROFILE} ]]; then
    docker compose -f "${COMPOSE_FILE}" --profile "${ACTIVE_PROFILE}" down --volumes --remove-orphans || true
  else
    docker compose -f "${COMPOSE_FILE}" down --volumes --remove-orphans || true
  fi
  exit "${exit_code}"
}
trap cleanup EXIT

run_unit() {
  ACTIVE_PROFILE=""
  echo ">>> Running unit & UI tests..."
  docker compose -f "${COMPOSE_FILE}" up \
    --build \
    --force-recreate \
    --remove-orphans \
    --abort-on-container-exit \
    --exit-code-from sut \
    sut
}

run_hw() {
  ACTIVE_PROFILE="HiL"
  echo ">>> Building images for QEMU HiL tests..."
  docker compose -f "${COMPOSE_FILE}" --profile HiL build
  echo ">>> Running QEMU Hardware-in-the-Loop (HiL) tests..."
  docker compose -f "${COMPOSE_FILE}" --profile HiL up \
    --build \
    --force-recreate \
    --remove-orphans \
    --abort-on-container-exit \
    --exit-code-from sut-hil \
    sut-hil
}

case "${MODE}" in
  unit)
    run_unit
    ;;
  hw | hil)
    run_hw
    ;;
  all)
    run_unit
    docker compose -f "${COMPOSE_FILE}" down --volumes --remove-orphans || true
    run_hw
    ;;
  *)
    echo "Usage: $0 [unit|hw|all]" >&2
    exit 2
    ;;
esac
