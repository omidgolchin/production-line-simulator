"""linesim: a discrete-period production-line simulator.

Built after the dice game in Goldratt and Cox's *The Goal*: a serial
line of stations, each with a random capacity per period, input buffers
between stations, an optional bottleneck, and push vs drum-buffer-rope
release. See PLAN.md for the design and the experiment pre-registration.
"""

from .simulate import LineConfig, StationSpec, simulate

__all__ = ["LineConfig", "StationSpec", "simulate"]
__version__ = "1.0.0"
