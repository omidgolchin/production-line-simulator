A production line has stations in series. Work flows station 1 -> station 2 -> ... -> station N, and leaves the line after the last station.

__CONFIG__

Rules of the line (discrete periods):
- Each period, every station draws a fresh capacity from its own distribution.
- Stations act in order, station 1 first. A station moves at most (its capacity) units, and only units already waiting in its input buffer. Moved units land in the next station's input buffer, so a unit can pass several stations within one period.
- Station 1 has unlimited raw material in front of it. The buffers between stations are unlimited.
- The bottleneck is the station that limits the whole line's output. If every station has the same average capacity, there is no bottleneck.

Write a Python program that simulates this line under these rules, for at least 20,000 periods after a warm-up of at least 1,000 periods, over at least 20 replications with different random seeds. Use only the standard library (numpy is also available). The program must print exactly two lines:

BOTTLENECK: <station number, or none>
THROUGHPUT: <average units finished per period, a number>

Put the whole program in a single ```python code block and nothing else after it.
