"""Build-time capability gate for chip-dfm-litho-yield. NON-VACUOUS BY DESIGN.

Run during `podman build`; a non-zero exit fails the build.

The defect repaired in this tool was a claim MANUFACTURED FROM THE ABSENCE OF
INPUT -- `opc_ready = len(hotspots) == 0` over a caller-supplied list. A gate
that only imported the module would repeat exactly that mistake, so this one
builds a layout with DELIBERATE, known-size defects and asserts:

  * the screen finds exactly those defects (it can detect), and
  * it finds NOTHING when the limits sit below the drawn geometry (it can be
    clean without being blind), and
  * every absent input fails CLOSED rather than reading as clean.
"""

import os
import sys
import tempfile

sys.path.insert(0, "/app")

import klayout.db as kdb  # noqa: E402
import layout_geometry as G  # noqa: E402

LAYER, DT = 68, 20


def _build():
    """A layout with one 0.05um sliver and one 0.05um gap. Everything else wide."""
    ly = kdb.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("TOP")
    li = ly.layer(LAYER, DT)

    def box(x1, y1, x2, y2):
        top.shapes(li).insert(kdb.Box(int(x1 / ly.dbu), int(y1 / ly.dbu),
                                      int(x2 / ly.dbu), int(y2 / ly.dbu)))

    box(0, 0, 5.0, 0.5)        # wide bar - must NOT be flagged
    box(0, 2.0, 5.0, 2.05)     # 0.05um SLIVER  -> width hotspot at a 0.1 limit
    box(0, 4.0, 5.0, 4.5)      # bar
    box(0, 4.55, 5.0, 5.05)    # 0.05um GAP     -> space hotspot at a 0.1 limit
    p = os.path.join(tempfile.mkdtemp(), "gate.gds")
    ly.write(p)
    return p


def main():
    path = _build()
    ly = G.load(path)

    # 1. DETECTS the deliberate width defect.
    r = G.screen_litho_patterns(ly, LAYER, {"min_width": 0.1}, DT)
    kinds = {h["kind"] for h in r["hotspots"]}
    assert r["assessable"] and "width_below_printability" in kinds, r

    # 2. DETECTS the deliberate space defect.
    r = G.screen_litho_patterns(ly, LAYER, {"min_space": 0.1}, DT)
    assert "space_below_resolution" in {h["kind"] for h in r["hotspots"]}, r

    # 3. IS NOT BLIND: limits below the drawn geometry must yield zero hotspots.
    #    A screen that always fires is as useless as one that never does.
    r = G.screen_litho_patterns(ly, LAYER, {"min_width": 0.01,
                                            "min_space": 0.01}, DT)
    assert r["assessable"] and r["hotspot_count"] == 0, r

    # 4. NO RULES -> not assessable. Never "clean".
    r = G.screen_litho_patterns(ly, LAYER, {}, DT)
    assert r["assessable"] is False and r["hotspots"] is None, r

    # 5. ABSENT LAYER -> not assessable, not empty.
    r = G.screen_litho_patterns(ly, 999, {"min_width": 0.1}, 0)
    assert r["assessable"] is False and r["hotspots"] is None, r

    # 6. UNREADABLE / MISSING layout must RAISE, never return empty.
    for bad in (None, "/definitely/not/a/layout.gds"):
        try:
            G.load(bad)
        except G.LayoutUnavailable:
            pass
        else:
            raise AssertionError("unreadable layout did not raise: %r" % (bad,))

    # 7. DENSITY IS WINDOWED, and the windows genuinely differ. A die-average
    #    can sit mid-window while individual windows are far outside it, so an
    #    average-only check passes exactly the layouts that fail at the foundry.
    d = G.windowed_density(ly, LAYER, 2.0, datatype=DT)
    assert d["assessable"] and d["windows_evaluated"] > 1, d
    assert d["min_density"] < d["max_density"], d

    # 8. Critical area is positive where narrow features and gaps exist.
    c = G.critical_area(ly, LAYER, 0.1, datatype=DT)
    assert c["assessable"] and c["critical_area_um2"] > 0, c

    # 9. The out-of-scope declaration must be present and must name OPC, so the
    #    tool can never be read as having established OPC-readiness.
    mechs = {m["mechanism"] for m in G.OUT_OF_SCOPE}
    assert "opc_ret_verification" in mechs and "aerial_image_simulation" in mechs

    print("DFM_LITHO_CAPABILITY_OK")


if __name__ == "__main__":
    main()
