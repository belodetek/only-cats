# onlyCat(s)
> Border Services Agency, preventing contraband entering the catflap.

	+---------------+
	|   INTEL NUC   |
	+-------+-------+
			|
			| USB (Serial + 5V)
			v
	+---------------+
	| SEEED XIAO    |
	|   ESP32-C3    |
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
		+24VDC           |    |
	+------------+       |    |
	| 24V PSU    |       |    |
	|       [V+] +-------+    |
	|            |            |
	|       [V-] +---------+  |
	+------------+         |  |
						   |  |
		   (0V / Return)   |  | (+24V Switched)
						   v  v
					 +-----+--+----+
					 |      C1     |  (Electrolytic >=35V, [-] to V-, [+] to NO)
					 +-----+--+----+
						   |  |
						   v  v
					 +-----+--+----+
					 |      D1     |  (1N4007, Anode to V-, Cathode/Band to NO)
					 +-----+--+----+
						   |  |
						   |  |
						   v  v
					 +-------------+
					 | 24V LOCK    |
					 | SOLENOID    |
					 +-------------+
