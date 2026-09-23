"""Pure-numpy geometry for technical drawings: STL I/O, feature edges, projections.

No CST or matplotlib dependency.  All coordinates handled here are in
millimetres once loaded through :func:`load_stl_dir` / :func:`load_solid`.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

UNIT_TO_MM = {
    "m": 1000.0,
    "cm": 10.0,
    "mm": 1.0,
    "um": 1e-3,
    "nm": 1e-6,
    "in": 25.4,
    "mil": 0.0254,
    "ft": 304.8,
}

MANIFEST_NAME = "manifest.json"
VIEW_NAMES = ("top", "front", "side", "iso")

_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_VERTEX_RE = re.compile(
    rf"vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# STL reading / writing
# ---------------------------------------------------------------------------


def read_stl(path: str | Path) -> np.ndarray:
    """Return triangles as a float64 array of shape (n, 3, 3). ASCII or binary."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + 50 * count == len(data):
            record = np.dtype(
                [("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")]
            )
            arr = np.frombuffer(data, dtype=record, count=count, offset=84)
            return arr["v"].astype(np.float64)
    text = data.decode("latin-1")
    if not text.lstrip().lower().startswith("solid"):
        raise ValueError(f"{path}: not a valid ASCII or binary STL file")
    coords = np.array(_VERTEX_RE.findall(text), dtype=np.float64)
    if coords.size == 0:
        return np.zeros((0, 3, 3))
    if len(coords) % 3:
        raise ValueError(f"{path}: vertex count {len(coords)} is not a multiple of 3")
    return coords.reshape(-1, 3, 3)


def _normals(tris: np.ndarray) -> np.ndarray:
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(norm > 0, n / np.where(norm > 0, norm, 1), 0.0)


