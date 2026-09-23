"""Input validation and VBA injection prevention."""

from __future__ import annotations

import enum
import re

# VBA constructs that could be used for injection attacks.
#
# IMPORTANT: this is a best-effort *denylist*, not a sandbox. CST's VBA
# (WinWrap Basic) is a full programming language and determined code can evade
# pattern matching (string building, Chr(), indirection, ...). The raw VBA
# tools are therefore additionally gated behind CST_ALLOW_RAW_VBA.
#
# Keyword patterns are matched against *masked* code: string-literal contents
# are blanked and comments dropped first (see ``_mask_code``), so a solid named
# "shell" or a comment mentioning Kill is not a false positive.

# Statement start: beginning of line, after ``:``, or after a single-line
# ``Then``/``Else``; optionally followed by a numeric line label.
_STMT_START = r"(?:^|:|\bThen\b|\bElse\b)[ \t]*(?:\d+[ \t]+)?"

_DANGEROUS_VBA_PATTERNS = [
    # Process / program execution
    r"\bShell\b",
    r"\bShellExecute\w*\b",
    r"\bWScript\b",
    r"\bPowerShell\b",
    r"\bSendKeys\b",
    r"\bAppActivate\b",
    r"\bRunAndWait\b",  # CST: starts an arbitrary program and waits for it
    r"\bAddClientCommandLine\b",  # CST co-simulation: arbitrary client command line
    r"\bDDE\w*\b",  # DDEInitiate / DDEExecute / DDEPoke ...
    # COM automation (FileSystemObject, WScript.Shell, other Office apps, ...)
    r"\bCreateObject\b",
    r"\bGetObject\b",
    r"\bNew\s+(?:Scripting|IWshRuntimeLibrary|Shell32|MSXML2|WinHttp|ADODB)\b",
    # .NET (WWB.NET) process / reflection / file access
    r"\bProcess\s*\.\s*Start\b",
    r"\bSystem\s*\.\s*(?:Diagnostics|IO|Reflection|Net)\b",
    # Native Win32 API access: any Declare statement (incl. PtrSafe) or Lib "..."
    r"\bDeclare\s+(?:PtrSafe\s+)?(?:Sub|Function)\b",
    r"\bPtrSafe\b",
    r"\bLib\s+\"",
    # Indirect / dynamic execution
    r"\bCallByName\b",
    r"\bApplication\s*\.\s*Run\b",
    r"\bRunScript\b",  # CST: reads and runs a script file
    r"\bRunMacro\b",  # CST: runs a named macro
    r"\bMacro(?:Run|Open)\w*\b",  # WinWrap: MacroRun / MacroRunThis / MacroOpen
    r"\bExecuteGlobal\b",
    # File system access. ``Open <path> As #n`` without a For clause is valid
    # (defaults to Random), so either keyword triggers; ``.Open`` members pass.
    r"(?<![.\w])Open\b.*?\b(?:For|As)\b",
    r"\bKill\b",
    r"\bFileCopy\b",
    r"\bMkDir\b",
    r"\bRmDir\b",
    # ``Name <old> As <new>`` (file rename) -- only at statement start, so that
    # ``.Name "x"``, ``Dim Name As String`` and ``Name As String`` type fields pass.
    _STMT_START + r"Name[ \t]+(?!As\b)\S.*?[ \t]+As\b",
    r"\bSetAttr\b",
    r"\bChDir\b",
    r"\bChDrive\b",
    r"\bEnviron\b",
]

# Matched against the raw (unmasked) text: WinWrap directives live inside
# comments (``'#Reference``, ``'#Language "WWB.NET"``, ``'#Uses``), and
# command-interpreter names are suspicious even inside string literals.
_RAW_DANGEROUS_VBA_PATTERNS = [
    r"(?:'|\bRem\b)\s*#\s*(?:Reference|Language|Uses)\b",
    r"\bcmd\.exe\b",
    r"\bcmd\s*/[ck]\b",
    r"\bPowerShell\b",
    r"\bWScript\b",
    r"\bmshta\b",
]

_DANGEROUS_VBA_RE = re.compile("|".join(_DANGEROUS_VBA_PATTERNS), re.IGNORECASE | re.MULTILINE)
_RAW_DANGEROUS_VBA_RE = re.compile("|".join(_RAW_DANGEROUS_VBA_PATTERNS), re.IGNORECASE | re.MULTILINE)

