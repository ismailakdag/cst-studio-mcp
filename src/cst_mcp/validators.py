"""Input validation and VBA injection prevention."""

from __future__ import annotations

import enum
import re

# VBA commands that could be used for injection attacks
_DANGEROUS_VBA_PATTERNS = [
    r"\bShell\b",
    r"\bKill\b",
    r"\bFileCopy\b",
    r"\bCreateObject\b",
    r"\bGetObject\b",
    r"\bSendKeys\b",
    r"\bAppActivate\b",
    r"\bOpen\s+.*\s+For\s+(Input|Output|Append|Binary|Random)\b",
    r"\bMkDir\b",
    r"\bRmDir\b",
    r"\bName\s+.*\s+As\b",
    r"\bSetAttr\b",
    r"\bChDir\b",
    r"\bChDrive\b",
    r"\bEnviron\b",
    r"\bWScript\b",
    r"\bPowerShell\b",
    r"\bcmd\.exe\b",
    r"\bcmd\s*/c\b",
    r"\bDeclare\s+(Sub|Function)\b",
]

_DANGEROUS_VBA_RE = re.compile("|".join(_DANGEROUS_VBA_PATTERNS), re.IGNORECASE)

_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .-]{0,99}$")

_VALID_COMPONENT_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .-]{0,99}(:[A-Za-z_][A-Za-z0-9_ .-]{0,99})?$")


class ValidationError(Exception):
    """Raised when input validation fails."""


def validate_name(name: str, label: str = "name") -> str:
    """Validate a component/solid/material name."""
    if not name:
        raise ValidationError(f"{label} cannot be empty")
    if not _VALID_NAME_RE.match(name):
        raise ValidationError(
            f"Invalid {label} '{name}': must start with letter/underscore, "
            "contain only alphanumeric, underscore, space, dot, hyphen, max 100 chars"
        )
    return name


def validate_component_path(path: str) -> str:
    """Validate a component:solid path like 'Antenna:Patch'."""
    if not path:
        raise ValidationError("Component path cannot be empty")
    if not _VALID_COMPONENT_PATH_RE.match(path):
        raise ValidationError(
            f"Invalid component path '{path}': use 'Component:Solid' format "
            "with alphanumeric, underscore, space, dot, hyphen"
        )
    return path


def validate_vba_input(vba_code: str) -> str:
    """Check VBA code for dangerous patterns."""
    match = _DANGEROUS_VBA_RE.search(vba_code)
    if match:
        raise ValidationError(
            f"VBA code contains potentially dangerous pattern: '{match.group()}'. "
            "Shell access, file I/O, and external process execution are blocked."
        )
    return vba_code


def validate_file_path(path: str, work_dir: str | None = None) -> str:
    """Validate a file path — block traversal and enforce work_dir confinement."""
    import os

    if not path:
        raise ValidationError("File path cannot be empty")

    normalized = path.replace("\\", "/")

    if ".." in normalized:
        raise ValidationError("Path traversal ('..') is not allowed")

    if work_dir and os.path.isabs(path):
        abs_path = os.path.normpath(os.path.abspath(path))
        abs_work = os.path.normpath(os.path.abspath(work_dir))
        # Ensure the path is within (or equal to) the work directory
        if not abs_path.startswith(abs_work + os.sep) and abs_path != abs_work:
            raise ValidationError(f"Path must be within work directory: {work_dir}")

    return path


def validate_positive(value: float, label: str = "value") -> float:
    """Validate that a value is positive."""
    if value <= 0:
        raise ValidationError(f"{label} must be positive, got {value}")
    return value


def validate_non_negative(value: float, label: str = "value") -> float:
    """Validate that a value is non-negative."""
    if value < 0:
        raise ValidationError(f"{label} must be non-negative, got {value}")
    return value


def validate_range(value: float, low: float, high: float, label: str = "value") -> float:
    """Validate that a value is within range [low, high]."""
    if value < low or value > high:
        raise ValidationError(f"{label} must be between {low} and {high}, got {value}")
    return value


def validate_frequency(freq_ghz: float) -> float:
    """Validate a frequency value in GHz."""
    if freq_ghz <= 0:
        raise ValidationError(f"Frequency must be positive, got {freq_ghz} GHz")
    if freq_ghz > 1000:
        raise ValidationError(f"Frequency {freq_ghz} GHz exceeds 1 THz maximum")
    return freq_ghz


def validate_port_number(port: int) -> int:
    """Validate a port number."""
    if port < 1 or port > 999:
        raise ValidationError(f"Port number must be 1-999, got {port}")
    return port


def validate_enum_value(value: str, enum_class: type[enum.Enum], label: str = "value") -> str:
    """Validate that a string matches an enum value."""
    valid = [e.value for e in enum_class]
    if value not in valid:
        raise ValidationError(f"Invalid {label} '{value}'. Valid options: {valid}")
    return value
