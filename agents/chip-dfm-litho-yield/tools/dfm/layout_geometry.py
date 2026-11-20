"""Real geometric DFM / litho screening on a layout, via the KLayout db module.

WHY THIS EXISTS
---------------
This tool claimed to "drive KLayout DFM/litho screening". It opened no layout at
all: every number was supplied by the caller, and KLayout was not installed in
the image. The litho scenario was the purest form of the fail-open pattern --

    hotspots = params.get("hotspots", [])
    "opc_ready": len(hotspots) == 0

-- a CLAIM MANUFACTURED FROM THE ABSENCE OF INPUT. Supply nothing, and the tool
reported the design OPC-ready and passed the gate.

This module replaces that with measurements taken from the actual geometry.

WHAT IS IN SCOPE (real, geometric, computable here)
---------------------------------------------------
Pattern-based litho-risk screening: features narrower than the printability
limit, gaps narrower than the resolution limit, notches, and isolated features.
These are genuine litho-risk patterns and are exactly what "pattern-based
hotspot screening" means without a calibrated optical model.

Windowed pattern density, which is the form DFM density rules are actually
written in -- a die-average density can sit mid-window while individual windows
are far outside it.

Critical area by the width/space method, for the yield model.

WHAT IS EXPLICITLY OUT OF SCOPE (and must never be reported as clean)
----------------------------------------------------------------------
Aerial-image simulation, resist modelling, focus/exposure process-window
analysis, and actual OPC/RET verification. Each needs a calibrated optical model
from the foundry and a commercial engine (Calibre/Proteus class). No open
toolchain can do them, so this module does not pretend to: `opc_ready` is NOT
emitted by this tool at all, because geometric screening cannot establish it.
Saying "we found no geometric hotspots" is honest; saying "OPC-ready" is not.
"""

import math

try:
    import klayout.db as kdb
except ImportError:  # pragma: no cover - the container installs it
    kdb = None


class LayoutUnavailable(Exception):
    """Raised when geometry cannot be read. NEVER caught and turned into clean."""


# Mechanisms this module cannot evaluate. Carried into every result so a reader
# is told what was NOT examined, rather than inferring coverage from silence.
OUT_OF_SCOPE = [
    {"mechanism": "aerial_image_simulation",
     "reason": ("requires a calibrated optical model (NA, sigma, illumination) "
                "from the foundry and a litho simulation engine; not available "
                "in any open toolchain")},
    {"mechanism": "resist_model",
     "reason": "requires a calibrated resist model; not available"},
    {"mechanism": "process_window_focus_exposure",
     "reason": ("requires simulating through focus and dose; needs the optical "
                "and resist models above")},
    {"mechanism": "opc_ret_verification",
     "reason": ("OPC correctness is verified against a simulated printed image, "
                "not against drawn geometry; this tool screens DRAWN patterns "
                "only and therefore CANNOT establish OPC-readiness")},
]


def _require_klayout():
    if kdb is None:
        raise LayoutUnavailable(
            "the KLayout db module is not installed, so no geometry can be "
            "measured; this is a packaging failure, not a clean result")


def load(path):
    """Open a GDS/OASIS layout. Fails closed."""
    _require_klayout()
    if not path:
        raise LayoutUnavailable("no layout path supplied")
    ly = kdb.Layout()
    try:
        ly.read(str(path))
    except Exception as e:  # noqa: BLE001 - klayout raises bare RuntimeError
        raise LayoutUnavailable("could not read layout '%s': %s" % (path, e))
    if ly.top_cell() is None or not ly.top_cells():
        raise LayoutUnavailable(
            "layout '%s' has no top cell; nothing was examined" % path)
    return ly


