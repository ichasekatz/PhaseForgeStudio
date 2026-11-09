"""Phase diagram generation via pycalphad binplot and G_mix simplex overlay."""

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

    # For N≥3 systems, also generate composition-space phase map
    overlay_pngs: list[Path] = []
    if len(all_els) >= 3:
        sys_name = "".join(all_els)
        overlay_path = tdb_path.parent / f"{sys_name}_phase_map.png"
        try:
            plotted = _plot_phase_overlay(
                dbf,
                all_els,
                phases,
                overlay_path,
                t_start=t_min,
                t_end=t_max,
                t_step=max(100.0, (t_max - t_min) / 15),
            )
            if plotted:
                overlay_pngs.append(overlay_path)
        except Exception:
            pass

    if len(pair_pngs) <= 1:
        return overlay_pngs + pair_pngs

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
        return overlay_pngs + [combined_path]
    except ImportError:
        return overlay_pngs + pair_pngs


def _simplex_grid(n_metals: int, n: int, *, x_total: float = 1.0) -> Any:
    """Recursive composition grid on N-metal simplex summing to x_total."""
    import numpy as np

    step = x_total / n
    pts: list[tuple] = []

    def _recurse(remaining: int, dims_left: int, current: list) -> None:
        if dims_left == 1:
            pts.append(tuple(current + [remaining * step]))
            return
        for i in range(remaining + 1):
            _recurse(remaining - i, dims_left - 1, current + [i * step])

    _recurse(n, n_metals, [])
    return np.array(pts)


def _polygon_vertices(n: int, radius: float = 1.0) -> Any:
    import numpy as np

    if n == 4:
        angles = np.linspace(np.pi / n, 2 * np.pi + np.pi / n, n, endpoint=False)
    else:
        angles = np.linspace(np.pi / 2, 2 * np.pi + np.pi / 2, n, endpoint=False)
    return np.array([[radius * np.cos(a), radius * np.sin(a)] for a in angles])


def _compositions_to_xy(grid: Any, x_total: float) -> tuple[Any, Any]:
    import numpy as np

    verts = _polygon_vertices(grid.shape[1])
    bary = grid / x_total
    xy = np.dot(bary, verts)
    return xy[:, 0], xy[:, 1]


def _find_two_phase_mask(x_cart: Any, y_cart: Any, g_mix: Any, threshold: float = 5.0) -> Any:
    """Points above lower convex hull by > threshold are in two-phase region."""
    import numpy as np
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import ConvexHull

    pts_3d = np.column_stack([x_cart, y_cart, g_mix])
    pts_2d = np.column_stack([x_cart, y_cart])
    try:
        hull = ConvexHull(pts_3d)
    except Exception:
        return np.zeros(len(g_mix), dtype=bool)

    lower_verts = set()
    for simplex, eq in zip(hull.simplices, hull.equations, strict=False):
        if eq[2] < 0:
            lower_verts.update(simplex)
    if len(lower_verts) < 3:
        return np.zeros(len(g_mix), dtype=bool)

    lower_idx = np.array(list(lower_verts))
    interp = LinearNDInterpolator(pts_3d[lower_idx, :2], pts_3d[lower_idx, 2])
    g_convex = interp(pts_2d)
    nan_mask = np.isnan(g_convex)
    g_convex[nan_mask] = g_mix[nan_mask]
    return (g_mix - g_convex) > threshold


def _mask_outside_simplex(triang: Any, x_cart: Any, y_cart: Any, n_metals: int) -> Any:
    import numpy as np
    from matplotlib.path import Path as MplPath

    verts = _polygon_vertices(n_metals)
    closed = np.vstack([verts, verts[0]])
    poly_path = MplPath(closed)
    cx = x_cart[triang.triangles].mean(axis=1)
    cy = y_cart[triang.triangles].mean(axis=1)
    inside = poly_path.contains_points(np.column_stack([cx, cy]), radius=1e-6)
    triang.set_mask(~inside)
    return triang


def _clip_to_simplex(ax: Any, n_metals: int) -> None:
    import numpy as np
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    verts = _polygon_vertices(n_metals)
    closed = np.vstack([verts, verts[0]])
    clip_path = MplPath(closed)
    clip_patch = PathPatch(clip_path, transform=ax.transData)
    for coll in ax.collections:
        coll.set_clip_path(clip_patch)
    for line in ax.lines:
        line.set_clip_path(clip_patch)


def _draw_polygon_frame(ax: Any, labels: list[str]) -> Any:
    import numpy as np
    from matplotlib.patches import Polygon as MplPolygon

    n = len(labels)
    verts = _polygon_vertices(n)
    ax.add_patch(MplPolygon(verts, closed=True, edgecolor="k", facecolor="none", linewidth=2, zorder=0))
    for j, label in enumerate(labels):
        theta = np.arctan2(verts[j, 1], verts[j, 0])
        nx = verts[j, 0] + 0.2 * np.cos(theta)
        ny = verts[j, 1] + 0.2 * np.sin(theta)
        ax.text(nx, ny, label, fontsize=12, ha="center", va="center", fontweight="bold")
    ax.set_aspect("equal")
    ax.axis("off")
    pad = 0.35
    ax.set_xlim(verts[:, 0].min() - pad, verts[:, 0].max() + pad)
    ax.set_ylim(verts[:, 1].min() - pad, verts[:, 1].max() + pad + 0.2)
    return verts


