"""Windows dialog handler for CST Studio Suite.

Detects, reads, and dismisses CST modal dialogs that block automation.
Uses Win32 API via ctypes — no external dependencies beyond the stdlib.

**Detection strategy (two-tier):**

1. **Process-based** — find CST main-window PIDs, then catch *any* popup or
   dialog window belonging to those processes (regardless of title).
2. **Title-pattern fallback** — match known CST dialog titles even if the
   process-based detection misses them.

This ensures that *all* CST dialogs are caught, including frequency-range
dialogs, property editors, and any unexpected popups.

Only functional on Windows; on other platforms the public functions
return empty results gracefully.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# Win32 setup (Windows only)
# ---------------------------------------------------------------------------

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    # Callback type for EnumWindows / EnumChildWindows
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # type: ignore[attr-defined]

    # Constants
    WM_CLOSE = 0x0010
    BM_CLICK = 0x00F5
    GW_OWNER = 4

    def _get_window_text(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def _get_class_name(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _get_window_pid(hwnd: int) -> int:
        """Get the process ID that owns *hwnd*."""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _get_child_texts(hwnd: int) -> list[str]:
        """Collect text from every child control of a dialog."""
        texts: list[str] = []

        @WNDENUMPROC
        def _cb(child_hwnd: int, _: int) -> bool:
            text = _get_window_text(child_hwnd)
            if text:
                texts.append(text)
            return True

        user32.EnumChildWindows(hwnd, _cb, 0)
        return texts

    def _click_button(hwnd: int, button_text: str = "OK") -> bool:
        """Find a button by label inside *hwnd* and click it.

        Searches child controls for a Button whose text matches
        *button_text* (case-insensitive, whitespace-trimmed, ignoring
        ``&`` accelerator prefixes).  Falls through a priority list:
        exact match → ``&``-stripped match → IDOK (dialog item 1).
        """
        found = [False]
        target = button_text.strip().lower()

        @WNDENUMPROC
        def _cb(child_hwnd: int, _: int) -> bool:
            cls = _get_class_name(child_hwnd)
            if "Button" not in cls:
                return True
            raw_text = _get_window_text(child_hwnd).strip()
            text = raw_text.lower()
            # Match with or without & accelerator prefix
            if text == target or text.lstrip("&") == target:
                user32.SendMessageW(child_hwnd, BM_CLICK, 0, 0)
                found[0] = True
                return False
            return True

        user32.EnumChildWindows(hwnd, _cb, 0)

        if not found[0] and target == "ok":
            # Fallback: try IDOK (standard dialog button ID = 1)
            ok_hwnd = user32.GetDlgItem(hwnd, 1)  # IDOK = 1
            if ok_hwnd:
                user32.SendMessageW(ok_hwnd, BM_CLICK, 0, 0)
                found[0] = True

        return found[0]

    def _try_dismiss(hwnd: int) -> str:
        """Try to dismiss a dialog window.  Returns the action taken."""
        # Try common accept buttons in priority order
        for label in ("OK", "Yes", "Continue", "Accept", "Close"):
            if _click_button(hwnd, label):
                return f"clicked_{label.lower()}"

        # Last resort: WM_CLOSE
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return "closed"


# ---------------------------------------------------------------------------
# CST main-window identification
# ---------------------------------------------------------------------------

# Substrings that identify a CST *main application* window title.
_CST_MAIN_WINDOW_KEYWORDS = [
    "cst studio suite",
    "cst design environment",
    "cst microwave studio -",   # Main window has " - project path"
    "cst em studio -",
]

# Known dialog title patterns (fallback when process detection fails).
_CST_DIALOG_PATTERNS = [
    "Results May Get Incompatible",
    "History Error",
    "Solver Error",
    "CST Error",
    "CST Warning",
    "Frequency Range",
    "Port Properties",
    "Mesh Properties",
    "Boundary Conditions",
    "Units",
]


def _is_cst_main_window(title: str) -> bool:
    """Return True if *title* looks like a CST main application window."""
    t = title.lower()
    return any(kw in t for kw in _CST_MAIN_WINDOW_KEYWORDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_cst_dialogs() -> list[dict[str, Any]]:
    """Return info about all visible CST dialog/popup windows.

    Uses process-based detection (finds CST PIDs from main windows, then
    catches *all* other visible windows from those processes) with a
    title-pattern fallback.
    """
    if not _IS_WINDOWS:
        return []

    # --- Pass 1: identify CST process IDs from main windows ---------------
    cst_pids: set[int] = set()
    main_hwnds: set[int] = set()

    @WNDENUMPROC
    def _find_main(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_text(hwnd)
        if _is_cst_main_window(title):
            cst_pids.add(_get_window_pid(hwnd))
            main_hwnds.add(hwnd)
        return True

    user32.EnumWindows(_find_main, 0)

    # --- Pass 2: find dialog windows --------------------------------------
    dialogs: list[dict[str, Any]] = []
    seen: set[int] = set()

    @WNDENUMPROC
    def _find_dialogs(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if hwnd in main_hwnds or hwnd in seen:
            return True

        title = _get_window_text(hwnd)
        if not title:
            return True

        pid = _get_window_pid(hwnd)
        matched_by: str | None = None

        # Strategy 1: any non-main window from a CST process
        if pid in cst_pids:
            matched_by = "cst_process"

        # Strategy 2: title pattern match (catches CST dialogs even if
        # the process-based detection didn't find the main window)
        if matched_by is None:
            title_lower = title.lower()
            for pat in _CST_DIALOG_PATTERNS:
                if pat.lower() in title_lower:
                    matched_by = "title_pattern"
                    break

        if matched_by is not None:
            child_texts = _get_child_texts(hwnd)
            dialogs.append({
                "hwnd": hwnd,
                "title": title,
                "class": _get_class_name(hwnd),
                "texts": child_texts,
                "full_text": "\n".join(child_texts),
                "match": matched_by,
            })
            seen.add(hwnd)

        return True

    user32.EnumWindows(_find_dialogs, 0)
    return dialogs


def dismiss_cst_dialogs() -> list[dict[str, Any]]:
    """Find and dismiss all CST dialogs.  Returns details of each."""
    dialogs = find_cst_dialogs()
    dismissed: list[dict[str, Any]] = []

    for dialog in dialogs:
        hwnd = dialog["hwnd"]
        dialog["action"] = _try_dismiss(hwnd)
        dismissed.append(dialog)

    # Strip non-serialisable fields
    for d in dismissed:
        d.pop("hwnd", None)

    return dismissed


class DialogWatcher:
    """Background thread that auto-dismisses CST dialogs.

    Start before long-running operations (solves, optimization loops)
    and stop afterwards.  All dismissed dialogs are logged and
    retrievable via :meth:`get_log`.
    """

    def __init__(self, poll_interval: float = 0.5) -> None:
        self._poll_interval = poll_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._log: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # -- lifecycle --

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Dialog watcher started (poll=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Dialog watcher stopped")

    @property
    def running(self) -> bool:
        return self._running

    # -- log access --

    def get_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._log)

    def clear_log(self) -> None:
        with self._lock:
            self._log.clear()

    # -- internal --

    def _loop(self) -> None:
        while self._running:
            try:
                dismissed = dismiss_cst_dialogs()
                if dismissed:
                    with self._lock:
                        for d in dismissed:
                            d["timestamp"] = time.time()
                            self._log.append(d)
                            logger.info("Auto-dismissed: %s", d.get("title"))
            except Exception as e:  # noqa: BLE001
                logger.debug("Dialog watcher error: %s", e)
            time.sleep(self._poll_interval)
