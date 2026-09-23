"""Shared publication figure style for figure/drawing tools.

matplotlib and numpy are optional (``pip install cst-studio-mcp[figures]``);
import them through :func:`require_matplotlib` so tools can return a clear
error instead of failing at import time.
"""

from __future__ import annotations

from typing import Any

# IEEE-style column widths in inches.
SINGLE_COLUMN_IN = 3.5
DOUBLE_COLUMN_IN = 7.16

RC_PARAMS: dict[str, Any] = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "axes.linewidth": 0.6,
    "lines.linewidth": 1.0,
    "grid.linewidth": 0.4,
    "grid.alpha": 0.5,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.top": True,
    "ytick.right": True,
    "savefig.dpi": 600,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
}

# Grayscale-safe line styles for multi-curve plots.
LINE_STYLES = ("-", "--", "-.", ":")
COLORS = ("#000000", "#1f4e9c", "#b22222", "#2e7d32", "#6a1b9a", "#ef6c00")

SUPPORTED_FORMATS = ("pdf", "svg", "png", "eps")


def require_matplotlib():
    """Return ``(matplotlib, pyplot, numpy)`` using the non-interactive Agg backend.

    Raises ImportError with an install hint when the optional extra is missing.
    """
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "Figure tools need matplotlib and numpy: pip install \"cst-studio-mcp[figures]\""
        ) from exc
    return matplotlib, plt, np


def apply_style(plt) -> None:
    plt.rcParams.update(RC_PARAMS)
