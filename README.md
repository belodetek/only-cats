# onlyCat(s)
> 🐈‍⬛+🐈‍⬛ Border Services Agency - preventing contraband entering the cat-flap.

[![balena deploy button](https://www.balena.io/deploy.svg)](https://dashboard.balena-cloud.com/deploy?repoUrl=https://github.com/belodetek/only-cats)

## BoM

* [REOLINK PoE Security Camera RLC-810A]
* [PoE injector]
* [Seeed Studio XIAO ESP32-C6]
* [5V single channel relay (opto-coupler) H/L trigger jumper]
* [24VDC solenoid lock (N)ormally(O)pen]
* D1: 1N4007 diode
* C1: 2200uF 50V
* R1: 10Ω 2W
* Good quality, democratically priced and sustainably sourced 24VDC power supply
* Intel NUC or compatible AARCH64/AMD64 compute

## software composition

The service includes a mobile-friendly Web Control UI, behind **Traefik** and
authenticated via **oauth2-proxy** (GitHub OAuth) across both custom domain (`DOMAIN_NAME`)
and balenaCloud public device URLs (`*.balena-devices.com`):

- **Manual Lock / Unlock Overrides:** Force the cat-flap locked or unlocked persistently
  until changed or power-cycled.
- **System Diagnostics:** Expandable drawer displaying service status.
- **Training Images**: Captured images editor and exporter for fine-tuning the model.
- **Live Camera Feed:** Reverse-proxied access to the Reolink camera web UI (`CAT_CAM_1`).
- **Prometheus Metrics:** Built-in visualisation of runtime (in-memory) metrics.
- **[Pet-a-Manger] Shortcut:** Dynamically appears when `DISPENSER_URL` is configured, to
  link to the kibble-bot's web UI.

## camera/webhooks event architecture

```text
+--------------------+                +---------------------------+
| REOLINK PoE CAMERA |                |         INTEL NUC         |
|  (IP / Local)      |                |   (FastAPI on Port 8000)  |
+-----+--------------+                +-----------+---------------+
      |                                           |
      | 1. Motion Detected (ANIMAL)               |
      |    POST /webhook/reolink                  |
      |    (JSON payload: event alarm)            |
      +------------------------------------------>| [reolink_webhook]
      |                                           | 1a. Immediate Pre-Lock:
      |                                           |     trigger_lock(15s,
      |                                           |     dispense_on_expire=False)
      |                                           |     -> Hold b'L' loop
      |                                           | 1b. Enqueue evaluation
      |<------------------------------------------+     task via BackgroundTasks
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
                                                  | 6. Two-Stage Cascade Infer
                                                  |    6a. Stage 2 Full-Frame:
                                                  |        Prey OpenVINO model
                                                  |    6b. Stage 1 Cat Gate:
                                                  |        yolo26s INT8 OpenVINO
                                                  |        (classes=[15, 16])
                                                  |        -> +20% padded ROI crop(s)
                                                  |    6c. Stage 2 Crop Infer:
                                                  |        Prey model on cat crop(s)
                                                  |        -> Remap [0,1] + IoU NMS
                                                  |
                                           [Prey Detected?]
                                            /            \
                                      YES  /              \  NO
                                          v                v
                         +--------------------+     [IN_TRAINING?]
                         | 7a. Extend Lock    |       /        \
                         |     Hold b'L' loop |  YES /          \ NO
                         |     to 300s + set  |     v            v
                         |     dispense=True  |  +---------+  +-------------------+
                         +-+----------------+-+  | 7b. Let |  | 7c. Discard Frame |
                           |                |    | 15s pre |  |     Let 15s pre-  |
                           v                |    | -lock   |  |     lock expire   |
      +-----------------------+             |    | expire  |  |     (no dispense) |
      | 8. BackgroundTasks    |             |    +----+----+  +-------------------+
      |    Offload Disk I/O   |             |         |
      +-+-------------------+-+             v         |
        |                   |   +------------------+  |
        v                   |   | 8.1 Snack Disp.  |  |
+------------------+        |   | on_lockout_exp.  |  |
| 9. Signal notify |        |   +------------------+  |
+------------------+        |                         |
                            +------------+------------+
                                         |
                                         v
                              +---------------------+
                              | 9.1 Persist Dataset |
                              | /data/images/*.jpg  |
                              | /data/labels/*.txt  |
                              | /data/labels/*.json |
                              +---------------------+
```

## physical wiring diagram

```text
 +---------------+                   +---------------------------------------+
 |   INTEL NUC   |                   |    5V RELAY MODULE (OPTO ISOLATED)    |
 +-------+-------+                   |    * Trigger Jumper on [H] (HIGH)     |
         | USB-C                     |                                       |
         v                           |  Control Header      Screw Terminals  |
 +---------------+                   |  --------------      ---------------  |
 |  SEEED XIAO   |                   |                                       |
 |   ESP32-C6    |                   |                                       |
 |            5V +------------------>| [VCC]                                 |
 |   (GPIO0)  D0 +------------------>| [IN]                                  |
 |           GND +------------------>| [GND]                                 |
 +---------------+                   |                                       |
                                     |                      [COM]  [NO] [NC] |
                                     +------------------------+-----+--------+
                                                              |     |
                            +---------------------------------+     |
                            |                                       |
                            |   +---( Junction A: Switched +24V )---+
                            |   |
                            |   |
                            |   +---> [ R1: 10Ω 2W ] ---> ( C1 [+] )
                            |   |                         (2200µF 50V)
                            |   |                         ( C1 [-] ) ---+
                            |   |                                       |
                            |   +---> [|<| D1: 1N4007 ] ----------------+
                            |   |     (White stripe toward Junction A)  |
                            |   |                                       |
                            |   +---> [ LED+resistor V+ ] ---[ V- ]-----+
                            |   |                                       |
                            |   +---> [ 24V Lock Solenoid V+ ] -[ V- ]--+
                            |                                           |
 +---------------+          |                                           |
 |   24VDC PSU   |          |                                           |
 |               |          |                                           |
 |          [V+] +----------+                                           |
 |          [V-] +--------------( Junction B: Common 24V Return )-------+
 +---------------+
```

[Pet-a-Manger]: https://pet-a-manger.pages.dev/
[REOLINK PoE Security Camera RLC-810A]: https://www.amazon.ca/dp/B08MQ61MKN
[PoE injector]: https://www.amazon.ca/dp/B07PR9CBGL
[5V single channel relay (opto-coupler) H/L trigger jumper]: https://www.aliexpress.com/item/1005004493713732.html
[24VDC solenoid lock (N)ormally(O)pen]: https://www.aliexpress.com/item/1005006233548116.html
[Seeed Studio XIAO ESP32-C6]: https://www.aliexpress.com/item/1005008884996574.html
