"""runemap — carve radar echoes into runes.

A text radar map for agents: turn 2D weather-radar fields into compact
character grids that language models can actually read.
"""
__version__ = "0.1.0"

from .render import ascii_radar, classify, RAMP   # noqa: F401
from .sparkline import sparkline                  # noqa: F401