def write_stl(path: str | Path, tris: np.ndarray, *, binary: bool = True, name: str = "solid") -> None:
    """Write triangles (n, 3, 3) as binary or ASCII STL (used by tests/fixtures)."""
    tris = np.asarray(tris, dtype=np.float64)
    normals = _normals(tris)
    path = Path(path)
    if binary:
        with path.open("wb") as fh:
            fh.write(name.encode("ascii", "replace")[:80].ljust(80, b" "))
            fh.write(struct.pack("<I", len(tris)))
            for nrm, tri in zip(normals, tris):
                fh.write(struct.pack("<12fH", *nrm, *tri.ravel(), 0))
        return
    lines = [f"solid {name}"]
    for nrm, tri in zip(normals, tris):
        lines.append(f"  facet normal {nrm[0]:e} {nrm[1]:e} {nrm[2]:e}")
        lines.append("    outer loop")
        for v in tri:
            lines.append(f"      vertex {v[0]:.9e} {v[1]:.9e} {v[2]:.9e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def box_triangles(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    """Closed axis-aligned box as 12 outward-facing triangles."""
    p = np.array(
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]],
        dtype=np.float64,
    )
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = []
    for a, b, c, d in quads:
        tris += [(a, b, c), (a, c, d)]
    return p[np.array(tris)]


def ring_triangles(cx, cy, r_in, r_out, z0, z1, segments: int = 48) -> np.ndarray:
    """Closed annular ring (washer) centred at (cx, cy)."""
    t = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    t2 = np.roll(t, -1)

    def pt(r, a, z):
        return np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.full_like(a, z)], axis=1)

    oi, oj = pt(r_out, t, z0), pt(r_out, t2, z0)
    Oi, Oj = pt(r_out, t, z1), pt(r_out, t2, z1)
    ii, ij = pt(r_in, t, z0), pt(r_in, t2, z0)
    Ii, Ij = pt(r_in, t, z1), pt(r_in, t2, z1)
    faces = [
        (Ii, Oi, Oj), (Ii, Oj, Ij),  # top (+z)
        (ii, oj, oi), (ii, ij, oj),  # bottom (-z)
        (oi, oj, Oj), (oi, Oj, Oi),  # outer wall
        (ii, Ii, Ij), (ii, Ij, ij),  # inner wall
    ]
    return np.concatenate([np.stack(f, axis=1) for f in faces])


# ---------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------


@dataclass
class Solid:
    name: str
    tris: np.ndarray  # (n, 3, 3) in mm
    component: str = ""
    material: str = ""
    source: str = ""
    edges: np.ndarray = field(default_factory=lambda: np.zeros((0, 2, 3)))
    edge_faces: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=int))

    @property
    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        pts = self.tris.reshape(-1, 3)
        return pts.min(axis=0), pts.max(axis=0)

    @property
    def size(self) -> np.ndarray:
        lo, hi = self.bbox
        return hi - lo

    @property
    def label(self) -> str:
        return self.name.split(":")[-1]

    def summary(self) -> dict[str, Any]:
        lo, hi = self.bbox
        return {
            "name": self.name,
            "component": self.component,
            "material": self.material,
            "source": self.source,
            "triangles": len(self.tris),
            "feature_edges": len(self.edges),
            "bbox_mm": bbox_dict(lo, hi),
        }


def bbox_dict(lo, hi) -> dict[str, float]:
    r = lambda v: round(float(v), 6)
    return {
        "xmin": r(lo[0]), "xmax": r(hi[0]),
        "ymin": r(lo[1]), "ymax": r(hi[1]),
        "zmin": r(lo[2]), "zmax": r(hi[2]),
        "dx": r(hi[0] - lo[0]), "dy": r(hi[1] - lo[1]), "dz": r(hi[2] - lo[2]),
    }


def feature_edges(tris: np.ndarray, angle_deg: float = 20.0):
    """Return ``(edges (m,2,3), faces (m,2))`` for crease and boundary edges.

    ``faces`` holds the adjacent triangle indices (-1 for a boundary edge).
    """
    crease, _smooth = _classify_edges(tris, angle_deg)
    return crease


def _classify_edges(tris: np.ndarray, angle_deg: float):
    n = len(tris)
    empty = (np.zeros((0, 2, 3)), np.zeros((0, 2), dtype=int))
    if n == 0:
        return empty, empty
    pts = tris.reshape(-1, 3)
    span = float(np.ptp(pts, axis=0).max()) or 1.0
    tol = span * 1e-7
    keys = np.round(pts / tol).astype(np.int64)
    _, vid = np.unique(keys, axis=0, return_inverse=True)
    vid = vid.reshape(n, 3)
    e = np.concatenate([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 0]]])
    coords = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    face = np.tile(np.arange(n), 3)
    e_sorted = np.sort(e, axis=1)
    valid = e_sorted[:, 0] != e_sorted[:, 1]
    e_sorted, coords, face = e_sorted[valid], coords[valid], face[valid]
    _, inv, counts = np.unique(e_sorted, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind="stable")
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    first = order[starts]
    normals = _normals(tris)
    cos_lim = np.cos(np.radians(angle_deg))

    crease_idx, crease_faces, smooth_idx, smooth_faces = [], [], [], []
    # Two-face edges (manifold): vectorised angle test.
    two = counts == 2
    if two.any():
        a = order[starts[two]]
        b = order[starts[two] + 1]
        fa, fb = face[a], face[b]
        cosang = np.einsum("ij,ij->i", normals[fa], normals[fb])
        sharp = cosang < cos_lim
        crease_idx.append(a[sharp])
        crease_faces.append(np.stack([fa[sharp], fb[sharp]], axis=1))
        smooth_idx.append(a[~sharp])
        smooth_faces.append(np.stack([fa[~sharp], fb[~sharp]], axis=1))
    # Boundary or non-manifold edges are always drawn.
    other = ~two
    if other.any():
        idx = first[other]
        crease_idx.append(idx)
        crease_faces.append(np.stack([face[idx], np.full(len(idx), -1)], axis=1))
    ci = np.concatenate(crease_idx) if crease_idx else np.zeros(0, dtype=int)
    cf = np.concatenate(crease_faces) if crease_faces else np.zeros((0, 2), dtype=int)
    si = np.concatenate(smooth_idx) if smooth_idx else np.zeros(0, dtype=int)
    sf = np.concatenate(smooth_faces) if smooth_faces else np.zeros((0, 2), dtype=int)
    return (coords[ci], cf), (coords[si], sf)


def load_solid(path: Path, *, scale: float, name: str, component: str = "",
               material: str = "", angle_deg: float = 20.0) -> Solid:
    tris = read_stl(path) * scale
    solid = Solid(name=name, tris=tris, component=component, material=material, source=str(path))
    (solid.edges, solid.edge_faces), smooth = _classify_edges(tris, angle_deg)
    solid._smooth = smooth  # type: ignore[attr-defined]
    return solid


def load_stl_dir(stl_dir: str | Path, *, units: str | None = None,
                 angle_deg: float = 20.0) -> tuple[list[Solid], dict[str, Any]]:
    """Load every *.stl in a directory. ``manifest.json`` (written by the
    connected export) supplies solid names, materials and file units."""
    root = Path(stl_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"stl_dir does not exist: {root}")
    manifest: dict[str, Any] = {}
    mpath = root / MANIFEST_NAME
    if mpath.is_file():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    file_units = units or manifest.get("units") or "mm"
    if file_units not in UNIT_TO_MM:
        raise ValueError(f"Unsupported units {file_units!r}; use one of {sorted(UNIT_TO_MM)}")
    scale = UNIT_TO_MM[file_units]
    entries = {e["file"]: e for e in manifest.get("solids", []) if "file" in e}
    solids = []
    for path in sorted(root.glob("*.stl")) + sorted(root.glob("*.STL")):
        meta = entries.get(path.name, {})
        solid = load_solid(
            path, scale=scale, angle_deg=angle_deg,
            name=meta.get("name") or path.stem,
            component=meta.get("component", ""),
            material=meta.get("material", ""),
        )
        if len(solid.tris):
            solids.append(solid)
    seen, unique = set(), []
    for s in solids:  # Windows globbing is case-insensitive: drop duplicates
        if s.source.lower() not in seen:
            seen.add(s.source.lower())
            unique.append(s)
    info = {"units_in_file": file_units, "manifest": bool(manifest),
            "project": manifest.get("project", "")}
    return unique, info


def overall_bbox(solids: list[Solid]) -> tuple[np.ndarray, np.ndarray]:
    pts = np.concatenate([s.tris.reshape(-1, 3) for s in solids])
    return pts.min(axis=0), pts.max(axis=0)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def view_basis(view: str) -> np.ndarray:
    """3x3 matrix whose rows are (u, v, depth) axes; depth grows away from viewer.

    Third-angle convention: top looks down -Z, front looks along +Y (viewer at
    -Y), side is the right-side view looking along -X (viewer at +X).
    """
    if view == "top":
        return np.array([[1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=float)
    if view == "front":
        return np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=float)
    if view == "side":
        return np.array([[0, 1, 0], [0, 0, 1], [-1, 0, 0]], dtype=float)
    if view == "iso":
        d = -np.array([1.0, -1.0, 1.0]) / np.sqrt(3)  # viewer at (+x, -y, +z)
        u = np.cross(d, [0.0, 0.0, 1.0])
        u /= np.linalg.norm(u)
        v = np.cross(u, d)
        return np.stack([u, v, d])
    raise ValueError(f"Unknown view {view!r}")


def project(points: np.ndarray, basis: np.ndarray, z_scale: float = 1.0) -> np.ndarray:
    """Project (..., 3) points -> (..., 3) as (u, v, depth). ``z_scale``
    stretches model Z before projection (thin-layer exaggeration)."""
    p = np.array(points, dtype=float, copy=True)
    p[..., 2] *= z_scale
    return p @ basis.T


def view_edges(solid: Solid, view: str, basis: np.ndarray, z_scale: float = 1.0) -> np.ndarray:
    """Crease/boundary edges plus view silhouettes of smooth surfaces, (m,2,3) uvd."""
    edges = [solid.edges]
    smooth_edges, smooth_faces = getattr(solid, "_smooth", (np.zeros((0, 2, 3)), np.zeros((0, 2), int)))
    if len(smooth_edges):
        normals = _normals(solid.tris)
        d = basis[2]
        s = normals[smooth_faces] @ d
        sil = (s[:, 0] * s[:, 1]) < 0
        edges.append(smooth_edges[sil])
    all_edges = np.concatenate(edges) if edges else np.zeros((0, 2, 3))
    uvd = project(all_edges, basis, z_scale)
    length = np.linalg.norm(uvd[:, 1, :2] - uvd[:, 0, :2], axis=1)
    span = max(float(np.ptp(uvd[..., :2].reshape(-1, 2), axis=0).max()) if len(uvd) else 1.0, 1e-9)
    return uvd[length > span * 1e-6]


def split_edges(uvd: np.ndarray, max_len: float, max_pieces: int = 16) -> np.ndarray:
    """Subdivide projected edges so partial occlusion is resolved per piece."""
    if len(uvd) == 0:
        return uvd
    length = np.linalg.norm(uvd[:, 1, :2] - uvd[:, 0, :2], axis=1)
    pieces = np.clip(np.ceil(length / max(max_len, 1e-12)), 1, max_pieces).astype(int)
    out = []
    for k in np.unique(pieces):
        sel = uvd[pieces == k]
        t = np.linspace(0, 1, k + 1)
        a = sel[:, None, 0] + (sel[:, None, 1] - sel[:, None, 0]) * t[None, :-1, None]
        b = sel[:, None, 0] + (sel[:, None, 1] - sel[:, None, 0]) * t[None, 1:, None]
        out.append(np.stack([a, b], axis=2).reshape(-1, 2, 3))
    return np.concatenate(out)


def hidden_mask(segments: np.ndarray, tris_uvd: np.ndarray, eps: float) -> np.ndarray:
    """True where a segment is occluded by a projected triangle nearer to the viewer.

    Three samples (45 %, 50 %, 55 % along the segment) are tested for strict
    interior containment; the segment is hidden when at least two are covered.
    The off-centre samples catch midpoints lying on an occluder's internal
    mesh diagonal, while edges coincident with a nearer outline stay visible.
    """
    m = len(segments)
    if m == 0 or len(tris_uvd) == 0:
        return np.zeros(m, dtype=bool)
    votes = np.zeros(m, dtype=int)
    for f in (0.45, 0.5, 0.55):
        pts = segments[:, 0] + (segments[:, 1] - segments[:, 0]) * f
        votes += _covered(pts, tris_uvd, eps)
    return votes >= 2


def _covered(points: np.ndarray, tris_uvd: np.ndarray, eps: float) -> np.ndarray:
    m = len(points)
    covered = np.zeros(m, dtype=bool)
    a, b, c = tris_uvd[:, 0], tris_uvd[:, 1], tris_uvd[:, 2]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    keep = np.abs(det) > eps * eps
    a, b, c, det = a[keep], b[keep], c[keep], det[keep]
    if len(det) == 0:
        return covered
    tmin = np.minimum(np.minimum(a, b), c)
    tmax = np.maximum(np.maximum(a, b), c)
    bary_tol = 1e-7
    chunk = max(1, int(4_000_000 // max(len(det), 1)))
    for s in range(0, m, chunk):
        p = points[s:s + chunk]
        inside_box = (
            (p[:, None, 0] > tmin[None, :, 0]) & (p[:, None, 0] < tmax[None, :, 0])
            & (p[:, None, 1] > tmin[None, :, 1]) & (p[:, None, 1] < tmax[None, :, 1])
            & (tmin[None, :, 2] < p[:, None, 2] - eps)
        )
        rows, cols = np.nonzero(inside_box)
        if len(rows) == 0:
            continue
        pa, ta, tb, tc, td = p[rows], a[cols], b[cols], c[cols], det[cols]
        l1 = ((tb[:, 0] - pa[:, 0]) * (tc[:, 1] - pa[:, 1]) - (tc[:, 0] - pa[:, 0]) * (tb[:, 1] - pa[:, 1])) / td
        l2 = ((tc[:, 0] - pa[:, 0]) * (ta[:, 1] - pa[:, 1]) - (ta[:, 0] - pa[:, 0]) * (tc[:, 1] - pa[:, 1])) / td
        l3 = 1.0 - l1 - l2
        inside = (l1 > bary_tol) & (l2 > bary_tol) & (l3 > bary_tol)
        depth = l1 * ta[:, 2] + l2 * tb[:, 2] + l3 * tc[:, 2]
        occl = inside & (depth < pa[:, 2] - eps)
        covered[s + np.unique(rows[occl])] = True
    return covered


def chain_segments(segs: np.ndarray, tol: float) -> list[np.ndarray]:
    """Join 2D segments (m,2,2) sharing endpoints into polylines so dash
    patterns run continuously along tessellated curves."""
    if len(segs) == 0:
        return []
    keys = np.round(segs.reshape(-1, 2) / max(tol, 1e-12)).astype(np.int64)
    _, node = np.unique(keys, axis=0, return_inverse=True)
    node = node.reshape(-1, 2)
    adj: dict[int, list[int]] = {}
    for i, (a, b) in enumerate(node):
        if a == b:
            continue
        adj.setdefault(int(a), []).append(i)
        adj.setdefault(int(b), []).append(i)
    used = np.zeros(len(segs), dtype=bool)
    used[node[:, 0] == node[:, 1]] = True
    lines: list[np.ndarray] = []

    def walk(start_node: int, seg: int) -> list[int]:
        path_nodes = [start_node]
        cur_node, cur = start_node, seg
        while cur is not None:
            used[cur] = True
            a, b = int(node[cur, 0]), int(node[cur, 1])
            nxt_node = b if a == cur_node else a
            path_nodes.append(nxt_node)
            cur_node = nxt_node
            options = [s for s in adj.get(cur_node, []) if not used[s]]
            cur = options[0] if len(adj.get(cur_node, [])) == 2 and options else None
        return path_nodes

    coords: dict[int, np.ndarray] = {}
    for i, (a, b) in enumerate(node):
        coords.setdefault(int(a), segs[i, 0])
        coords.setdefault(int(b), segs[i, 1])
    # Start at chain ends (degree != 2) first, then close remaining loops.
    starts = [n for n, lst in adj.items() if len(lst) != 2]
    for n in starts + list(adj):
        for s in adj[n]:
            if not used[s]:
                path = walk(n, s)
                lines.append(np.array([coords[k] for k in path]))
    return lines
