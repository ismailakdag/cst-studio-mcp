"""Matplotlib renderers for 1D publication figures.

Every renderer takes plain data (frequencies in GHz, complex samples) and
returns a matplotlib Figure; :func:`save_figure` writes it in the requested
formats. The shared IEEE style comes from :mod:`academic_style`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from cst_mcp.execution.academic_style import (
    COLORS,
    DOUBLE_COLUMN_IN,
    LINE_STYLES,
    SINGLE_COLUMN_IN,
    apply_style,
    require_matplotlib,
)
from cst_mcp.execution.figures_1d_metrics import DB_FLOOR, impedance, phase_deg, to_db, vswr

# A "series" is {"label": str, "f": [GHz], "values": [complex], "z0": float|list}.


def _plt():
    _, plt, np = require_matplotlib()
    apply_style(plt)
    return plt, np


def figure(width: str = "single", aspect: float = 0.75, square: bool = False):
    plt, _ = _plt()
    w = DOUBLE_COLUMN_IN if width == "double" else SINGLE_COLUMN_IN
    h = w if square else (w * aspect if width != "double" else 3.0)
    fig, ax = plt.subplots(figsize=(w, h))
    return fig, ax


def style_of(i: int) -> dict[str, Any]:
    return {"linestyle": LINE_STYLES[i % len(LINE_STYLES)], "color": COLORS[i % len(COLORS)]}


def _finish(ax, title: str | None, legend: bool = True) -> None:
    ax.grid(True, which="major")
    if title:
        ax.set_title(title)
    if legend:
        handles, labels = ax.get_legend_handles_labels()
        if len(handles) > 1 or (handles and labels[0] and not labels[0].startswith("_")):
            leg = ax.legend(loc="best", frameon=True, framealpha=0.9, edgecolor="0.6",
                            handlelength=2.4)
            leg.get_frame().set_linewidth(0.4)


def _xlim(ax, series: list[dict], overlays: list[dict] | None = None) -> None:
    fs = [x for s in series for x in s["f"]] + [x for o in overlays or [] for x in o["f_ghz"]]
    if fs and series:
        lo = min(min(s["f"]) for s in series)
        hi = max(max(s["f"]) for s in series)
        if hi > lo:
            ax.set_xlim(lo, hi)


def _db_ylim(ax, curves: list[list[float]], threshold_db: float | None) -> None:
    finite = [v for c in curves for v in c if math.isfinite(v) and v > DB_FLOOR]
    if not finite:
        return
    lo = min(finite)
    if threshold_db is not None:
        lo = min(lo, threshold_db)
    lo = max(5 * math.floor((lo - 2) / 5), -80)
    hi = max(0.0, 5 * math.ceil(max(finite) / 5))
    ax.set_ylim(lo, hi if hi > lo else lo + 5)


def plot_s11_db(
    series: list[dict],
    *,
    overlays: list[dict] | None = None,
    metrics: dict | None = None,
    threshold_db: float | None = -10.0,
    mark_resonance: bool = True,
    width: str = "single",
    title: str | None = None,
    ylabel: str = r"$|S_{11}|$ (dB)",
):
    fig, ax = figure(width)
    curves = []
    for i, s in enumerate(series):
        db = to_db(s["values"])
        curves.append(db)
        y = [v if v > DB_FLOOR else math.nan for v in db]
        ax.plot(s["f"], y, label=s["label"], **style_of(i))
    for k, o in enumerate(overlays or []):
        n = len(o["f_ghz"])
        ax.plot(
            o["f_ghz"], o["db"], label=o.get("label", "Measured"), color="0.45",
            linestyle="-", linewidth=0.8, marker="o", markersize=2.2, markerfacecolor="none",
            markevery=max(1, n // 25), zorder=2 + k,
        )
        curves.append(o["db"])
    if threshold_db is not None:
        ax.axhline(threshold_db, color="0.35", linestyle=(0, (4, 2)), linewidth=0.6, zorder=1)
        ax.text(
            0.01, threshold_db, f" {threshold_db:g} dB", transform=ax.get_yaxis_transform(),
            va="bottom", ha="left", fontsize=6, color="0.3",
        )
    _xlim(ax, series, overlays)
    _db_ylim(ax, curves, threshold_db)
    if metrics:
        _annotate_bands(ax, metrics)
        if mark_resonance:
            _annotate_resonance(ax, metrics)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel(ylabel)
    _finish(ax, title)
    return fig


def _annotate_bands(ax, metrics: dict) -> None:
    """Shade each band; label it just below the threshold, outside the band edge."""
    thr = metrics.get("threshold_db", -10.0)
    lo, hi = ax.get_xlim()
    for k, band in enumerate(metrics.get("bands", [])):
        ax.axvspan(band["f_low"], band["f_high"], color="0.88", zorder=0, linewidth=0)
        trunc = band.get("lower_truncated") or band.get("upper_truncated")
        text = f"BW = {band['bw_mhz']:.1f} MHz\n({band['fbw_pct']:.2f}%){'*' if trunc else ''}"
        left = hi > lo and (band["f_high"] - lo) / (hi - lo) > 0.8
        ax.annotate(
            text, xy=(band["f_low"] if left else band["f_high"], thr),
            xytext=(-3 if left else 3, -3 - 15 * k), textcoords="offset points",
            ha="right" if left else "left", va="top", fontsize=5.5, color="0.15", zorder=6,
        )


def _annotate_resonance(ax, metrics: dict) -> None:
    f0, y0 = metrics.get("f_res_ghz"), metrics.get("s11_min_db")
    if f0 is None or y0 is None or not math.isfinite(y0) or y0 <= DB_FLOOR:
        return
    lo, hi = ax.get_xlim()
    right = (f0 - lo) / (hi - lo) > 0.62 if hi > lo else False
    ybot, ytop = ax.get_ylim()
    y_plot = max(y0, ybot)
    ax.plot([f0], [y_plot], marker="v", color="black", markersize=3.5, zorder=5, linestyle="none")
    ax.annotate(
        f"$f_0$ = {f0:.3f} GHz\n{y0:.1f} dB",
        xy=(f0, y_plot),
        xytext=(-10 if right else 10, 6),
        textcoords="offset points",
        ha="right" if right else "left",
        va="bottom",
        fontsize=6,
        arrowprops={"arrowstyle": "-", "color": "0.3", "linewidth": 0.5},
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "0.6", "linewidth": 0.4},
        zorder=6,
    )


def plot_db_family(series: list[dict], *, width="single", title=None, ylabel="Magnitude (dB)",
                   threshold_db: float | None = None):
    fig, ax = figure(width)
    curves = []
    for i, s in enumerate(series):
        db = to_db(s["values"])
        curves.append(db)
        ax.plot(s["f"], [v if v > DB_FLOOR else math.nan for v in db], label=s["label"], **style_of(i))
    if threshold_db is not None:
        ax.axhline(threshold_db, color="0.35", linestyle=(0, (4, 2)), linewidth=0.6)
    _xlim(ax, series)
    _db_ylim(ax, curves, threshold_db)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel(ylabel)
    _finish(ax, title)
    return fig


def plot_vswr(series: list[dict], *, threshold_db: float | None = -10.0, width="single", title=None,
              vmax: float = 10.0):
    fig, ax = figure(width)
    for i, s in enumerate(series):
        v = [x if math.isfinite(x) and x <= vmax * 10 else math.nan for x in vswr(s["values"])]
        ax.plot(s["f"], v, label=s["label"], **style_of(i))
    if threshold_db is not None and threshold_db < 0:
        g = 10 ** (threshold_db / 20)
        limit = (1 + g) / (1 - g)
        ax.axhline(limit, color="0.35", linestyle=(0, (4, 2)), linewidth=0.6)
        ax.text(0.01, limit, f" VSWR = {limit:.2f}", transform=ax.get_yaxis_transform(),
                va="bottom", ha="left", fontsize=6, color="0.3")
    _xlim(ax, series)
    ax.set_ylim(1, vmax)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("VSWR")
    _finish(ax, title)
    return fig


def plot_phase(series: list[dict], *, width="single", title=None, unwrap=False,
               ylabel=r"$\angle S_{11}$ (deg)"):
    fig, ax = figure(width)
    for i, s in enumerate(series):
        ax.plot(s["f"], phase_deg(s["values"], unwrap), label=s["label"], **style_of(i))
    _xlim(ax, series)
    if not unwrap:
        ax.set_ylim(-180, 180)
        ax.set_yticks(range(-180, 181, 90))
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel(ylabel)
    _finish(ax, title)
    return fig


def plot_impedance(series: list[dict], *, width="single", title=None, metrics: dict | None = None,
                   mark_resonance: bool = True):
    fig, ax = figure(width)
    multi = len(series) > 1
    for i, s in enumerate(series):
        z = impedance(s["values"], s.get("z0", 50.0))
        color = COLORS[i % len(COLORS)]
        suffix = f" ({s['label']})" if multi else ""
        ax.plot(s["f"], [v.real for v in z], color=color, linestyle="-",
                label=r"Re$\{Z_\mathrm{in}\}$" + suffix)
        ax.plot(s["f"], [v.imag for v in z], color=color, linestyle="--",
                label=r"Im$\{Z_\mathrm{in}\}$" + suffix)
    ax.axhline(0, color="0.3", linewidth=0.5)
    z0 = series[0].get("z0", 50.0) if series else 50.0
    z0_ref = float(z0 if isinstance(z0, (int, float)) else complex(z0[len(z0) // 2]).real)
    ax.axhline(z0_ref, color="0.45", linestyle=":", linewidth=0.6)
    ax.text(0.01, z0_ref, rf" $Z_0$ = {z0_ref:.1f} $\Omega$", transform=ax.get_yaxis_transform(),
            va="bottom", ha="left", fontsize=6, color="0.3")
    if metrics and mark_resonance and metrics.get("f_res_ghz") is not None:
        ax.axvline(metrics["f_res_ghz"], color="0.5", linestyle="-.", linewidth=0.5)
    _xlim(ax, series)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel(r"Impedance ($\Omega$)")
    _finish(ax, title)
    return fig


def plot_efficiency(series: list[dict], *, width="single", title=None):
    """Efficiency curves in percent; single-frequency monitors become markers."""
    fig, ax = figure(width)
    markers = ("o", "s", "^", "D", "v", "P")
    for i, s in enumerate(series):
        y = [100 * complex(v).real for v in s["values"]]
        st = style_of(i)
        if len(y) == 1:
            ax.plot(s["f"], y, linestyle="none", marker=markers[i % len(markers)], color=st["color"],
                    markersize=4, markerfacecolor="none", label=f"{s['label']} ({y[0]:.1f}%)")
        else:
            ax.plot(s["f"], y, label=s["label"], **st)
    fs = [x for s in series for x in s["f"]]
    if fs and max(fs) > min(fs):
        ax.set_xlim(min(fs), max(fs))
    elif fs:
        ax.set_xlim(fs[0] * 0.9, fs[0] * 1.1)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Efficiency (%)")
    _finish(ax, title)
    return fig


def plot_real(series: list[dict], *, width="single", title=None, ylabel="Value"):
    fig, ax = figure(width)
    for i, s in enumerate(series):
        ax.plot(s["f"], [complex(v).real for v in s["values"]], label=s["label"], **style_of(i))
    _xlim(ax, series)
    ax.set_xlabel(series[0].get("xlabel", "Frequency (GHz)") if series else "Frequency (GHz)")
    ax.set_ylabel(ylabel)
    _finish(ax, title)
    return fig


# --------------------------------------------------------------------- Smith

SMITH_R = (0.0, 0.2, 0.5, 1.0, 2.0, 5.0)
SMITH_X = (0.2, 0.5, 1.0, 2.0, 5.0)


def draw_smith_grid(ax) -> None:
    """Impedance Smith chart grid drawn with plain circles (no extra deps)."""
    from matplotlib.patches import Circle

    plt, np = _plt()
    grid = {"fill": False, "edgecolor": "0.72", "linewidth": 0.4}
    rim = Circle((0, 0), 1.0, fill=False, edgecolor="black", linewidth=0.7, zorder=3)
    ax.add_patch(rim)
    clip = Circle((0, 0), 1.0, transform=ax.transData)
    for r in SMITH_R[1:]:
        ax.add_patch(Circle((r / (1 + r), 0), 1 / (1 + r), **grid))
        ax.text(r / (1 + r) - 1 / (1 + r), 0.015, f"{r:g}", fontsize=5, color="0.35",
                ha="right", va="bottom", rotation=90)
    for x in SMITH_X:
        for sign in (1, -1):
            arc = Circle((1, sign / x), 1 / x, **grid)
            ax.add_patch(arc)
            arc.set_clip_path(clip)
            # Label where the x-circle meets the rim: Gamma = (jx-1)/(jx+1)
            g = complex(sign * 1j * x - 1) / complex(sign * 1j * x + 1)
            ax.text(g.real * 1.07, g.imag * 1.07, f"{'+' if sign > 0 else '-'}j{x:g}", fontsize=5,
                    color="0.35", ha="center", va="center")
    ax.plot([-1, 1], [0, 0], color="0.72", linewidth=0.4)
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.axis("off")


def plot_smith(series: list[dict], *, width="single", title=None, metrics: dict | None = None,
               mark_resonance: bool = True):
    fig, ax = figure(width, square=True)
    draw_smith_grid(ax)
    for i, s in enumerate(series):
        g = s["values"]
        ax.plot([v.real for v in g], [v.imag for v in g], label=s["label"], zorder=4, **style_of(i))
    # Frequency markers and f0 on the primary (last) run, which the metrics describe.
    if series and series[-1]["values"]:
        s = series[-1]
        g = s["values"]
        ax.plot([g[0].real], [g[0].imag], marker="o", color="black", markersize=2.5, zorder=5)
        ax.plot([g[-1].real], [g[-1].imag], marker="s", color="black", markersize=2.5, zorder=5)
        ax.annotate(f"{s['f'][0]:.2f} GHz", (g[0].real, g[0].imag), xytext=(3, 3),
                    textcoords="offset points", fontsize=5.5)
        ax.annotate(f"{s['f'][-1]:.2f} GHz", (g[-1].real, g[-1].imag), xytext=(3, -7),
                    textcoords="offset points", fontsize=5.5)
        if metrics and mark_resonance and metrics.get("f_res_ghz") is not None:
            f = s["f"]
            j = min(range(len(f)), key=lambda k: abs(f[k] - metrics["f_res_ghz"]))
            ax.plot([g[j].real], [g[j].imag], marker="v", color="black", markersize=3.5, zorder=6)
            ax.annotate(f"$f_0$ = {f[j]:.3f} GHz", (g[j].real, g[j].imag), xytext=(5, -9),
                        textcoords="offset points", fontsize=5.5,
                        bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none",
                              "alpha": 0.85})
    if title:
        ax.set_title(title)
    if len(series) > 1 or (series and series[0]["label"]):
        leg = ax.legend(loc="lower left", bbox_to_anchor=(-0.02, -0.04), frameon=True,
                        framealpha=0.9, edgecolor="0.6", fontsize=6)
        leg.get_frame().set_linewidth(0.4)
    return fig


def save_figure(fig, out_dir: Path, stem: str, formats: list[str]) -> list[str]:
    plt, _ = _plt()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        for fmt in formats:
            path = out_dir / f"{stem}.{fmt}"
            kwargs = {"dpi": 600} if fmt == "png" else {}
            fig.savefig(path, format=fmt, **kwargs)
            paths.append(str(path))
    finally:
        plt.close(fig)
    return paths
