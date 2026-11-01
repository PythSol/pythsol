"""Pytest helpers for programs built by PythSol.

Importing this package does not import the compiler. The plugin does, when a
test asks for the ``program`` fixture.
"""

from __future__ import annotations

__all__ = ["DEFAULT_PROGRAM_ID"]

#: Program id the LiteSVM fixture loads, unless ``PYTHSOL_PROGRAM_ID`` is set.
DEFAULT_PROGRAM_ID = "F1x3Lz3Nn3jvrUWM65uwGFPzFGuCB5GMUksMiNGxiKgU"
