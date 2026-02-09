"""Typed data models for KiCad file formats."""

from .board import BoardSummary, Footprint, Layer, Net, Pad, Segment
from .common import BoundingBox, Position, Size
from .extract import (
    extract_board_outline,
    extract_board_summary,
    extract_footprints,
    extract_layers,
    extract_nets,
    extract_segments,
)

__all__ = [
    "BoardSummary",
    "BoundingBox",
    "Footprint",
    "Layer",
    "Net",
    "Pad",
    "Position",
    "Segment",
    "Size",
    "extract_board_outline",
    "extract_board_summary",
    "extract_footprints",
    "extract_layers",
    "extract_nets",
    "extract_segments",
]
