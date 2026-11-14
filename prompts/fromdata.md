Below is a log of 50 periods from a production line with __N__ stations in series. Work flows station 1 -> station 2 -> ... -> station __N__, and leaves the line after the last station. Station 1 has unlimited raw material in front of it. Each period, stations act in order and each station moves units from its input buffer to the next station's buffer; a station can never move more than its capacity for that period, or more than is waiting in its buffer.

Columns: period; out_i = units station i moved in that period; wip_before_i = units waiting in station i's input buffer at the end of the period.

__LOG__

Which station is the bottleneck - the station that limits the whole line's output? If no station limits the others, answer "none".

Answer with exactly one line:
BOTTLENECK: <station number, or none>
