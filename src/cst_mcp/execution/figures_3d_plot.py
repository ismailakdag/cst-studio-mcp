"""Publication figures for farfield patterns (polar/rect cuts, heatmap, 3D)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from cst_mcp.execution import academic_style as st
from cst_mcp.execution.figures_3d_data import (
    Cut,
    FarfieldGrid,
    beam_metrics,
    cut_co_cross,
    plane_label,
)

_COMP_LABEL = {
    "theta": r"$E_\theta$",
    "phi": r"$E_\phi$",
    "horizontal": "Hor. (L3)",
    "vertical": "Ver. (L3)",
    "copolar": "Co-pol",
    "crosspolar": "Cross-pol",
    "left": "LHCP",
    "right": "RHCP",
}


def figure_width(width: Any) -> float:
    if width is None or width == "single":
        return st.SINGLE_COLUMN_IN
    if width == "double":
        return st.DOUBLE_COLUMN_IN
    w = float(width)
    if not 1.0 <= w <= 20.0:
        raise ValueError("width must be 'single', 'double' or inches in [1, 20]")
    return w


def _save(fig, plt, out_dir: Path, stem: str, formats: list[str]) -> list[str]:
    files = []
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        fig.savefig(path, format=fmt)
        files.append(str(path))
    plt.close(fig)
    return files


def _floor(vmax: float, dr: float) -> float:
    return vmax - dr


def _cut_curves(grid: FarfieldGrid, cut: Cut) -> list[tuple[str, np.ndarray]]:
    curves = [(f"{grid.label}", cut.total)]
    co, cx = cut_co_cross(grid, cut)
    if co and cx:
        curves = [(f"Co-pol ({_COMP_LABEL.get(co, co)})", cut.components[co]),
                  (f"Cross-pol ({_COMP_LABEL.get(cx, cx)})", cut.components[cx])]
        # keep total when it differs from the co-pol (e.g. CP antennas)
        if np.nanmax(np.abs(cut.total - cut.components[co])) > 0.5:
            curves.insert(0, (grid.label, cut.total))
    return curves


def _cut_title(grid: FarfieldGrid, cut: Cut) -> str:
    plane = plane_label(grid, cut)
    return f"{cut.label} ({plane})" if plane else cut.label


def plot_polar(grid: FarfieldGrid, cuts: list[Cut], out_dir: Path, stem: str, *, dynamic_range_db: float,
               width: float, formats: list[str]) -> list[str]:
    _, plt, _ = st.require_matplotlib()
    st.apply_style(plt)
    n = len(cuts)
    ncols = min(n, 2)
    nrows = math.ceil(n / ncols)
    vmax = float(np.nanmax(grid.total_db))
    top = math.ceil(vmax / 5.0) * 5.0 if vmax > 0 else math.ceil(vmax)
    bottom = top - dynamic_range_db
    panel = width / ncols
    fig, axes = plt.subplots(nrows, ncols, subplot_kw={"projection": "polar"},
                             figsize=(width, panel * nrows * 1.08), squeeze=False)
    for idx, cut in enumerate(cuts):
        ax = axes[idx // ncols][idx % ncols]
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ang = np.deg2rad(cut.angle)
        if cut.kind == "phi" and cut.angle.min() >= 0:
            ang = np.deg2rad(cut.angle)
        closed = cut.kind == "theta" or cut.angle.min() < -90
        for k, (label, vals) in enumerate(_cut_curves(grid, cut)):
            r = np.clip(np.where(np.isfinite(vals), vals, bottom), bottom, None)
            a = ang
            if closed:
                a = np.append(a, a[0] + 2 * np.pi)
                r = np.append(r, r[0])
            ax.plot(a, r, linestyle=st.LINE_STYLES[k % len(st.LINE_STYLES)],
                    color=st.COLORS[k % len(st.COLORS)], label=label)
        ax.set_ylim(bottom, top)
        step = 10 if dynamic_range_db >= 20 else 5
        ticks = np.arange(top, bottom - 1e-9, -step)[::-1]
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"{t:g}" for t in ticks], fontsize=6)
        ax.set_rlabel_position(100)
        ax.set_thetagrids(np.arange(0, 360, 30), fontsize=6)
        bm = beam_metrics(cut)
        if bm["hpbw_edges_deg"]:
            for edge in bm["hpbw_edges_deg"]:
                ax.plot([np.deg2rad(edge)] * 2, [bottom, bm["peak"] - 3.0], color="0.35",
                        linestyle=":", linewidth=0.7)
            ax.text(0.5, -0.12, f"HPBW = {bm['hpbw_deg']:.1f}°", transform=ax.transAxes,
                    ha="center", va="top", fontsize=7)
        ax.set_title(_cut_title(grid, cut), pad=10)
        if idx == 0:
            ax.legend(loc="upper left", bbox_to_anchor=(-0.18, 1.18), frameon=False, fontsize=6)
    for idx in range(n, nrows * ncols):
        axes[idx // ncols][idx % ncols].set_visible(False)
    fig.text(0.99, 0.01, f"{grid.label} / {grid.unit}", ha="right", va="bottom", fontsize=6)
    fig.tight_layout()
    return _save(fig, plt, out_dir, f"{stem}_polar", formats)


def plot_rect(grid: FarfieldGrid, cuts: list[Cut], out_dir: Path, stem: str, *, dynamic_range_db: float,
              width: float, formats: list[str]) -> list[str]:
    _, plt, _ = st.require_matplotlib()
    st.apply_style(plt)
    fig, ax = plt.subplots(figsize=(width, width * 0.62))
    vmax = float(np.nanmax(grid.total_db))
    bottom = vmax - dynamic_range_db
    k = 0
    for cut in cuts:
        for label, vals in _cut_curves(grid, cut):
            ax.plot(cut.angle, np.clip(vals, bottom, None), linestyle=st.LINE_STYLES[k % len(st.LINE_STYLES)],
                    color=st.COLORS[k % len(st.COLORS)], label=f"{_cut_title(grid, cut)}: {label}")
            k += 1
    ax.axhline(vmax - 3.0, color="0.5", linewidth=0.5, linestyle=(0, (1, 2)))
    ax.set_ylim(bottom, math.ceil(vmax / 5.0) * 5.0 + (5 if vmax % 5 == 0 else 0))
    xmin = min(float(c.angle.min()) for c in cuts)
    xmax = max(float(c.angle.max()) for c in cuts)
    ax.set_xlim(xmin, xmax)
    ax.set_xticks(np.arange(math.ceil(xmin / 45) * 45, xmax + 1e-9, 45))
    angle_name = "θ" if all(c.kind == "phi" for c in cuts) else "Angle"
    ax.set_xlabel(f"{angle_name} / deg")
    ax.set_ylabel(f"{grid.label} / {grid.unit}")
    ax.grid(True)
    ax.legend(loc="lower center", frameon=False, fontsize=6, ncol=1 if width < 5 else 2)
    fig.tight_layout()
    return _save(fig, plt, out_dir, f"{stem}_rect", formats)


def _closed_grid(grid: FarfieldGrid) -> tuple[np.ndarray, np.ndarray]:
    phi = grid.phi
    z = grid.total_db
    if len(phi) > 1 and phi[-1] < 360 - 1e-6:
        phi = np.append(phi, 360.0)
        z = np.vstack([z, z[:1]])
    return phi, z


def plot_heatmap(grid: FarfieldGrid, out_dir: Path, stem: str, *, dynamic_range_db: float, width: float,
                 formats: list[str], projection: str = "theta_phi") -> list[str]:
    _, plt, _ = st.require_matplotlib()
    st.apply_style(plt)
    phi, z = _closed_grid(grid)
    vmax = float(np.nanmax(z))
    vmin = vmax - dynamic_range_db
    zc = np.clip(z, vmin, vmax)
    if projection == "uv":
        fig, ax = plt.subplots(figsize=(width, width * 0.85))
        mask = grid.theta <= 90 + 1e-9
        T, P = np.meshgrid(np.deg2rad(grid.theta[mask]), np.deg2rad(phi))
        U, V = np.sin(T) * np.cos(P), np.sin(T) * np.sin(P)
        mesh = ax.pcolormesh(U, V, zc[:, mask], cmap="viridis", vmin=vmin, vmax=vmax, shading="gouraud",
                             rasterized=True)
        ax.set_aspect("equal")
        ax.set_xlim(-1, 1)
        ax.set_ylim(-1, 1)
        ax.set_xlabel(r"$u = \sin\theta\cos\phi$")
        ax.set_ylabel(r"$v = \sin\theta\sin\phi$")
        ax.add_patch(plt.Circle((0, 0), 1.0, fill=False, color="0.3", linewidth=0.5))
    else:
        fig, ax = plt.subplots(figsize=(width, width * 0.6))
        mesh = ax.pcolormesh(phi, grid.theta, zc.T, cmap="viridis", vmin=vmin, vmax=vmax, shading="gouraud",
                             rasterized=True)
        cs = ax.contour(phi, grid.theta, z.T, levels=[vmax - 3.0], colors="white", linewidths=0.6,
                        linestyles="--")
        if cs.allsegs and any(len(s) for s in cs.allsegs[0]):
            ax.clabel(cs, fmt={vmax - 3.0: "−3 dB"}, fontsize=5)
        ax.set_xlabel("φ / deg")
        ax.set_ylabel("θ / deg")
        ax.set_xticks(np.arange(0, 361, 45))
        ax.set_yticks(np.arange(0, 181, 30))
        ax.set_xlim(0, 360)
        ax.set_ylim(180, 0)
    ip, it = np.unravel_index(int(np.nanargmax(grid.total_db)), grid.total_db.shape)
    if projection == "uv":
        th, ph = np.deg2rad(grid.theta[it]), np.deg2rad(grid.phi[ip])
        if grid.theta[it] <= 90:
            ax.plot(np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), marker="+", color="white", markersize=6)
    else:
        ax.plot(grid.phi[ip], grid.theta[it], marker="+", color="white", markersize=6)
    cb = fig.colorbar(mesh, ax=ax, pad=0.02)
    cb.set_label(f"{grid.label} / {grid.unit}")
    fig.tight_layout()
    return _save(fig, plt, out_dir, f"{stem}_heatmap_{'uv' if projection == 'uv' else 'thetaphi'}", formats)


def plot_3d(grid: FarfieldGrid, out_dir: Path, stem: str, *, dynamic_range_db: float, width: float,
            formats: list[str]) -> list[str]:
    matplotlib, plt, _ = st.require_matplotlib()
    st.apply_style(plt)
    from matplotlib import cm
    from matplotlib.colors import Normalize

    phi, z = _closed_grid(grid)
    vmax = float(np.nanmax(z))
    vmin = vmax - dynamic_range_db
    zc = np.clip(np.where(np.isfinite(z), z, vmin), vmin, vmax)
    r = (zc - vmin) / dynamic_range_db
    T, P = np.meshgrid(np.deg2rad(grid.theta), np.deg2rad(phi))
    X, Y, Z = r * np.sin(T) * np.cos(P), r * np.sin(T) * np.sin(P), r * np.cos(T)
    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap = matplotlib.colormaps["viridis"]
    fig = plt.figure(figsize=(width, width * 0.85))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot_surface(X, Y, Z, facecolors=cmap(norm(zc)), rstride=1, cstride=1, linewidth=0.1,
                    edgecolor=(0, 0, 0, 0.15), antialiased=True, shade=False)
    lim = 1.0
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(-lim, lim)
    ax.set_box_aspect((1, 1, 1))
    ax.set_axis_off()
    for vec, name in (((1.15, 0, 0), "x"), ((0, 1.15, 0), "y"), ((0, 0, 1.15), "z")):
        ax.plot([0, vec[0]], [0, vec[1]], [0, vec[2]], color="0.2", linewidth=0.6)
        ax.text(vec[0] * 1.06, vec[1] * 1.06, vec[2] * 1.06, name, fontsize=7)
    ax.view_init(elev=25, azim=-60)
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.65, pad=0.02)
    cb.set_label(f"{grid.label} / {grid.unit}")
    fig.tight_layout()
    return _save(fig, plt, out_dir, f"{stem}_3d", formats)
