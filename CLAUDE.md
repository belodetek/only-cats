# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

onlyCat(s) is a cat-flap "border control" system: a Reolink PoE camera posts motion webhooks to a
FastAPI service running on an Intel NUC; the service runs YOLO/OpenVINO inference on a camera
snapshot, and if **prey** is detected it commands a serially-attached ESP32 (Seeed XIAO) to energize
a solenoid lock on the cat-flap for a lockout window, persists the image + labels for retraining, and
sends a Signal alert. Deployed as a multi-container balena application fronted by Traefik +
oauth2-proxy (GitHub OAuth). The Python app's internal name is `iwatch-ulock`.

## Commands

Local dev (host Python; the app expects `src` on the path):

```bash
pip install -r requirements.txt
PYTHONPATH=src uvicorn only_cats:app --reload --port 8000   # run from repo root
```

Tests run **in Docker** (they need Traefik, oauth2-proxy, a mock camera, and Playwright/Chromium):

```bash
# Unit tests (tests/unit) — the default suite
docker compose -f docker-compose.test.yml run --rm --remove-orphans sut
docker compose -f docker-compose.test.yml down --volumes

# A single test
docker compose -f docker-compose.test.yml run --rm sut pytest -v tests/unit/test_evaluator.py::test_name

# Hardware-in-the-Loop (QEMU ESP32-C6 emulator + virtual serial) — opt-in profile
docker compose -f docker-compose.test.yml --profile HiL up --build \
  --abort-on-container-exit --exit-code-from sut-hil sut-hil
docker compose -f docker-compose.test.yml --profile HiL down --volumes
```

Pytest config lives in `pyproject.toml`: `asyncio_mode = "auto"` (no `@pytest.mark.asyncio`
needed), `testpaths = tests/unit`, and the `hil` marker is excluded from the default run.

Lint/format via pre-commit (black, isort `--profile black`, pylint, biome for JS/CSS/HTML, shfmt/shellcheck):

```bash
pre-commit run --all-files
```

## Architecture

**Flat module layout, not a package.** Everything in `src/` imports siblings by bare name
(`import config`, `from state import AppState`). This only works because `PYTHONPATH=src` is set
everywhere (Dockerfiles, compose, `pyproject.toml` `pythonpath`). Do not convert to relative imports.

**Runtime wiring** — `only_cats.py` is the FastAPI entrypoint. On `lifespan` startup it builds a
single `AppState` (`state.py`) holding all shared deps (ESP32 controller, YOLO model, httpx client,
eval semaphore) and stashes it on `app.state.deps`; request handlers pull it from there rather than
using globals. Two HTTP middlewares enforce security headers/CSP and CSRF (Origin + `X-Requested-With`
checks on `/ui/*` mutations). Routers: `api_routes.py` (webhook, lock/unlock, health, metrics) and
`web_ui.py` (`/` dashboard + `/ui/*` JSON endpoints + dataset editor + camera redirect).

**The detection pipeline** (`api_routes.reolink_webhook` → `evaluator.fetch_and_evaluate`): the
webhook verifies a shared secret, filters on allowed alarm types, and returns `202`-style immediately
while enqueuing the real work via FastAPI `BackgroundTasks`. `evaluator._run_evaluation_pipeline`
fetches a snapshot, runs YOLO in a thread (`asyncio.to_thread`), and on a prey/TEST match calls
`trigger_lock` + `persist_and_notify`. A `Semaphore(1)` plus `pending_evaluations` counter drops
redundant webhook bursts (only one eval in flight, one queued). The camera base URL is resolved from
the webhook's **client IP** (`utils.resolve_camera_url`), falling back to `CAMERA_URL`.

**ESP32 serial controller** (`esp32.py`) is the safety-critical piece. The firmware is **fail-safe
open**: it unlocks automatically if it stops receiving `L` within ~3s. So the controller runs a
background thread (`_command_loop`) that *continuously re-sends* `L` as a keepalive for the whole
lockout window — the lock is held by repetition, not a single command. Single-char serial protocol:
`L`=lock, `U`=unlock, `P`=ping; firmware replies `ACK:*` / `EVENT:*`. Admin overrides
(`/lock`, `/unlock`) set a sticky `admin_override` that suppresses prey-driven lockouts until cleared.
When a prey lockout expires naturally, the loop fires `on_lockout_expired`, which triggers the food
dispenser (`dispenser.py`). The firmware source is in `firmware/firmware_sketch/`; the prebuilt binary
(`firmware/bin/firmware_sketch.ino.bin`) is flashed over the serial bootloader at startup by
`flasher.py` only when the on-chip `esp_app_desc_t` version differs from the local binary's.

**Model & dataset** — `vision.py` runs inference; `dataset.py` persists captures as a clean
JPEG (EXIF stripped) + YOLO `.txt` labels + sidecar `.json` under `DATA_DIR` (`/data/images`,
`/data/labels`). With `IN_TRAINING=true`, non-prey frames are also saved (prefix `train`) to grow the
dataset. The Web UI exposes a triage/label editor and a `export.zip` of the dataset. An `ofelia` cron
container purges data older than 90 days. Fine-tuning happens offline under `training/` (see
`training/README.md`); the Docker build copies `training/runs/latest/weights/` into the image as
`weights/` (an OpenVINO model dir by default).

**Metrics** (`metrics.py`) is a module-level singleton `METRICS` over a custom prometheus
`CollectorRegistry`, exposed at `/metrics` and surfaced in the UI. Tests swap it out by monkeypatching
`METRICS` across every importing module (see `conftest._patch_metrics_store`) — if you add a new module
that imports `METRICS`, add it there too.

**Config** (`config.py`) is a flat module of module-level constants read from env vars at import time
(no Settings class). Tests override these by monkeypatching `config.*` attributes
(`conftest._BASE_CONFIG_OVERRIDES`), so read config through the `config` module at call time rather
than copying values into local defaults. Version/repo default to values parsed out of `balena.yml`.

## Deployment & CI

- Runtime topology is `docker-compose.yml`: `traefik` (TLS via Gandi ACME) → `oauth2-proxy` (GitHub
  OAuth) → `iwatch-ulock` (this app), plus `signal-api`, `error-pages`, and the `ipurge` cron. Traefik
  dynamic routing config is in `traefik/dynamic/`.
- The app container needs the USB serial device (`/dev/ttyACM0`) and `dialout` group access.
- CI is balena **Flowzone** (`.github/workflows/flowzone.yml`); it runs the `HiL` test matrix entry and
  publishes balena releases + the `ghcr.io/belodetek/only-cats` image. Releases are cut by versionbot
  (`.versionbot/`, `CHANGELOG.yml`); `VERSION` and `balena.yml` version are bot-managed — don't bump by hand.
