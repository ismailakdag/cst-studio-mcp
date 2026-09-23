"""Matplotlib renderer for dimensioned orthographic technical drawings.

All views are drawn in one shared millimetre coordinate plane so that the
third-angle projection stays aligned and at one scale on the sheet:

    +-----------+   +-----+
    |   TOP     |   | ISO |
    +-----------+   +-----+
    +-----------+ +------+
    |  FRONT    | | SIDE |
    +-----------+ +------+
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cst_mcp.execution import academic_style as style
from cst_mcp.execution.drawing_geometry import (
    Solid,
    chain_segments,
    hidden_mask,
    overall_bbox,
    project,
    split_edges,
    view_basis,
    view_edges,
)

_METAL_RE = re.compile(
    r"pec|copper|\bcu\b|gold|silver|alumin|brass|nickel|tin\b|metal|conductor|annealed",
    re.IGNORECASE,
)
_VACUUM_RE = re.compile(r"^(vacuum|air)$", re.IGNORECASE)

VISIBLE_LW = 0.8
HIDDEN_LW = 0.45
DIM_LW = 0.35
DIM_COLOR = "#000000"


@dataclass
class DrawingOptions:
    views: list[str] = field(default_factory=lambda: ["top", "front", "side"])
    layout: str = "sheet"
    formats: list[str] = field(default_factory=lambda: ["pdf", "svg", "png"])
    dpi: int = 600
    title: str = "Technical drawing"
    title_block: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)
    max_solid_dims: int = 4
    hidden_lines: str = "dashed"  # dashed | hide | show
    fill: bool = True
    z_exaggeration: float = 0.0  # 0 = auto, 1 = true scale
    decimals: int = 2
    project_name: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text if text not in {"-0", ""} else "0"


def _clip(text: str, limit: int = 27) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def is_metal(solid: Solid, thin_limit: float) -> bool:
    if solid.material:
        return bool(_METAL_RE.search(solid.material))
    return float(solid.size[2]) <= thin_limit


def shade(solid: Solid, thin_limit: float) -> str | None:
    if solid.material and _VACUUM_RE.match(solid.material):
        return None
    return "0.55" if is_metal(solid, thin_limit) else "0.90"


def auto_z_scale(lo: np.ndarray, hi: np.ndarray, requested: float) -> float:
    if requested and requested > 0:
        return float(requested)
    size = hi - lo
    planar = float(max(size[0], size[1], 1e-12))
    dz = float(size[2])
    if dz <= 0 or dz >= 0.12 * planar:
        return 1.0
    # Make the stack at least ~12 % of the planar extent; round to a nice factor.
    k = 0.12 * planar / dz
    for nice in (2, 2.5, 3, 4, 5, 8, 10, 15, 20, 25, 30, 40, 50, 75, 100, 200, 500, 1000):
        if nice >= k:
            return float(nice)
    return float(np.ceil(k))


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


class DimStack:
    """Allocate non-overlapping offsets on each side of a view."""

    def __init__(self, step: float, base: float):
        self.step, self.base = step, base
        self.levels: dict[str, int] = {}

    def next(self, side: str) -> float:
        level = self.levels.get(side, 0)
        self.levels[side] = level + 1
        return self.base + level * self.step


def draw_dim(ax, p1, p2, side: str, offset: float, text: str, fontsize: float, gap: float):
    """Engineering linear dimension between p1 and p2 (2D points).

    side: 'below'/'above' (horizontal dim) or 'left'/'right' (vertical dim);
    ``offset`` is the absolute coordinate distance from the feature edge.
    """
    (x1, y1), (x2, y2) = p1, p2
    kw = {"color": DIM_COLOR, "lw": DIM_LW, "zorder": 5, "solid_capstyle": "butt"}
    arrow = {"arrowstyle": "<|-|>,head_length=0.35,head_width=0.12", "lw": DIM_LW,
             "color": DIM_COLOR, "shrinkA": 0, "shrinkB": 0, "mutation_scale": fontsize * 1.4}
    if side in ("below", "above"):
        sgn = -1 if side == "below" else 1
        ref = min(y1, y2) if side == "below" else max(y1, y2)
        yd = ref + sgn * offset
        for x, y in ((x1, y1), (x2, y2)):
            ax.plot([x, x], [y + sgn * gap, yd + sgn * gap * 1.5], **kw)
        ax.annotate("", xy=(x1, yd), xytext=(x2, yd), arrowprops=arrow, zorder=5)
        ax.text((x1 + x2) / 2, yd + sgn * gap * 0.6, text, ha="center",
                va="top" if side == "below" else "bottom", fontsize=fontsize, zorder=6,
                bbox={"fc": "white", "ec": "none", "pad": 0.4})
    else:
        sgn = -1 if side == "left" else 1
        ref = min(x1, x2) if side == "left" else max(x1, x2)
        xd = ref + sgn * offset
        for x, y in ((x1, y1), (x2, y2)):
            ax.plot([x + sgn * gap, xd + sgn * gap * 1.5], [y, y], **kw)
        ax.annotate("", xy=(xd, y1), xytext=(xd, y2), arrowprops=arrow, zorder=5)
        ax.text(xd + sgn * gap * 0.6, (y1 + y2) / 2, text, rotation=90,
                ha="right" if side == "left" else "left", va="center",
                fontsize=fontsize, zorder=6, bbox={"fc": "white", "ec": "none", "pad": 0.4})


# ---------------------------------------------------------------------------
# View rendering
# ---------------------------------------------------------------------------


@dataclass
class ViewGeom:
    name: str
    basis: np.ndarray
    z_scale: float
    lo: np.ndarray  # 2D bbox of the view (in projected, possibly exaggerated units)
    hi: np.ndarray
    per_solid: list[tuple[Solid, np.ndarray, np.ndarray, np.ndarray]]  # solid, tris_uvd, vis, hid


def build_view(solids: list[Solid], view: str, z_scale: float, hidden_mode: str) -> ViewGeom:
    zs = z_scale if view in ("front", "side") else 1.0
    basis = view_basis(view)
    tri_uvd = [project(s.tris, basis, zs) for s in solids]
    all_tris = np.concatenate(tri_uvd)
    pts = all_tris.reshape(-1, 3)
    lo2, hi2 = pts[:, :2].min(axis=0), pts[:, :2].max(axis=0)
    span = float(max(np.ptp(pts, axis=0).max(), 1e-9))
    eps = span * 1e-6
    per = []
    for s, t in zip(solids, tri_uvd):
        segs = view_edges(s, view, basis, zs)
        if hidden_mode == "show":
            vis, hid = segs, segs[:0]
        else:
            segs = split_edges(segs, span / 80.0, max_pieces=32)
            mask = hidden_mask(segs, all_tris, eps)
            vis, hid = segs[~mask], segs[mask]
        per.append((s, t, vis, hid))
    return ViewGeom(view, basis, zs, lo2, hi2, per)


def _draw_view(ax, vg: ViewGeom, origin: np.ndarray, opts: DrawingOptions, thin_limit: float):
    from matplotlib.collections import LineCollection, PolyCollection

    shift = origin - vg.lo
    # Painter's algorithm fill: farthest solid first.
    order = sorted(vg.per_solid, key=lambda item: -float(item[1][..., 2].mean()))
    for solid, tris, _vis, _hid in order:
        color = shade(solid, thin_limit) if opts.fill else None
        if color is None:
            continue
        poly = tris[..., :2] + shift
        e1, e2 = poly[:, 1] - poly[:, 0], poly[:, 2] - poly[:, 0]
        area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
        poly = poly[area > 1e-12]
        if len(poly):
            ax.add_collection(PolyCollection(poly, facecolors=color, edgecolors=color,
                                             linewidths=0.05, zorder=1))
    tol = float(np.linalg.norm(vg.hi - vg.lo)) * 1e-6
    for solid, _tris, vis, hid in vg.per_solid:
        if len(hid) and opts.hidden_lines == "dashed":
            ax.add_collection(LineCollection(chain_segments(hid[..., :2] + shift, tol), colors="0.25",
                                             linewidths=HIDDEN_LW, linestyles=(0, (3, 2)), zorder=2))
        if len(vis):
            ax.add_collection(LineCollection(chain_segments(vis[..., :2] + shift, tol), colors="black",
                                             linewidths=VISIBLE_LW, capstyle="round",
                                             joinstyle="round", zorder=3))


def _solid_dims_candidates(solids: list[Solid], lo, hi, limit: int) -> list[Solid]:
    total = hi - lo
    ranked = sorted(solids, key=lambda s: -float(s.size[0] * s.size[1]))
    picked = []
    for s in ranked:
        sz = s.size
        if np.allclose(sz[:2], total[:2], rtol=1e-4, atol=1e-6):
            continue  # same as overall dimension
        if sz[0] <= 0 or sz[1] <= 0:
            continue
        picked.append(s)
        if len(picked) >= limit:
            break
    return picked


def _dimension_view(ax, vg: ViewGeom, origin, solids, opts, lo3, hi3, fs, unit_step):
    """Add dimensions for one placed view; returns extra margins used."""
    d = opts.decimals
    stack = DimStack(step=unit_step * 2.0, base=unit_step * 1.4)
    gap = unit_step * 0.25
    o = np.asarray(origin, dtype=float)
    w, h = vg.hi - vg.lo
    if vg.name == "top":
        draw_dim(ax, (o[0], o[1]), (o[0] + w, o[1]), "below", stack.next("below"),
                 _fmt(hi3[0] - lo3[0], d), fs, gap)
        draw_dim(ax, (o[0], o[1]), (o[0], o[1] + h), "left", stack.next("left"),
                 _fmt(hi3[1] - lo3[1], d), fs, gap)
        seen_x, seen_y = {_fmt(w, d)}, {_fmt(h, d)}
        for s in _solid_dims_candidates(solids, lo3, hi3, opts.max_solid_dims):
            slo, shi = s.bbox
            x0, x1 = o[0] + slo[0] - lo3[0], o[0] + shi[0] - lo3[0]
            y0, y1 = o[1] + slo[1] - lo3[1], o[1] + shi[1] - lo3[1]
            tx, ty = _fmt(shi[0] - slo[0], d), _fmt(shi[1] - slo[1], d)
            if tx not in seen_x:
                seen_x.add(tx)
                ax_off = stack.next("above") + (o[1] + h - y1)
                draw_dim(ax, (x0, y1), (x1, y1), "above", ax_off, tx, fs, gap)
            if ty not in seen_y:
                seen_y.add(ty)
                r_off = stack.next("right") + (o[0] + w - x1)
                draw_dim(ax, (x1, y0), (x1, y1), "right", r_off, ty, fs, gap)
    elif vg.name in ("front", "side"):
        axis = 0 if vg.name == "front" else 1
        draw_dim(ax, (o[0], o[1]), (o[0] + w, o[1]), "below", stack.next("below"),
                 _fmt(hi3[axis] - lo3[axis], d), fs, gap)
        # Layer thicknesses (distinct Z intervals), stacked on the right/left.
        zs = vg.z_scale
        intervals: dict[tuple[float, float], list[str]] = {}
        for s in solids:
            slo, shi = s.bbox
            key = (round(float(slo[2]), 9), round(float(shi[2]), 9))
            if shi[2] - slo[2] > 0:
                mats = intervals.setdefault(key, [])
                if s.material and s.material not in mats:
                    mats.append(s.material)
        z_total = (round(float(lo3[2]), 9), round(float(hi3[2]), 9))
        ordered = [z_total] + sorted((k for k in intervals if k != z_total),
                                     key=lambda k: k[1] - k[0], reverse=True)
        side = "right" if vg.name == "side" else "left"
        edge_x = o[0] + w if side == "right" else o[0]
        thin, shown = [], set()
        for z0, z1 in ordered[: max(1, opts.max_solid_dims + 1)]:
            text = _fmt(z1 - z0, max(d, 3))
            if text in shown:
                continue
            shown.add(text)
            if (z1 - z0) * zs < 1.2 * unit_step and (z0, z1) != z_total:
                thin.append((z0, z1, text, intervals.get((z0, z1), [])))
                continue
            y0 = o[1] + (z0 - lo3[2]) * zs
            y1 = o[1] + (z1 - lo3[2]) * zs
            draw_dim(ax, (edge_x, y0), (edge_x, y1), side, stack.next(side), text, fs, gap)
        # Layers too thin for arrows: leader notes above the view.
        for k, (z0, z1, text, mats) in enumerate(thin):
            y_mid = o[1] + ((z0 + z1) / 2 - lo3[2]) * zs
            tip_x = o[0] + w * (0.08 + 0.3 * k) if side == "left" else o[0] + w * (0.92 - 0.3 * k)
            label = f"t = {text}" + (f", {mats[0]}" if mats else "")
            ax.annotate(label, xy=(tip_x, y_mid),
                        xytext=(tip_x + (unit_step if side == "left" else -unit_step),
                                o[1] + h + unit_step * 1.6),
                        ha="left" if side == "left" else "right", va="bottom", fontsize=fs - 0.5,
                        arrowprops={"arrowstyle": "-|>,head_length=0.3,head_width=0.1",
                                    "lw": DIM_LW, "color": DIM_COLOR, "shrinkA": 1, "shrinkB": 0,
                                    "mutation_scale": fs * 1.4}, zorder=6)
    return stack.levels


def _layout(vgs: dict[str, ViewGeom], gap: float) -> dict[str, np.ndarray]:
    """Third-angle placement of views in the shared plane."""
    pos: dict[str, np.ndarray] = {}
    top, front, side, iso = (vgs.get(k) for k in ("top", "front", "side", "iso"))
    size = {k: v.hi - v.lo for k, v in vgs.items()}
    y_cursor = 0.0
    if front is not None:
        pos["front"] = np.array([0.0, 0.0])
        y_cursor = size["front"][1] + gap
    if top is not None:
        pos["top"] = np.array([0.0, y_cursor])
    ref_w = max(size["top"][0] if top is not None else 0.0, size["front"][0] if front is not None else 0.0)
    if side is not None:
        pos["side"] = np.array([ref_w + gap, 0.0])
    if iso is not None:
        x = ref_w + gap
        y = y_cursor if (front is not None) else 0.0
        if front is None and side is None and top is None:
            x = 0.0
        elif top is not None and front is None and side is None:
            y = 0.0
        pos["iso"] = np.array([x, y])
    if not pos and vgs:
        pos[next(iter(vgs))] = np.array([0.0, 0.0])
    return pos


def _param_lines(params: dict[str, Any], limit: int = 40) -> list[str]:
    lines = []
    for k in sorted(params, key=str.lower)[:limit]:
        v = params[k]
        try:
            fv = float(v)
            v = _fmt(fv, 4) if abs(fv) < 1e6 else f"{fv:.4g}"
        except (TypeError, ValueError):
            v = str(v)
        lines.append(f"{k} = {v}")
    if len(params) > limit:
        lines.append(f"... (+{len(params) - limit} more)")
    return lines


def render(solids: list[Solid], out_dir: Path, basename: str, opts: DrawingOptions) -> dict[str, Any]:
    matplotlib, plt, _np = style.require_matplotlib()
    style.apply_style(plt)
    from matplotlib.patches import Patch

    out_dir.mkdir(parents=True, exist_ok=True)
    lo3, hi3 = overall_bbox(solids)
    size3 = hi3 - lo3
    zk = auto_z_scale(lo3, hi3, opts.z_exaggeration)
    thin_limit = 0.2 * float(max(s.size[2] for s in solids))
    vgs = {v: build_view(solids, v, zk, opts.hidden_lines) for v in opts.views}
    diag = float(np.linalg.norm(size3[:2])) or float(size3.max()) or 1.0
    unit = diag * 0.03  # one "dimension step" in model units
    fs = 6.5

    materials = []
    for s in solids:
        key = s.material or ("metal (assumed)" if is_metal(s, thin_limit) else "dielectric (assumed)")
        c = shade(s, thin_limit) if opts.fill else None
        if c is not None and (key, c) not in materials:
            materials.append((key, c))

    files: list[str] = []
    view_info = []

    def caption(ax, vg, origin, below_levels):
        w, _h = vg.hi - vg.lo
        name = {"top": "TOP VIEW", "front": "FRONT VIEW", "side": "RIGHT SIDE VIEW",
                "iso": "ISOMETRIC VIEW"}[vg.name]
        note = ""
        if vg.name in ("front", "side") and vg.z_scale != 1.0:
            note = f"\n(Z exaggerated ×{_fmt(vg.z_scale, 2)}, not to scale)"
        y = origin[1] - unit * (1.4 + 2.0 * below_levels + 1.0)
        ax.text(origin[0] + w / 2, y, name + note, ha="center", va="top",
                fontsize=fs + 0.5, fontweight="bold", linespacing=1.1)

    def save(fig, stem: str) -> list[str]:
        written = []
        for fmt in opts.formats:
            path = out_dir / f"{stem}.{fmt}"
            kwargs = {"dpi": opts.dpi} if fmt == "png" else {}
            fig.savefig(path, format=fmt, facecolor="white", **kwargs)
            written.append(str(path))
        plt.close(fig)
        return written

    def side_panel(fig, rect, scale_text):
        pax = fig.add_axes(rect)
        panel_h_in = rect[3] * fig.get_figheight()
        line_frac = (fs - 0.5) * 1.3 / 72.0 / panel_h_in
        pax.set_axis_off()
        y = 1.0
        if opts.parameters:
            pax.text(0, y, "PARAMETERS", fontsize=fs + 0.5, fontweight="bold", va="top",
                     transform=pax.transAxes)
            y -= 0.035
            lines = _param_lines(opts.parameters)
            pax.text(0, y, "\n".join(lines), fontsize=fs - 0.5, va="top", family="monospace",
                     transform=pax.transAxes, linespacing=1.25)
            y -= line_frac * (len(lines) + 1.5)
        if materials:
            handles = [Patch(facecolor=c, edgecolor="black", lw=0.4, label=m) for m, c in materials]
            pax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, max(y, 0.3)),
                       frameon=False, fontsize=fs - 0.5, title="MATERIALS",
                       title_fontproperties={"size": fs + 0.5, "weight": "bold"}, alignment="left")
        if opts.title_block:
            rows = [
                ("TITLE", _clip(opts.title)),
                ("MODEL", _clip(opts.project_name or "-")),
                ("UNITS", "mm"),
                ("SCALE", scale_text),
                ("PROJECTION", "Third angle"),
                ("DATE", _dt.datetime.now().astimezone().date().isoformat()),
                ("SOURCE", "CST Studio Suite (STL)"),
            ]
            table = pax.table(cellText=[[k, v] for k, v in rows], colWidths=[0.36, 0.64],
                              loc="lower left", cellLoc="left", edges="closed")
            table.auto_set_font_size(False)
            table.set_fontsize(fs - 0.5)
            for (r, c), cell in table.get_celld().items():
                cell.set_linewidth(0.5)
                cell.set_height(0.028)
                if c == 0:
                    cell.get_text().set_fontweight("bold")

    def finish_axes(ax, xlim, ylim):
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal")
        ax.set_axis_off()

    def scale_label(ax_w_in: float, data_w: float) -> str:
        paper_mm_per_model_mm = ax_w_in * 25.4 / max(data_w, 1e-12)
        if paper_mm_per_model_mm >= 1:
            return f"{_fmt(paper_mm_per_model_mm, 2)}:1 at {style.DOUBLE_COLUMN_IN:g} in sheet width"
        return f"1:{_fmt(1 / paper_mm_per_model_mm, 2)} at {style.DOUBLE_COLUMN_IN:g} in sheet width"

    margin = unit * 10

    if opts.layout == "sheet":
        gap = unit * 12
        pos = _layout(vgs, gap)
        fig_w = style.DOUBLE_COLUMN_IN
        panel = opts.title_block or bool(opts.parameters) or bool(materials)
        main_frac = 0.70 if panel else 0.98
        # Compute extents first with a dummy axis-free pass for limits.
        mins, maxs = [], []
        for v, vg in vgs.items():
            o = pos[v]
            mins.append(o - margin)
            maxs.append(o + (vg.hi - vg.lo) + margin)
        xy_lo, xy_hi = np.min(mins, axis=0), np.max(maxs, axis=0)
        data_w, data_h = xy_hi - xy_lo
        fig_h = float(np.clip(fig_w * main_frac * data_h / data_w, 3.2, 9.5))
        if panel:
            fig_h = max(fig_h, 4.2)
        fig = plt.figure(figsize=(fig_w, fig_h))
        ax = fig.add_axes([0.01, 0.01, main_frac, 0.98])
        for v, vg in vgs.items():
            _draw_view(ax, vg, pos[v], opts, thin_limit)
            levels = {}
            if v != "iso":
                levels = _dimension_view(ax, vg, pos[v], solids, opts, lo3, hi3, fs, unit)
            caption(ax, vg, pos[v], levels.get("below", 0))
            view_info.append({"view": v, "z_scale": vg.z_scale,
                              "extent_mm": [round(float(x), 6) for x in (vg.hi - vg.lo)]})
        finish_axes(ax, (xy_lo[0], xy_hi[0]), (xy_lo[1], xy_hi[1]))
        # Border frame (sheet)
        fig.add_artist(matplotlib.patches.Rectangle((0.004, 0.004), 0.992, 0.992, fill=False,
                                                    lw=0.8, transform=fig.transFigure))
        eff_w = min(fig_w * main_frac, fig_h * 0.98 * data_w / data_h)
        scale_text = scale_label(eff_w, data_w)
        if panel:
            side_panel(fig, [main_frac + 0.03, 0.03, 0.97 - main_frac - 0.03, 0.94], scale_text)
        files += save(fig, basename)
    else:
        for v, vg in vgs.items():
            w, h = vg.hi - vg.lo
            o = np.zeros(2)
            fig_w = style.SINGLE_COLUMN_IN
            data_w, data_h = w + 2 * margin, h + 2 * margin + unit * 3
            fig_h = float(np.clip(fig_w * data_h / data_w, 1.2, 6.0))
            fig = plt.figure(figsize=(fig_w, fig_h))
            ax = fig.add_axes([0.01, 0.01, 0.98, 0.98])
            _draw_view(ax, vg, o, opts, thin_limit)
            levels = {}
            if v != "iso":
                levels = _dimension_view(ax, vg, o, solids, opts, lo3, hi3, fs, unit)
            caption(ax, vg, o, levels.get("below", 0))
            finish_axes(ax, (-margin, w + margin), (-margin - unit * 3, h + margin))
            files += save(fig, f"{basename}_{v}")
            view_info.append({"view": v, "z_scale": vg.z_scale,
                              "extent_mm": [round(float(x), 6) for x in (w, h)]})
    return {"files": files, "views": view_info, "z_exaggeration": zk}