def _compute_gmix_many(
    tdb: Any, all_comps: list[str], metals: list[str], phases: list[str], *, temperatures: Any, grid: Any
) -> dict[int, Any]:
    """Compute G_mix for several temperatures via pycalphad calculate()."""
    import numpy as np
    from pycalphad import calculate

    n_metals = len(metals)
    n_pts = len(grid)
    pts = {metals[i]: grid[:, i] for i in range(n_metals)}

    try:
        result = calculate(tdb, all_comps, phases[0], T=temperatures, P=101325.0, points=pts)
        gm = result.GM
        indexer = {dim: 0 for dim in gm.dims if dim not in {"T", "points"}}
        if indexer:
            gm = gm.isel(indexer)
        gm = gm.transpose("T", "points")
        calc_temps = np.asarray(gm.coords["T"].values, dtype=float)
        gm_vals = np.asarray(gm.values, dtype=float)[:, :n_pts]

        g_ends = []
        for m in metals:
            end_pts = {metals[i]: np.array([1e-10]) for i in range(n_metals)}
            end_pts[m] = np.array([1.0 - (n_metals - 1) * 1e-10])
            r = calculate(tdb, all_comps, phases[0], T=temperatures, P=101325.0, points=end_pts)
            eg = r.GM
            if indexer:
                eg = eg.isel(indexer)
            eg = eg.transpose("T", "points")
            g_ends.append(np.asarray(eg.values, dtype=float)[:, 0])

        endmember = np.column_stack(g_ends)
        baseline = endmember @ grid.T
        g_mix = gm_vals - baseline
        return {int(round(t)): g_mix[i] for i, t in enumerate(calc_temps)}
    except Exception as exc:
        print(f"    batch G_mix failed ({exc}); per-T fallback")

    from pycalphad import calculate as _calc

    result_d: dict[int, Any] = {}
    for t_val in temperatures:
        try:
            res = _calc(tdb, all_comps, phases[0], T=float(t_val), P=101325.0, points=pts)
            gm_t = np.asarray(res.GM.values, dtype=float).ravel()[:n_pts]
            g_e = []
            for m in metals:
                ep = {metals[i]: np.array([1e-10]) for i in range(n_metals)}
                ep[m] = np.array([1.0 - (n_metals - 1) * 1e-10])
                re = _calc(tdb, all_comps, phases[0], T=float(t_val), P=101325.0, points=ep)
                g_e.append(float(re.GM.values.ravel()[0]))
            baseline_t = np.array([sum(grid[i, j] * g_e[j] for j in range(n_metals)) for i in range(n_pts)])
            result_d[int(round(float(t_val)))] = gm_t - baseline_t
        except Exception:
            pass
    return result_d


def _plot_phase_overlay(
    tdb: Any,
    metals: list[str],
    phases: list[str],
    out_path: Path,
    *,
    t_start: float = 300.0,
    t_end: float = 3000.0,
    t_step: float = 300.0,
    n_grid: int = 30,
) -> bool:
    """Generate composition-space phase map for N≥3 metal systems.

    Projects the N-metal simplex to 2D via polygon vertices, computes G_mix
    on a grid of compositions, finds two-phase regions via lower convex hull,
    and overlays shaded regions for each temperature with a plasma colorbar.
    Matches the approach in BLADE's phase_visualization.py.

    Args:
        tdb: pycalphad Database object.
        metals: Sorted list of variable element names.
        phases: Phase names from TDB.
        out_path: Output PNG path.
        t_start: First temperature (K).
        t_end: Final temperature (K).
        t_step: Temperature increment (K).
        n_grid: Grid density per simplex dimension.

    Returns:
        True if any two-phase region was found and plotted.
    """
    import matplotlib
    import matplotlib.cm as mcm
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import tri

    matplotlib.use("Agg")

    t_arr = np.arange(t_start, t_end + 1, t_step, dtype=float)
    if t_arr.size == 0 or t_arr[-1] < t_end - 0.5:
        t_arr = np.append(t_arr, t_end)
    t_arr = np.unique(t_arr)

    all_comps = list(tdb.elements) + ["VA"]
    phase_grid = _simplex_grid(len(metals), n_grid, x_total=1.0)
    x_cart, y_cart = _compositions_to_xy(phase_grid, 1.0)
    triang = tri.Triangulation(x_cart, y_cart)
    triang = _mask_outside_simplex(triang, x_cart, y_cart, len(metals))

    gmix_by_t = _compute_gmix_many(tdb, all_comps, metals, phases, temperatures=t_arr, grid=phase_grid)

    cmap = mcm.plasma
    norm = mcolors.Normalize(vmin=t_start, vmax=t_end)
    fig, ax = plt.subplots(figsize=(9, 8))
    _draw_polygon_frame(ax, [m.title() for m in metals])

    any_two_phase = False
    any_plotted = False

    for t_raw in t_arr:
        t_k = int(t_raw)
        g_mix = gmix_by_t.get(t_k)
        if g_mix is None or np.isnan(g_mix).all():
            continue
        any_plotted = True
        color = cmap(norm(t_k))
        two_phase = _find_two_phase_mask(x_cart, y_cart, g_mix)
        if two_phase.any():
            any_two_phase = True
            shade = two_phase.astype(float)
            ax.tricontourf(triang, shade, levels=[0.5, 1.5], colors=[color], alpha=0.35)
            ax.tricontour(triang, shade, levels=[0.5], colors=[color], linewidths=1.2, alpha=0.9)
            _clip_to_simplex(ax, len(metals))

    if not any_plotted:
        plt.close(fig)
        return False

    sm = mcm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.7)
    cbar.set_label("Temperature (K)", fontsize=11)
    label_str = "-".join(m.title() for m in metals)
    note = "shaded = two-phase" if any_two_phase else "single phase across all T"
    ax.set_title(
        f"{label_str}  {int(t_start)}–{int(t_end)} K  (every {int(t_step)} K)\n{note}",
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return True


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
