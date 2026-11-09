"""Phase diagram generation via pycalphad binplot."""

from __future__ import annotations

import contextlib
import math
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from phaseforge_studio.job import JobState

_element_ref: dict[str, tuple[str, float, float, float]] = {
    "AL": ("FCC_A1", 0.026982, 4540.0, 28.300),
    "FE": ("BCC_A2", 0.055845, 4489.0, 27.280),
    "NI": ("FCC_A1", 0.058693, 5179.0, 29.796),
    "CR": ("BCC_A2", 0.051996, 4050.0, 23.543),
    "CU": ("FCC_A1", 0.063546, 5004.0, 33.150),
    "MO": ("BCC_A2", 0.095940, 4589.0, 28.560),
    "TI": ("HCP_A3", 0.047867, 4824.0, 30.720),
    "CO": ("FCC_A1", 0.058933, 4765.6, 30.040),
    "W": ("BCC_A2", 0.183850, 4970.0, 32.618),
    "B": ("BETA_RHOMBO_B", 0.010811, 1222.0, 5.900),
    "HF": ("HCP_A3", 0.178490, 6301.0, 43.680),
    "TA": ("BCC_A2", 0.180950, 5285.0, 41.470),
    "PT": ("FCC_A1", 0.195080, 5723.7, 41.631),
    "RE": ("HCP_A3", 0.186210, 5765.0, 36.530),
    "V": ("BCC_A2", 0.050941, 4507.0, 30.890),
    "ZR": ("HCP_A3", 0.091224, 5566.0, 39.180),
    "MN": ("CBCC_A12", 0.054938, 4996.0, 32.008),
    "SI": ("DIAMOND_A4", 0.028086, 3217.0, 18.820),
    "C": ("GRAPHITE", 0.012011, 1054.0, 5.740),
}
"""Standard CALPHAD reference states for common elements.

Used when a TDB file lacks ELEMENT declarations (e.g. ATAT minimal format).
Values: (reference_phase, molar_mass_kg_mol, H298_J_mol, S298_J_mol_K).
"""


def _inject_element_declarations(tdb_text: str) -> str:
    """Prepend ELEMENT lines to a TDB that lacks them.

    ATAT minimal-format TDB files omit ELEMENT declarations, which causes
    pycalphad's species_dict to be empty when it processes CONSTITUENT blocks.
    This function extracts element names from CONSTITUENT lines and inserts
    standard ELEMENT declarations so parsing succeeds.

    Args:
        tdb_text (str): Raw TDB file contents.

    Returns:
        TDB text with ELEMENT declarations prepended, or the original text
        if declarations are already present.
    """
    if re.search(r"^\s*ELEMENT\s+\S", tdb_text, re.MULTILINE | re.IGNORECASE):
        return tdb_text
    elements: set[str] = set()
    for m in re.finditer(r"CONSTITUENT\s+\S+\s*:(.*?):", tdb_text, re.IGNORECASE):
        for tok in m.group(1).split(","):
            el = tok.strip().upper()
            if el and el not in ("VA", "/-", "/", ""):
                elements.add(el)
    if not elements:
        return tdb_text
    header_lines = ["ELEMENT VA VACUUM  0 0 0 !"]
    for el in sorted(elements):
        ref, mass, h, s = _element_ref.get(el, ("FCC_A1", 0.0, 0.0, 0.0))
        header_lines.append(f"ELEMENT {el} {ref}  {mass:.6f} {h} {s} !")
    return "\n".join(header_lines) + "\n" + tdb_text


