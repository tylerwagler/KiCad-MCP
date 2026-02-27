"""Input validation utilities for tool parameters.

Provides validation for common parameter types used in KiCAD operations:
- Coordinates (floats)
- Dimensions (positive floats)
- Angles (floats in degrees)
- Reference designators (strings like R1, C2, U10)
- Net names (valid KiCad net identifiers)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    valid: bool
    value: Any = None
    error: str | None = None

    @classmethod
    def success(cls, value: Any = None) -> ValidationResult:
        return cls(valid=True, value=value)

    @classmethod
    def failure(cls, error: str) -> ValidationResult:
        return cls(valid=False, error=error)


def validate_coordinate(value: float, name: str = "coordinate") -> ValidationResult:
    """Validate a coordinate value.

    Args:
        value: The coordinate value to validate.
        name: The parameter name for error messages.

    Returns:
        ValidationResult with the validated value or error.
    """
    try:
        coord = float(value)
    except (TypeError, ValueError):
        return ValidationResult.failure(f"{name} must be a number, got {type(value).__name__}")

    # Reasonable board bounds (KiCad boards are typically within +/- 500mm)
    # But allow larger for flexibility
    if abs(coord) > 10000:
        return ValidationResult.failure(
            f"{name} value {coord} is outside reasonable bounds (-10000 to 10000)"
        )

    return ValidationResult.success(coord)


def validate_coordinate_pair(
    x: float, y: float, names: tuple[str, str] = ("x", "y")
) -> ValidationResult:
    """Validate a coordinate pair.

    Args:
        x: X coordinate.
        y: Y coordinate.
        names: Tuple of parameter names for error messages.

    Returns:
        ValidationResult with tuple of validated coordinates or error.
    """
    result_x = validate_coordinate(x, names[0])
    if not result_x.valid:
        return result_x

    result_y = validate_coordinate(y, names[1])
    if not result_y.valid:
        return result_y

    return ValidationResult.success((result_x.value, result_y.value))


def validate_dimension(
    value: float, name: str = "dimension", min_value: float = 0.0, max_value: float = 1000.0
) -> ValidationResult:
    """Validate a dimension value (must be positive).

    Args:
        value: The dimension value to validate.
        name: The parameter name for error messages.
        min_value: Minimum allowed value.
        max_value: Maximum allowed value.

    Returns:
        ValidationResult with the validated value or error.
    """
    try:
        dim = float(value)
    except (TypeError, ValueError):
        return ValidationResult.failure(f"{name} must be a number, got {type(value).__name__}")

    if dim < min_value:
        return ValidationResult.failure(f"{name} must be >= {min_value}, got {dim}")

    if dim > max_value:
        return ValidationResult.failure(f"{name} must be <= {max_value}, got {dim}")

    return ValidationResult.success(dim)


def validate_angle(value: float, name: str = "angle") -> ValidationResult:
    """Validate an angle value (degrees).

    Angles can be any float value (KiCad allows any rotation).

    Args:
        value: The angle in degrees.
        name: The parameter name for error messages.

    Returns:
        ValidationResult with the validated value or error.
    """
    try:
        angle = float(value)
    except (TypeError, ValueError):
        return ValidationResult.failure(f"{name} must be a number, got {type(value).__name__}")

    # Normalize angle to 0-360 for display, but allow any value
    return ValidationResult.success(angle)


def validate_reference(value: str) -> ValidationResult:
    """Validate a component reference designator.

    Valid format: letter(s) followed by number(s) (e.g., R1, C10, U123, D5)

    Args:
        value: The reference designator to validate.

    Returns:
        ValidationResult with the validated reference or error.
    """
    if not isinstance(value, str):
        return ValidationResult.failure(f"Reference must be a string, got {type(value).__name__}")

    if not value:
        return ValidationResult.failure("Reference cannot be empty")

    # KiCad references are typically letters followed by numbers
    # Also allow some special cases like GND, VCC for power nets
    pattern = r"^[A-Za-z]+[0-9]+$"
    if not re.match(pattern, value):
        return ValidationResult.failure(
            "Reference "
            f"'{value}' is not a valid designator format (expected: letters followed by numbers)"
        )

    return ValidationResult.success(value)


def validate_net_name(value: str) -> ValidationResult:
    """Validate a net name.

    Args:
        value: The net name to validate.

    Returns:
        ValidationResult with the validated name or error.
    """
    if not isinstance(value, str):
        return ValidationResult.failure(f"Net name must be a string, got {type(value).__name__}")

    if not value:
        return ValidationResult.failure("Net name cannot be empty")

    # KiCad net names can contain letters, numbers, underscores, dashes, slashes
    # But should not contain spaces or special characters
    pattern = r"^[A-Za-z0-9_\-/]+$"
    if not re.match(pattern, value):
        return ValidationResult.failure(
            f"Net name '{value}' contains invalid characters. "
            "Only letters, numbers, underscores, dashes, and slashes are allowed."
        )

    # Length limit (KiCad has limits on net name length)
    if len(value) > 255:
        return ValidationResult.failure(f"Net name too long (max 255 characters, got {len(value)})")

    return ValidationResult.success(value)


def validate_layer_name(value: str) -> ValidationResult:
    """Validate a layer name.

    Args:
        value: The layer name to validate.

    Returns:
        ValidationResult with the validated name or error.
    """
    if not isinstance(value, str):
        return ValidationResult.failure(f"Layer name must be a string, got {type(value).__name__}")

    if not value:
        return ValidationResult.failure("Layer name cannot be empty")

    # KiCad standard layers
    standard_layers = {
        "F.Cu",
        "B.Cu",
        "F.Paste",
        "B.Paste",
        "F.SilkS",
        "B.SilkS",
        "F.CrtYd",
        "B.CrtYd",
        "F.Fab",
        "B.Fab",
        "F.Mask",
        "B.Mask",
        "Dwgs.User",
        "Cmts.User",
        "Eco1.User",
        "Eco2.User",
        "Edge.Cuts",
        "F.Adhes",
        "B.Adhes",
        "PASTE",
        "SOLDERMASK",
        "SILKSCREEN",
        "F.Copper",
        "B.Copper",
        "In1.Cu",
        "In2.Cu",
        "In3.Cu",
        "In4.Cu",
    }

    if value in standard_layers:
        return ValidationResult.success(value)

    # Allow user-defined layers (User.* pattern)
    if value.startswith("User.") or value.startswith("Dwgs.User") or value.startswith("Cmts.User"):
        return ValidationResult.success(value)

    return ValidationResult.failure(
        f"Layer '{value}' is not a recognized KiCad layer. "
        f"Standard layers include: {', '.join(sorted(standard_layers)[:10])}..."
    )


def validate_directory_path(value: str) -> ValidationResult:
    """Validate a directory path (for output directories).

    Args:
        value: The path to validate.

    Returns:
        ValidationResult with the validated path or error.
    """
    if not isinstance(value, str):
        return ValidationResult.failure(f"Path must be a string, got {type(value).__name__}")

    if not value:
        return ValidationResult.failure("Path cannot be empty")

    # Reject null bytes and path traversal in the raw string
    if "\x00" in value:
        return ValidationResult.failure("Path contains null bytes")

    if ".." in value:
        return ValidationResult.failure("Path traversal detected")

    # For output paths, allow relative paths
    # Absolute paths starting with ~ are allowed (home directory)
    if value.startswith("/") and not value.startswith("~/"):
        return ValidationResult.failure("Absolute paths not allowed for output directories")

    return ValidationResult.success(value)


def validate_filename(value: str, allowed_extensions: list[str] | None = None) -> ValidationResult:
    """Validate a filename.

    Args:
        value: The filename to validate.
        allowed_extensions: List of allowed extensions (including dot).

    Returns:
        ValidationResult with the validated filename or error.
    """
    if not isinstance(value, str):
        return ValidationResult.failure(f"Filename must be a string, got {type(value).__name__}")

    if not value:
        return ValidationResult.failure("Filename cannot be empty")

    # Reject dangerous filenames
    if value in (".", ".."):
        return ValidationResult.failure("Invalid filename")

    if "\x00" in value:
        return ValidationResult.failure("Filename contains null bytes")

    if ".." in value:
        return ValidationResult.failure("Path traversal detected in filename")

    # Check extension if specified
    if allowed_extensions:
        has_allowed_ext = any(value.lower().endswith(ext.lower()) for ext in allowed_extensions)
        if not has_allowed_ext:
            return ValidationResult.failure(
                f"Filename extension not allowed. Expected one of: {', '.join(allowed_extensions)}"
            )

    return ValidationResult.success(value)


def validate_component_properties(
    properties: dict[str, str], allowed_keys: list[str] | None = None
) -> ValidationResult:
    """Validate component properties dictionary.

    Args:
        properties: The properties dictionary to validate.
        allowed_keys: List of allowed property keys (if None, all keys allowed).

    Returns:
        ValidationResult with validated properties or error.
    """
    if not isinstance(properties, dict):
        return ValidationResult.failure(
            f"Properties must be a dictionary, got {type(properties).__name__}"
        )

    for key, value in properties.items():
        if not isinstance(key, str):
            return ValidationResult.failure(
                f"Property key must be a string, got {type(key).__name__}"
            )

        if not isinstance(value, str):
            return ValidationResult.failure(
                f"Property value for '{key}' must be a string, got {type(value).__name__}"
            )

        if not key:
            return ValidationResult.failure("Property key cannot be empty")

        if not value:
            return ValidationResult.failure(f"Property value for '{key}' cannot be empty")

        if len(key) > 255:
            return ValidationResult.failure(f"Property key too long: {key}")

        if len(value) > 1024:
            return ValidationResult.failure(f"Property value for '{key}' too long")

    return ValidationResult.success(properties)