def _region(ly, layer, datatype=0):
    """Flattened region for one drawn layer, or None when the layer is absent.

    NONE MEANS ABSENT, NOT EMPTY. A layer that is not in the layout has not been
    screened; a layer that is present but empty has been screened and is empty.
    Collapsing the two would let a mis-specified layer number read as a clean
    layer.
    """
    idx = ly.find_layer(int(layer), int(datatype))
    if idx is None:
        return None
    return kdb.Region(ly.top_cell().begin_shapes_rec(idx)).merged()


def _um(ly, v):
    """micrometres -> database units."""
    return int(round(float(v) / ly.dbu))


def _area_um2(ly, region):
    return region.area() * (ly.dbu ** 2)


def screen_litho_patterns(ly, layer, rules, datatype=0):
    """Find geometric litho-risk patterns on one layer.

    `rules` carries the node's limits (from the PDK binding), in micrometres:
      min_width      - features narrower than this print unreliably
      min_space      - gaps narrower than this may bridge
      min_notch      - notches narrower than this
      isolated_space - a feature further than this from any neighbour prints
                       differently from a dense one (iso/dense bias)

    A rule that is not supplied is NOT checked and is reported as such. Nothing
    is defaulted: an invented printability limit would silently declare a design
    clean against a number the foundry never specified.
    """
    _require_klayout()
    reg = _region(ly, layer, datatype)
    if reg is None:
        return {"assessable": False, "layer": layer, "hotspots": None,
                "note": ("layer %s/%s is not present in the layout, so it was "
                         "NOT screened; this is not a clean result"
                         % (layer, datatype))}

    hotspots = []
    checked, skipped = [], []

    def _add(kind, edge_pairs, limit, why):
        polys = edge_pairs.polygons()
        n = polys.count()
        if n:
            hotspots.append({
                "kind": kind, "layer": layer, "count": n,
                "limit_um": limit,
                "area_um2": round(_area_um2(ly, polys), 6),
                "why": why})

    mw = rules.get("min_width")
    if mw is not None:
        checked.append("min_width")
        _add("width_below_printability", reg.width_check(_um(ly, mw)), mw,
             ("features narrower than the printability limit round off, pull "
              "back at the ends, or fail to resolve at all"))
    else:
        skipped.append("min_width")

    ms = rules.get("min_space")
    if ms is not None:
        checked.append("min_space")
        _add("space_below_resolution", reg.space_check(_um(ly, ms)), ms,
             ("gaps narrower than the resolution limit may bridge in the "
              "printed image even though the drawn shapes are separate"))
    else:
        skipped.append("min_space")

    mn = rules.get("min_notch")
    if mn is not None:
        checked.append("min_notch")
        _add("notch", reg.notch_check(_um(ly, mn)), mn,
             "notches concentrate the optical proximity effect")
    else:
        skipped.append("min_notch")

    iso = rules.get("isolated_space")
    if iso is not None:
        checked.append("isolated_space")
        _add("isolated_feature", reg.isolated_check(_um(ly, iso)), iso,
             ("an isolated feature prints at a different size than the same "
              "feature in a dense array (iso/dense bias)"))
    else:
        skipped.append("isolated_space")

    if not checked:
        return {"assessable": False, "layer": layer, "hotspots": None,
                "rules_checked": [], "rules_not_supplied": skipped,
                "note": ("no printability limits were supplied for layer %s, so "
                         "NOTHING was screened. Limits come from the PDK "
                         "binding and are never defaulted -- an invented limit "
                         "would declare the design clean against a number the "
                         "foundry never specified." % layer)}

    return {"assessable": True, "layer": layer, "hotspots": hotspots,
            "hotspot_count": sum(h["count"] for h in hotspots),
            "rules_checked": checked, "rules_not_supplied": skipped,
            "shapes_examined": reg.count(),
            "basis": "klayout_geometric_pattern_screen"}


