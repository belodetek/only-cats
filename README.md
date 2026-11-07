# onlyCat(s)
> Border Services Agency, preventing contraband entering the catflap.

## camera/webhooks event architecture

    +--------------------+                +-----------------------------------------+
    | REOLINK PoE CAMERA |                |                INTEL NUC                |
    |  (IP / Local)      |                |          (FastAPI on Port 8000)         |
    +-------+------------+                +--------------------+--------------------+
            |                                              |
            | 1. Motion Detected                           |
            |    POST /webhook/reolink                     |
            |    (JSON payload: event alarm)               |
            +--------------------------------------------->|  [reolink_webhook]
            |                                              |  Enqueues evaluation
            |<---------------------------------------------+  task via BackgroundTasks
            | 2. HTTP 200 {"status": "queued"}             |
            |    (Connection closed immediately)           |
            |                                              |
            |                                              v
            |                                   [fetch_and_evaluate]
            |                                   (Async background worker)
            |                                              |
            | 3. GET /cgi-bin/api.cgi?cmd=Snap             |
            |<---------------------------------------------+  (Fetch raw snapshot bytes)
            |                                              |
            | 4. JPEG Snapshot Image Stream                |
            +--------------------------------------------->|
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
                             +----------+---------+     +-------------------+
                                        |
                                        v
                             +---------------------+
                             | 8. BackgroundTasks  |
                             |    Offload Disk I/O |
                             +----------+----------+
                                        |
                                        v
                             +-----------------------+
                             | 9. Persist Dataset    |
                             |    /data/images/*.jpg |
                             |    /data/labels/*.txt |
                             +-----------------------+

## physical(ish) wiring diagram

    +---------------+
    |   INTEL NUC   |
    +-------+-------+
            |
            | USB (Serial + 5V)
            v
    +---------------+                      +---------------------------------------+
    |  SEEED XIAO   |                      |    5V RELAY MODULE (OPTO ISOLATED)    |
    |   ESP32-C6    |                      |                                       |
    |               |                      | [VCC]            [IN]           [GND] |
    |               |                      |   |               |               |   |
    |            5V +----------------------|---+               |               |   |
    |   (GPIO0)  D0 +----------------------|-------------------+               |   |
    |           GND +----------------------|-----------------------------------+   |
    +---------------+                      |                                       |
                                           | [COM]            [NO] (normally open) |
    +---------------+                      +---+---------------+-------------------+
    |    24V PSU    |                          |               |
    |          [V+] +--------------------------+               |
    |          [V-] +----------------------+                   |
    +---------------+                      |                   |
                                           |                   |
                                           v                   v
                                   +-------+-------------------+-----+
                                   |         C1  (2200uF >=50V)      |
                                   |       [-] to V-, [+] to NC      |
                                   +-------+-------------------------+
                                           |                   |
                                           v                   v
                                   +-------+-------------------+-----+
                                   |            D1 (1N4007)          |
                                   | anode to V-, cathode/band to NC |
                                   +-------+-------------------+-----+
                                           |                   |
                                           |                   |
                                           v                   v
                                   +-----------------------------------+
                                   |         24V LOCK SOLENOID         |
                                   |        NO - normally open         |
                                   +-----------------------------------+

## BoM

* [REOLINK PoE Security Camera RLC-810A]
* [PoE injector]
* [Seeed Studio XIAO ESP32-C6]
* [5V single channel relay (opto-coupler) H/L trigger jumper]
* [24VDC solenoid lock NO]
* 1N4007 diode
* 2200uF 50V electrolytic capacitor
* Good quality, democratically priced and sustainably sourced 24VDC power supply
* Intel NUC or compatible AMD64 compute


[REOLINK PoE Security Camera RLC-810A]: https://www.amazon.ca/dp/B08MQ61MKN
[PoE injector]: https://www.amazon.ca/dp/B07PR9CBGL
[5V single channel relay (opto-coupler) H/L trigger jumper]: https://www.aliexpress.com/item/1005004493713732.html
[24VDC solenoid lock NO]: https://www.aliexpress.com/item/1005006233548116.html
[Seeed Studio XIAO ESP32-C6]: https://www.aliexpress.com/item/1005008884996574.html