# VBA line continuation: whitespace, underscore, optional trailing blanks, newline.
_LINE_CONTINUATION_RE = re.compile(r"[ \t]+_[ \t]*\n")
_ENDS_WITH_CONTINUATION_RE = re.compile(r"[ \t]+_[ \t]*$")
_REM_RE = re.compile(r"Rem\b", re.IGNORECASE)
# Control characters other than tab / LF / CR have no place in VBA source.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize_newlines(code: str) -> str:
    """CRLF and lone CR both become LF (a lone CR is a line break for CST)."""
    return code.replace("\r\n", "\n").replace("\r", "\n")


def _mask_line(line: str, continued: bool, brackets: bool) -> str:
    """Blank string-literal contents and drop the comment of one physical line.

    Strings and comments cannot span physical lines in VBA, so masking happens
    per line *before* continuations are joined: a comment ending in `` _`` is
    dropped and the next line is still checked as code (stricter than VBA,
    never looser). ``""`` inside a string is an escaped quote. ``Rem`` counts as
    a comment only at a real statement start (not on a continued line). With
    ``brackets``, ``[...]`` is copied verbatim as an opaque foreign identifier.
    """
    out: list[str] = []
    i, n = 0, len(line)
    stmt_start = not continued
    while i < n:
        ch = line[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if line[j] == '"':
                    if j + 1 < n and line[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            closed = j < n
            out.append('"' + " " * (min(j, n) - i - 1) + ('"' if closed else ""))
            i = j + 1
            stmt_start = False
            continue
        if ch == "'":
            break  # comment runs to end of line
        if brackets and ch == "[":
            j = line.find("]", i + 1)
            j = n - 1 if j < 0 else j
            out.append(line[i : j + 1])
            i = j + 1
            stmt_start = False
            continue
        if stmt_start and _REM_RE.match(line, i) and (i == 0 or not (line[i - 1].isalnum() or line[i - 1] == "_")):
            break  # Rem comment
        if ch == ":":
            stmt_start = True
        elif not ch.isspace():
            stmt_start = False
        out.append(ch)
        i += 1
    return "".join(out)


def _mask_code(code: str, brackets: bool) -> str:
    """Mask every physical line of LF-normalised code, then join continuations."""
    masked: list[str] = []
    continued = False
    for line in code.split("\n"):
        m = _mask_line(line, continued, brackets)
        masked.append(m)
        continued = bool(_ENDS_WITH_CONTINUATION_RE.search(m))
    return _LINE_CONTINUATION_RE.sub(" ", "\n".join(masked))

RAW_VBA_ENV = "CST_ALLOW_RAW_VBA"


def raw_vba_enabled() -> bool:
    """Return True when executing raw user-supplied VBA is explicitly allowed.

    Read from ``os.environ`` at call time (not import time) so the gate can be
    toggled per process/test without re-importing.
    """
    import os

    return os.environ.get(RAW_VBA_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def raw_vba_disabled_message() -> str:
    """Error text returned when a raw VBA tool is called while the gate is off."""
    return (
        "Raw VBA execution is disabled by default. To enable it, set the environment "
        f"variable {RAW_VBA_ENV}=1 (or true) for the MCP server process and restart/"
        "retry. VBA validation is a best-effort denylist, not a sandbox: enabling this "
        "effectively grants the MCP client arbitrary code execution on this machine, "
        "so only enable it for fully trusted clients."
    )

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
    """Check VBA code for dangerous patterns (best-effort denylist, not a sandbox).

    Newlines are normalised first (CRLF and lone CR become LF). Directive and
    interpreter patterns are checked on the raw text; keyword patterns on a
    masked copy (string contents blanked, comments dropped, line continuations
    joined so a statement cannot be split to dodge a pattern). The masked check
    runs both with and without treating ``[...]`` as an opaque identifier, and
    either hit rejects, so tokenizer ambiguity cannot hide code.
    """
    if _CONTROL_CHARS_RE.search(vba_code):
        raise ValidationError("VBA code contains control characters (e.g. NUL), which are not allowed.")
    normalized = _normalize_newlines(vba_code)
    match = _RAW_DANGEROUS_VBA_RE.search(_LINE_CONTINUATION_RE.sub(" ", normalized))
    if not match:
        for brackets in (False, True):
            match = _DANGEROUS_VBA_RE.search(_mask_code(normalized, brackets))
            if match:
                break
    if match:
        raise ValidationError(
            f"VBA code contains potentially dangerous pattern: '{match.group().strip()}'. "
            "This best-effort denylist (not a sandbox) rejects program/shell launching, "
            "COM objects, file I/O, native API declarations, WinWrap directives and "
            "indirect execution."
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