def windowed_density(ly, layer, window_um, step_um=None, datatype=0):
    """Pattern density per window, plus the die-average.

    WINDOWED, because that is how density rules are written. A die-average can
    sit comfortably mid-window while individual windows are far outside it, so
    an average-only check passes exactly the layouts that fail at the foundry.
    """
    _require_klayout()
    reg = _region(ly, layer, datatype)
    if reg is None:
        return {"assessable": False, "layer": layer, "windows": None,
                "note": "layer %s/%s absent; not measured" % (layer, datatype)}

    bbox = ly.top_cell().bbox()
    if bbox.empty():
        return {"assessable": False, "layer": layer, "windows": None,
                "note": "layout bounding box is empty; nothing to measure"}

    w = _um(ly, window_um)
    step = _um(ly, step_um if step_um is not None else window_um)
    if w <= 0 or step <= 0:
        return {"assessable": False, "layer": layer, "windows": None,
                "note": "window/step must be positive"}

    results = []
    y = bbox.bottom
    while y < bbox.top:
        x = bbox.left
        while x < bbox.right:
            box = kdb.Box(x, y, min(x + w, bbox.right), min(y + w, bbox.top))
            clipped = reg & kdb.Region(box)
            dens = clipped.area() / float(box.area()) if box.area() else None
            results.append({"x_um": round(x * ly.dbu, 4),
                            "y_um": round(y * ly.dbu, 4),
                            "density": round(dens, 6) if dens is not None else None})
            x += step
        y += step

    vals = [r["density"] for r in results if r["density"] is not None]
    die = _area_um2(ly, reg) / (bbox.area() * (ly.dbu ** 2)) if bbox.area() else None
    return {"assessable": True, "layer": layer,
            "window_um": window_um,
            "step_um": step_um if step_um is not None else window_um,
            "edge_policy": "clip_to_layout_bbox",
            "windows_evaluated": len(results),
            "min_density": min(vals) if vals else None,
            "max_density": max(vals) if vals else None,
            "die_average_density": round(die, 6) if die is not None else None,
            "windows": results,
            "basis": "klayout_windowed_density"}


def critical_area(ly, layer, defect_size_um, datatype=0):
    """Critical area for a defect of the given size, by the width/space method.

    Geometric approximation, and labelled as one:
      * OPENS   -- a defect of size x breaks a conductor narrower than x, so the
                   open-critical area is the area of conductor narrower than x.
      * SHORTS  -- a defect of size x bridges a gap narrower than x, so the
                   short-critical area is the area of gap narrower than x.

    This is a standard first-order model. It is NOT a Voronoi/exact critical-area
    extraction, and it does not know nets, so shapes on the same net contribute
    to the short term. Both limits are recorded in the result rather than left
    for the reader to discover.
    """
    _require_klayout()
    reg = _region(ly, layer, datatype)
    if reg is None:
        return {"assessable": False, "layer": layer,
                "note": "layer %s/%s absent; critical area not measured"
                        % (layer, datatype)}
    d = _um(ly, defect_size_um)
    if d <= 0:
        return {"assessable": False, "layer": layer,
                "note": "defect size must be positive"}

    opens = reg.width_check(d).polygons()
    shorts = reg.space_check(d).polygons()
    a_open = _area_um2(ly, opens)
    a_short = _area_um2(ly, shorts)
    return {"assessable": True, "layer": layer,
            "defect_size_um": defect_size_um,
            "critical_area_open_um2": round(a_open, 6),
            "critical_area_short_um2": round(a_short, 6),
            "critical_area_um2": round(a_open + a_short, 6),
            "basis": "klayout_width_space_first_order_model",
            "limits": ["first-order geometric model, not Voronoi/exact",
                       "net-unaware: same-net shapes contribute to the short term"]}


def poisson_yield(terms):
    """Y = exp(-sum(A_i * D_i)) with EVERY term accounted for.

    `terms` is a list of {critical_area_um2, defect_density_per_cm2, ...}. A
    term whose density is missing is NOT silently dropped -- see the caller.
    """
    lam = 0.0
    for t in terms:
        lam += float(t["critical_area_um2"]) * 1e-8 * float(t["defect_density_per_cm2"])
    return math.exp(-lam), lam
