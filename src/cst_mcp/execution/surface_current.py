"""Surface-current export (CST ASCIIExport) parsing and top-view |J| maps.

CST 2026 writes, for ``2D/3D Results\\Surface Current\\surface current (f=X) [1]``
(an Hfield monitor result), one row per metal-face sample::

    x [mm]  y [mm]  z [mm]  KxRe [A/m]  KxIm [A/m]  KyRe [A/m]  KyIm [A/m]  KzRe [A/m]  KzIm [A/m]  Area [mm^2]
    ------------------------------------------------------------------------------------------------------
    12.864583  0.10007708  0  -0.14808448  -0.95783675  0.057528444  -1.1492193  0  0  0.060984472

Plot.ExportImage in a quiet Design Environment returns only the geometry (even
after SelectTreeItem / RestoreView / Plot.Update), so the map is rendered here
from the exported samples: per top-view cell and per horizontal face layer
(e.g. the top and bottom face of a 35 um copper sheet) the area-weighted mean
K phasor is formed, the layers are summed as complex vectors (total sheet
current), and |J| = sqrt(|Jx|^2 + |Jy|^2) (+ |Jz|^2 if requested).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_COLS = ("x", "y", "z", "kxre", "kxim", "kyre", "kyim", "kzre", "kzim", "area")


@dataclass
class SurfaceCurrentSamples:
    x: Any
    y: Any
    z: Any
    k: Any  # complex (n, 3)
    area: Any
    length_unit: str = "mm"
    columns: tuple[str, ...] = _COLS


def _header_columns(line: str) -> list[str]:
    names = re.findall(r"([A-Za-z][A-Za-z0-9_]*)\s*\[[^\]]*\]", line)
    return [n.lower() for n in names]


def parse_surface_current_ascii(path: str | Path | None = None, *, text: str | None = None) -> SurfaceCurrentSamples:
    """Parse a CST surface-current ASCIIExport (FixedWidth/ascii) file."""
    import numpy as np

    if text is None:
        if path is None:
            raise ValueError("path or text required")
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    cols: list[str] = []
    unit = "mm"
    rows: list[list[float]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or set(s) <= {"-", " "}:
            continue
        parts = s.replace(",", " ").replace(";", " ").split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            if not cols:
                cols = _header_columns(s)
                m = re.search(r"x\s*\[([^\]]+)\]", s, re.I)
                if m:
                    unit = m.group(1).strip()
            continue
        rows.append(vals)
    if not rows:
        raise ValueError("no numeric rows in surface-current export")
    width = min(len(r) for r in rows)
    if width < 10:
        raise ValueError(
            f"surface-current export needs 10 columns (x y z KxRe KxIm KyRe KyIm KzRe KzIm Area), got {width}"
        )
    arr = np.array([r[:width] for r in rows], dtype=float)
    idx = {name: i for i, name in enumerate(_COLS)}
    if cols and len(cols) >= 10:
        found = {c: i for i, c in enumerate(cols)}
        if all(c in found for c in _COLS):
            idx = {c: found[c] for c in _COLS}
        elif not {"x", "y", "z"} <= set(found):
            raise ValueError(f"unexpected surface-current header columns: {cols}")
    k = np.stack([
        arr[:, idx["kxre"]] + 1j * arr[:, idx["kxim"]],
        arr[:, idx["kyre"]] + 1j * arr[:, idx["kyim"]],
        arr[:, idx["kzre"]] + 1j * arr[:, idx["kzim"]],
    ], axis=1)
    return SurfaceCurrentSamples(arr[:, idx["x"]], arr[:, idx["y"]], arr[:, idx["z"]], k,
                                 arr[:, idx["area"]], unit)


def grid_top_view(
    s: SurfaceCurrentSamples,
    *,
    cell: float = 0.4,
    extent: tuple[float, float, float, float] | None = None,
    z_range: tuple[float, float] | None = None,
    layer_split_z: float | None = None,
    include_kz: bool = False,
    min_fill: float = 0.05,
) -> dict[str, Any]:
    """Bin samples into a top-view |J| grid (A/m, peak phasor).

    ``layer_split_z`` separates two face layers (default: midpoint of the
    selected z span when it exceeds 1e-6); each layer's area-weighted mean K
    per cell is summed as a complex vector.  Cells whose sample area is below
    ``min_fill`` * cell^2 are left empty (NaN).
    """
    import numpy as np

    if cell <= 0:
        raise ValueError("cell must be > 0")
    m = np.isfinite(s.x) & np.isfinite(s.y) & np.isfinite(s.area) & (s.area > 0)
    if z_range is None and m.any() and float(np.ptp(s.z[m])) > 0.5:
        # Exports that include a connector body or the substrate's far face span
        # millimetres in z; averaging those faces with the copper hides the
        # current. Default to the thin sheet that carries the most face area
        # (the printed copper, both faces within +-0.1 mm).
        zs, areas = s.z[m], s.area[m]
        bins = np.round(zs / 0.01).astype(int)
        uniq, inv = np.unique(bins, return_inverse=True)
        z_peak = float(uniq[np.argmax(np.bincount(inv, weights=areas))]) * 0.01
        z_range = (z_peak - 0.1, z_peak + 0.1)
    if z_range is not None:
        z0, z1 = sorted(z_range)
        m &= (s.z >= z0) & (s.z <= z1)
    if not m.any():
        raise ValueError("no surface-current samples in the selected z_range/extent")
    x, y, z, k, a = s.x[m], s.y[m], s.z[m], s.k[m], s.area[m]
    if extent is None:
        # Snap the data bounds outwards to whole cells (grid anchored at multiples of ``cell``).
        extent = (math.floor(float(x.min()) / cell + 1e-9) * cell, math.ceil(float(x.max()) / cell - 1e-9) * cell,
                  math.floor(float(y.min()) / cell + 1e-9) * cell, math.ceil(float(y.max()) / cell - 1e-9) * cell)
        if extent[1] <= extent[0]:
            extent = (extent[0], extent[0] + cell, extent[2], extent[3])
        if extent[3] <= extent[2]:
            extent = (extent[0], extent[1], extent[2], extent[2] + cell)
    x0, x1, y0, y1 = extent
    nx = max(1, int(math.ceil((x1 - x0) / cell)))
    ny = max(1, int(math.ceil((y1 - y0) / cell)))
    inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
    x, y, z, k, a = x[inside], y[inside], z[inside], k[inside], a[inside]
    ix = np.clip(((x - x0) / cell).astype(int), 0, nx - 1)
    iy = np.clip(((y - y0) / cell).astype(int), 0, ny - 1)
    if layer_split_z is None and z.size and float(z.max() - z.min()) > 1e-6:
        layer_split_z = float(z.min() + z.max()) / 2
    layers = [np.ones_like(z, dtype=bool)] if layer_split_z is None else [z > layer_split_z, z <= layer_split_z]
    ncomp = 3 if include_kz else 2
    J = np.zeros((ny, nx, ncomp), complex)
    filled = np.zeros((ny, nx), bool)
    for sel in layers:
        if not sel.any():
            continue
        S = np.zeros((ny, nx, ncomp), complex)
        A = np.zeros((ny, nx))
        for c in range(ncomp):
            np.add.at(S[:, :, c], (iy[sel], ix[sel]), k[sel, c] * a[sel])
        np.add.at(A, (iy[sel], ix[sel]), a[sel])
        ok = A > min_fill * cell * cell
        J[ok] += S[ok] / A[ok][:, None]
        filled |= ok
    mag = np.sqrt(np.sum(np.abs(J) ** 2, axis=2))
    mag[~filled] = np.nan
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y0 + (np.arange(ny) + 0.5) * cell
    if np.isfinite(mag).any():
        kmax = np.unravel_index(np.nanargmax(mag), mag.shape)
        jmax = float(mag[kmax])
        at = [float(xs[kmax[1]]), float(ys[kmax[0]])]
    else:  # pragma: no cover - guarded by the checks above
        jmax, at = 0.0, [None, None]
    total = float(np.nansum(mag) * cell * cell)
    return {
        "J": mag, "xs": xs, "ys": ys, "extent": (x0, x0 + nx * cell, y0, y0 + ny * cell),
        "max_A_per_m": jmax, "max_at": at, "integral_A_mm": total,
        "layers": len(layers), "layer_split_z": layer_split_z, "n_samples": int(x.size),
    }


def render_maps(
    grids: list[tuple[str, dict[str, Any]]],
    out_dir: Path,
    *,
    stem: str,
    shared_scale: bool = True,
    dynamic_range_db: float = 40.0,
    formats: list[str] | None = None,
    title: str | None = None,
    length_unit: str = "mm",
    cmap: str = "inferno",
) -> dict[str, Any]:
    """Top-view |J| maps in dB (0 dB = max, shared across panels if requested)."""
    from cst_mcp.execution.academic_style import require_matplotlib

    _, plt, np = require_matplotlib()
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = formats or ["png"]
    vmax_all = max(g["max_A_per_m"] for _, g in grids) or 1.0
    n = len(grids)
    fig, axs = plt.subplots(1, n, figsize=(3.2 * n, 4.6), squeeze=False)
    panels = []
    im = None
    for ax, (label, g) in zip(axs[0], grids):
        ref = vmax_all if shared_scale else (g["max_A_per_m"] or 1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            db = 20 * np.log10(np.maximum(g["J"], 1e-30) / ref)
        db[~np.isfinite(g["J"])] = np.nan
        im = ax.imshow(db, origin="lower", extent=g["extent"], cmap=cmap, vmin=-dynamic_range_db, vmax=0,
                       interpolation="nearest")
        mx, my = g["max_at"]
        if mx is not None:
            ax.plot(mx, my, marker="x", color="c", ms=7, mew=1.5)
        ax.set_title(f"{label}\nmax {g['max_A_per_m']:.3g} A/m at ({mx:.2f}, {my:.2f})", fontsize=7)
        ax.set_xlabel(f"x ({length_unit})")
        ax.set_ylabel(f"y ({length_unit})")
        ax.set_aspect("equal")
        if not shared_scale:
            cb = fig.colorbar(im, ax=ax, shrink=0.8)
            cb.set_label(f"|J_s| (dB re {ref:.3g} A/m)")
        panels.append({"label": label, "max_A_per_m": round(g["max_A_per_m"], 6), "max_at": g["max_at"],
                       "integral_A_mm": round(g["integral_A_mm"], 6), "n_samples": g["n_samples"],
                       "scale_ref_A_per_m": round(ref, 6)})
    if shared_scale and im is not None:
        cb = fig.colorbar(im, ax=axs[0].tolist(), shrink=0.8)
        cb.set_label(f"|J_s| (dB re {vmax_all:.3g} A/m, common scale)")
    if title:
        fig.suptitle(title, fontsize=8)
    files = []
    for fmt in formats:
        p = out_dir / f"{stem}.{fmt}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        files.append(str(p))
    plt.close(fig)
    return {"files": files, "panels": panels, "shared_scale": shared_scale,
            "dynamic_range_db": dynamic_range_db, "scale_ref_A_per_m": round(vmax_all, 6)}


def surface_current_tree_candidates(frequency_ghz: float | None, tree_path: str | None) -> list[str]:
    out = []
    if tree_path:
        out.append(tree_path if tree_path.startswith("2D/3D Results") else
                   f"2D/3D Results\\Surface Current\\{tree_path}")
    if frequency_ghz is not None:
        f = f"{float(frequency_ghz):g}"
        for excitation in ("[1]", "[pw]", ""):
            label = f"surface current (f={f}) {excitation}".strip()
            out.append(f"2D/3D Results\\Surface Current\\{label}")
    return out


def build_export_vba(tree_path: str, out_file: str, *, step: float = 0.25,
                     subvolume: tuple[float, float, float, float, float, float] | None = None) -> str:
    """ASCIIExport of a surface-current item (official ASCIIExport object methods)."""
    from cst_mcp.vba_safety import vba_escape, vba_number

    tp = vba_escape(tree_path, "tree_path")
    fn = vba_escape(out_file.replace("\\", "/"), "out_file")
    st = vba_number(step, "step")
    lines = [
        f'SelectTreeItem "{tp}"',
        "With ASCIIExport",
        "  .Reset",
        f'  .FileName "{fn}"',
        '  .SetFileType "ascii"',
        '  .Mode "FixedWidth"',
        f"  .StepX {st}",
        f"  .StepY {st}",
        f"  .StepZ {st}",
    ]
    if subvolume is not None:
        vals = ", ".join(vba_number(v, "subvolume") for v in subvolume)
        lines += [f"  .SetSubvolume {vals}", "  .UseSubvolume True"]
    lines += ["  .Execute", "End With"]
    return "\n".join(lines)


def acquire(client: Any, args: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    """Export the surface-current item of the open project via ASCIIExport (never solves)."""
    from cst_mcp.execution import figures_3d_cst as fc

    idle = getattr(client, "_idle_error", None)
    if callable(idle):
        blocked = idle()
        if blocked:
            return blocked
    freq = float(args["frequency_ghz"]) if args.get("frequency_ghz") is not None else None
    cands = surface_current_tree_candidates(freq, args.get("tree_path"))
    if not cands:
        return {"status": "error", "message": "Pass frequency_ghz or tree_path (or data_files)."}
    tree = None
    for c in cands:
        try:
            if client.model3d.SelectTreeItem(c):
                tree = c
                break
        except Exception:  # noqa: BLE001
            continue
    if tree is None:
        return {
            "status": "no_results",
            "message": "No surface-current result found. Add an Hfield monitor (cst_add_field_monitor "
            "monitor_type='Hfield'; 'Surfacecurrent' is not a CST 2026 type), solve, then retry; or pass "
            "data_files.",
            "tried_tree_paths": cands,
        }
    export_dir = work_dir / "exports" / "surface_current"
    export_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._=-]+", "_", tree.split("\\")[-1]).strip("_") or "surface_current"
    out = export_dir / f"{safe}.txt"
    try:
        out.unlink(missing_ok=True)
    except OSError:
        pass
    sub = args.get("subvolume")
    vba = build_export_vba(tree, str(out), step=float(args.get("export_step", 0.25)),
                           subvolume=tuple(sub) if sub else None)
    run = fc._run(client, vba)
    if out.is_file() and out.stat().st_size > 0:
        return {"status": "ok", "path": str(out), "tree_path": tree, "run": run.get("status")}
    return {"status": "error", "message": f"ASCIIExport produced no data for {tree}", "tree_path": tree,
            "run": run.get("status"), "run_message": str(run.get("message") or "")[:300]}
