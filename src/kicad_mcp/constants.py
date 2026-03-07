"""Global constants for KiCad MCP server."""

# A* Algorithm Constants
MAX_ITERATIONS_DEFAULT = 500_000
"""Default maximum iterations before stopping search for a path."""

# Response Size Constants
MAX_RESPONSE_CHARS = 50_000
"""Maximum characters in a response before truncation (~12k tokens)."""

# Default Via Cost in A* Pathfinding
DEFAULT_VIA_COST = 5.0
"""Default cost penalty for layer changes (via insertions)."""

# Board Outline Stroke Width
BOARD_OUTLINE_STROKE_WIDTH = 0.05
"""Default stroke width for board outline lines in mm."""
