# onlyCat(s)
> Border Services Agency, preventing contraband entering the catflap.

    +---------------+
    |   INTEL NUC   |
    +-------+-------+
            |
            | USB (Serial + 5V)
            v
    +---------------+
    |  SEEED XIAO   |
    |   ESP32-C6    |
    |               |
    |           GND +----------------+
    |    (GPIO0) D0 +-----------+    |
    |            5V +-----+     |    |
    +---------------+     |     |    |
                          |     |    |
                          v     v    v
                    +--------------------+
                    | 5V RELAY MODULE    |
                    |                    |
                    |   [VCC] [IN] [GND] |
                    |                    |
                    |  [COM] [NO]        |
                    +----+--------+------+
                         |    |
                         |    |
    +------------+       |    |
    | 24V PSU    |       |    |
    |       [V+] +-------+    |
    |            |            |
    |       [V-] +---------+  |
    +------------+         |  |
                           |  |
                           |  |
                           v  v
                     +-----+--+----+
                     |      C1     |  (2200uf >=35V, [-] to V-, [+] to NO)
                     +-----+--+----+
                           |  |
                           v  v
                     +-----+--+----+
                     |      D1     |  (1N4007, anode to V-, cathode/band to NO)
                     +-----+--+----+
                           |  |
                           |  |
                           v  v
                     +-------------+
                     | 24V LOCK    |
                     | SOLENOID    |
                     +-------------+
