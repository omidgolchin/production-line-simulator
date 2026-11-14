A production line has stations in series. Work flows station 1 -> station 2 -> ... -> station N, and leaves the line after the last station.

__CONFIG__

Rules of the line (discrete periods):
- Each period, every station draws a fresh capacity from its own distribution.
- Stations act in order, station 1 first. A station moves at most (its capacity) units, and only units already waiting in its input buffer. Moved units land in the next station's input buffer, so a unit can pass several stations within one period.
- Station 1 has unlimited raw material in front of it. The buffers between stations are unlimited.
- The bottleneck is the station that limits the whole line's output. If every station has the same average capacity, there is no bottleneck.

Answer with exactly two lines and nothing after them:
BOTTLENECK: <station number, or none>
THROUGHPUT: <average units finished per period, a number>