def _phase_diagram_from_tdb(
    tdb_path: Path,
    t_min: float = 300.0,
    t_max: float = 3000.0,
) -> list[Path]:
    """Generate phase diagram PNGs from a TDB file.

    For a binary system (2 non-VA elements) produces one diagram.
    For N>2 elements produces all C(N,2) pseudo-binary sections and tiles
    them into a single grid image matching BLADE's BladeVisualizer output.

    Rendering parameters match BladeVisualizer.plot_binary_phase_diagram:
    figsize (10, 7), dpi 300, 5-tick x-axis, fontsize 15/17/13 for
    labels/title/ticks, LaTeX metal-site fraction axis labels.

    Args:
        tdb_path (Path): Path to the TDB file.
        t_min (float): Minimum temperature in K.
        t_max (float): Maximum temperature in K.

    Returns:
        List of PNG Paths written (single combined image for N>2, or one
        per binary pair if PIL is unavailable).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pycalphad import Database, binplot
    from pycalphad import variables as v

    tdb_text = tdb_path.read_text(errors="ignore")
    tdb_text = _inject_element_declarations(tdb_text)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tdb", delete=False) as _f:
        _f.write(tdb_text)
        _tmp = Path(_f.name)
    try:
        dbf = Database(str(_tmp))
    finally:
        _tmp.unlink(missing_ok=True)

    phases = list(dbf.phases.keys())
    all_els = sorted(e for e in dbf.elements if e not in ("VA", "/-", "/"))
    if len(all_els) < 2:
        return []
    comps = all_els + ["VA"]

    t_step = max(5.0, (t_max - t_min) / 200)
    eps = 1e-3
    pair_pngs: list[Path] = []

    from itertools import combinations

    pairs = list(combinations(all_els, 2))

    _n_ticks = 5
    for el_a, el_b in pairs:
        fixed = {el: 0.0 for el in all_els if el not in (el_a, el_b)}
        metal_site_fraction = 1.0 - sum(fixed.values())
        x_max = metal_site_fraction - eps
        conds: dict[Any, Any] = {
            v.N: 1,
            v.P: 101325,
            v.T: (t_min, t_max, t_step),
            v.X(el_b): (eps, x_max, x_max / 100),
        }
        for el, frac in fixed.items():
            conds[v.X(el)] = frac

        fig, ax = plt.subplots(figsize=(10, 7))
        try:
            binplot(dbf, comps, phases, conds, plot_kwargs={"ax": ax})
        except (ValueError, KeyError) as exc:
            if "need at least one array" in str(exc) or "degrees of freedom" in str(exc).lower():
                ax.clear()
                ax.set_xlim(0, metal_site_fraction)
                ax.set_ylim(t_min, t_max)
                ax.text(
                    metal_site_fraction / 2,
                    (t_min + t_max) / 2,
                    "No two-phase boundaries found",
                    ha="center",
                    va="center",
                )
            else:
                plt.close(fig)
                raise

        tick_vals = [i * metal_site_fraction / (_n_ticks - 1) for i in range(_n_ticks)]
        tick_labels = [f"{i / (_n_ticks - 1):.2f}" for i in range(_n_ticks)]
        ax.set_xticks(tick_vals)
        ax.set_xticklabels(tick_labels, fontsize=13)
        ax.set_xlabel(
            rf"Metal-site fraction $x_{{{el_b}}}$ in $({el_a}_{{1-x}}{el_b}_x)$",
            fontsize=15,
        )
        ax.set_ylabel("Temperature (K)", fontsize=15)
        sys_label = "–".join(all_els)
        title = rf"$({el_a},{el_b})$ Pseudo-Binary Phase Diagram" if len(all_els) == 2 else rf"$({el_a},{el_b})$ section of {sys_label}"
        ax.set_title(title, fontsize=17)
        fig.tight_layout()

        stem = f"{''.join(all_els)}_{el_a}{el_b}_phasediag"
        out = tdb_path.parent / f"{stem}.png"
        fig.savefig(str(out), dpi=300, bbox_inches="tight")
        plt.close(fig)
        pair_pngs.append(out)

    if len(pair_pngs) <= 1:
        return pair_pngs

    try:
        from PIL import Image

        imgs = [Image.open(p) for p in pair_pngs]
        n = len(imgs)
        ncols = math.ceil(math.sqrt(n))
        nrows = math.ceil(n / ncols)
        cell_w = max(img.width for img in imgs)
        cell_h = max(img.height for img in imgs)
        combined = Image.new("RGB", (ncols * cell_w, nrows * cell_h), "white")
        for idx, img in enumerate(imgs):
            row, col = divmod(idx, ncols)
            combined.paste(img, (col * cell_w, row * cell_h))
        sys_name = "".join(all_els)
        combined_path = tdb_path.parent / f"{sys_name}_phase_diagrams.png"
        combined.save(str(combined_path))
        for p in pair_pngs:
            with contextlib.suppress(OSError):
                p.unlink()
        return [combined_path]
    except ImportError:
        return pair_pngs


def _generate_phase_diagrams(
    work_dir: Path,
    species: list[str],
    lattices: list[str],
    job: JobState,
) -> None:
    """Generate phase diagram PNGs from all TDB files in work_dir.

    Args:
        work_dir (Path): Job work directory to search for TDB files.
        species (list[str]): Element species (used for logging only).
        lattices (list[str]): Lattice names (used for logging only).
        job (JobState): Active job for log forwarding.
    """
    import traceback

    try:
        import matplotlib  # noqa: F401
        from pycalphad import Database  # noqa: F401
    except ImportError as e:
        job.push_log(f"[studio] Phase diagram skipped: {e}")
        return

    tdb_files = list(work_dir.rglob("*.tdb"))
    if not tdb_files:
        job.push_log("[studio] No TDB files found for phase diagram.")
        return

    for tdb_path in tdb_files:
        try:
            pngs = _phase_diagram_from_tdb(tdb_path)
            for p in pngs:
                job.push_log(f"[studio] Phase diagram saved: {p.name}")
            if not pngs:
                job.push_log(f"[studio] Skipped {tdb_path.name}: < 2 components")
        except Exception as e:
            job.push_log(f"[studio] Phase diagram failed for {tdb_path.name}: {e}")
            job.push_log(traceback.format_exc()[:800])
