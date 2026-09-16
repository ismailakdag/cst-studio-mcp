"""Parse explicit CST export headers; numeric values cannot identify a layout."""

import math
import re
from pathlib import Path

from cst_mcp.execution.curves import frequency_scale


def parse_sparam_csv(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        headers, rows = [], []
        for line in text.splitlines():
            line = line.strip()
            if not line or set(line) <= set("-= \t"):
                continue
            parts = [v for v in re.split(r"[,;\s]+", line) if v]
            try:
                row = [float(v) for v in parts]
            except ValueError:
                headers.append(line)
                continue
            rows.append(row)
        if not rows or any(len(r) < 2 for r in rows):
            raise ValueError("No complete numeric rows")
        header = " ".join(headers).lower()
        scale = frequency_scale(header) / 1e9
        real_imag = bool(
            re.search(r"\b(real|re)\b", header) and re.search(r"\b(imag|imaginary|im)\b", header)
        )
        if real_imag:
            layout = "re_im"
        elif "db" in header:
            layout = "db_phase" if "phase" in header else "db_only"
        elif "mag" in header or "abs" in header:
            layout = "mag_phase" if "phase" in header else "mag_only"
        else:
            raise ValueError(
                "Ambiguous result layout; export explicit Real/Imag or magnitude/dB/phase headers"
            )
        columns = 3 if layout in {"re_im", "db_phase", "mag_phase"} else 2
        if any(len(r) != columns for r in rows):
            raise ValueError("Column count does not match the declared layout")
        if not all(math.isfinite(v) for r in rows for v in r):
            raise ValueError("Non-finite numeric export")
        freq, real, imag, mag, db, phase = [], [], [], [], [], []
        for row in rows:
            freq.append(row[0] * scale)
            if layout == "re_im":
                z = complex(row[1], row[2])
                amplitude = abs(z)
                ph = math.degrees(math.atan2(z.imag, z.real)) if z else None
            else:
                amplitude = 10 ** (row[1] / 20) if layout.startswith("db") else row[1]
                if amplitude < 0:
                    raise ValueError("Magnitude cannot be negative")
                ph = row[2] if columns == 3 else None
                z = (
                    complex(
                        amplitude * math.cos(math.radians(ph)),
                        amplitude * math.sin(math.radians(ph)),
                    )
                    if ph is not None
                    else None
                )
            real.append(z.real if z is not None else None)
            imag.append(z.imag if z is not None else None)
            mag.append(amplitude)
            db.append(20 * math.log10(amplitude) if amplitude else None)
            phase.append(ph)
        if any(b <= a for a, b in zip(freq, freq[1:])):
            raise ValueError("Frequency must be strictly increasing")
        finite = [(f, d) for f, d in zip(freq, db) if d is not None]
        metrics = {}
        if finite:
            f, d = min(finite, key=lambda pair: pair[1])
            metrics = {"min_db": d, "freq_at_min_ghz": f}
        return dict(
            status="ok",
            path=str(path),
            layout_detected=layout,
            frequency_unit="GHz",
            n_points=len(freq),
            frequency_ghz=freq,
            real=real,
            imag=imag,
            magnitude_linear=mag,
            magnitude_db=db,
            phase_deg=phase,
            metrics=metrics,
            complex_available=layout in {"re_im", "db_phase", "mag_phase"},
        )
    except Exception as exc:
        return {"status": "error", "path": str(path), "message": str(exc)}
