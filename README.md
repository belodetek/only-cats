# onlyCat(s)
> 🐈‍⬛+🐈‍⬛ Border Services Agency - preventing contraband entering the cat-flap.

[![balena deploy button](https://www.balena.io/deploy.svg)](https://dashboard.balena-cloud.com/deploy?repoUrl=https://github.com/belodetek/only-cats)

## BoM

* [REOLINK PoE Security Camera RLC-810A]
* [PoE injector]
* [Seeed Studio XIAO ESP32-C6]
* [5V single channel relay (opto-coupler) H/L trigger jumper]
* [24VDC solenoid lock NO]
* 1N4007 diode
* 2200uF 50V electrolytic capacitor
* PN2222A NPN transistor
* 1.1kΩ 0.5W resistor
* Good quality, democratically priced and sustainably sourced V19.5+ DC power supply
* Intel NUC or compatible AARCH64/AMD64 compute

## software composition

The service includes a mobile-friendly Web Control UI, behind **Traefik** and
authenticated via **oauth2-proxy** (GitHub OAuth) across both custom domain (`DOMAIN_NAME`)
and balenaCloud public device URLs (`*.balena-devices.com`):

- **Manual Lock / Unlock Overrides:** Force the cat-flap locked or unlocked persistently until changed or power-cycled.
- **System Diagnostics:** Expandable drawer displaying service status.
- **Training Images**: Captured images editor and exporter for fine-tuning the model.
- **Live Camera Feed:** Reverse-proxied access to the Reolink camera web UI (`CAT_CAM_1`).
- **[Pet-a-Manger] Shortcut:** Dynamically appears when `DISPENSER_URL` is configured, to link to the kibble-bot's web UI.

## camera/webhooks event architecture

```text
+--------------------+                +---------------------------+
| REOLINK PoE CAMERA |                |         INTEL NUC         |
|  (IP / Local)      |                |   (FastAPI on Port 8000   |
+-----+--------------+                +-----------+---------------+
      |                                           |
      | 1. Motion Detected                        |
      |    POST /webhook/reolink                  |
      |    (JSON payload: event alarm)            |
      +------------------------------------------>| [reolink_webhook]
      |                                           | Enqueues evaluation
      |<------------------------------------------+ task via BackgroundTasks
      | 2. HTTP 200 {"status": "queued"}          |
      |    (Connection closed immediately)        |
      |                                           v
      |                                [fetch_and_evaluate]
      |                                (Async background worker)
      |                                           |
      | 3. GET /cgi-bin/api.cgi?cmd=Snap          |
      |<------------------------------------------+ (Fetch raw snapshot bytes)
      |                                           |
      | 4. JPEG Snapshot Image Stream             |
      +------------------------------------------>|
                                                  |
                                                  | 5. cv2.imdecode()
                                                  |    Decode buffer to array
                                                  |
                                                  | 6. YOLO / OpenVINO Infer
                                                  |    Predict bounding boxes
                                                  |
                                                  |
                                                  |
                                           [Prey Detected?]
                                            /           \
                                      YES  /             \  NO
                                          v               v
                         +--------------------+     +-------------------+
                         | 7a. Trigger Lock   |     | 7b. Discard Frame |
                         |     Hold b'L' loop |     |     No lock state |
                         |     for 300 sec    |     |     change        |
                         +-+----------------+-+     +-------------------+
                           |                |
                           v                v
      +-----------------------+          +-----------------------------+
      | 8. BackgroundTasks    |          | 8.1 trigger snack dispenser |
      |    Offload Disk I/O   |          |     on_lockout_expired      |
      +-+-------------------+-+          +-----------------------------+
        |                   |
        v                   v
+------------------+     +---------------------+
| 9. Signal notify |     | 9.1 Persist Dataset |
+------------------+     | /data/images/*.jpg  |
                         | /data/labels/*.txt  |
                         +---------------------+
```

## physical(ish) wiring diagram

```text
 +---------------+
 |   INTEL NUC   |
 +-------+-------+
         |
         | USB (Serial + 5V)
         v
 +---------------+                              +---------------------------------------+
 |  SEEED XIAO   |                              |    5V RELAY MODULE (OPTO ISOLATED)    |
 |   ESP32-C6    |                              |    * Jumper set to LOW-TRIGGER (L)    |
 |               |                              |      (Center pin reads 5.0V to GND)   |
 |               |                              |                                       |
 |            5V +------------------------------|-> [VCC]                               |
 |               |                              |                                       |
 |   (GPIO0)  D0 +---[ 1.1kΩ 0.5W ]---+         |                                       |
 |               |                    |         |                                       |
 |               |                    v (Base)  |                                       |
 |               |              +-----------+   |                                       |
 |               |              |  PN2222A  |   |                                       |
 |               |              | (TO-92-3) |   |                                       |
 |               |              |  E  B  C  |   |                                       |
 |               |              +--+-----+--+   |                                       |
 |               |                 |     +------|-> [IN]  (Collector sinks IN to GND)   |
 |               |                 |            |                                       |
 |           GND +-----------------+------------|-> [GND] (Common Ground + Emitter)     |
 +---------------+                              |                                       |
                                                | [COM]            [NO] (normally open) |
 +---------------+                              +---+---------------+-------------------+
 |  19.5V/24V    |                                  |               |
 |     PSU       |                                  |               |
 |          [V+] +----------------------------------+               |
 |          [V-] +------------------------------+                   |
 +---------------+                              |                   |
                                                |                   |
                                                v                   v
                                        +-------+-------------------+-----+
                                        |        C1  (2200uF >=50V)       |
                                        |       [-] to V-, [+] to NO      |
                                        +-------+-------------------+-----+
                                                |                   |
                                                v                   v
                                        +-------+-------------------+-----+
                                        |            D1 (1N4007)          |
                                        | anode to V-, cathode/band to NO |
                                        +-------+-------------------+-----+
                                                |                   |
                                                v                   v
                                        +-------+-------------------+-----+
                                        |        LED+resistor package     |
                                        |      V-                   V+    |
                                        +-------+-------------------+-----+
                                                |                   |
                                                v                   v
                                        +-----------------------------------+
                                        |         24V LOCK SOLENOID         |
                                        |        NO - normally open         |
                                        +-----------------------------------+
```

[Pet-a-Manger]: https://pet-a-manger.pages.dev/
[REOLINK PoE Security Camera RLC-810A]: https://www.amazon.ca/dp/B08MQ61MKN
[PoE injector]: https://www.amazon.ca/dp/B07PR9CBGL
[5V single channel relay (opto-coupler) H/L trigger jumper]: https://www.aliexpress.com/item/1005004493713732.html
[24VDC solenoid lock NO]: https://www.aliexpress.com/item/1005006233548116.html
[Seeed Studio XIAO ESP32-C6]: https://www.aliexpress.com/item/1005008884996574.html
