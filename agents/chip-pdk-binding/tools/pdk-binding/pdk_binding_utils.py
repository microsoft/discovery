#!/usr/bin/env python3
"""pdk_binding_utils.py -- PDK resolution, validation, and node switching for the
chip-pdk-binding tool.

Assembles a complete binding, pins every reference with a real sha256 + size, and
fails closed on any missing required reference. Produces a node-switch diff. Results
conform to the Common Design Envelope (the binding travels in pdk_binding).
"""
import hashlib
import json
import os
import re

TOOL = "pdk-binding"
_OUTPUT_DIR = "/output"
_WORK_DIR = "/workdir"


# --- production hardening (migrate_production_hardening.py) ---------------
_PRODUCTION_HARDENING_V1 = True


def _env_dir(default, *names):
    """Return the first non-empty env var in *names*, else *default*."""
    for _n in names:
        _v = os.environ.get(_n)
        if _v:
            return _v
    return default


def _hash_input_file(path):
    try:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as _f:
            for _chunk in iter(lambda: _f.read(65536), b""):
                h.update(_chunk)
        return {"sha256": h.hexdigest(), "bytes": os.path.getsize(path)}
    except Exception:
        return None


_CDE_REQUIRED_FIELDS = (
    "tool", "status", "objective", "tools_used", "pdk_binding", "assumptions",
    "inputs_ref", "vplan", "results", "qor_metrics", "signoff_evidence",
    "margin", "validation", "provenance",
)


def _finalize_envelope(results):
    """(3) CDE self-validation + (4) provenance stamping. Never raises."""
    if not isinstance(results, dict):
        return results
    try:
        # Make the CDE contract invariant: a required field that is legitimately
        # EMPTY for this stage (a node-agnostic / pre-physical tool has no QoR or
        # margin, a spec/RTL stage has no signoff_evidence, etc.) is defaulted to
        # a typed-empty value rather than omitted, so downstream readers can rely
        # on the field existing. Content-bearing fields (objective/results/
        # validation/provenance) are NOT fabricated -- their absence stays a warning.
        _EMPTY_DEFAULTS = {
            "tools_used": [], "assumptions": [], "qor_metrics": {},
            "signoff_evidence": {}, "inputs_ref": {}, "margin": {},
            "vplan": "shared_artifact", "pdk_binding": "none",
        }
        _defaulted = []
        for _k, _dv in _EMPTY_DEFAULTS.items():
            if _k not in results:
                results[_k] = list(_dv) if isinstance(_dv, list) else \
                    (dict(_dv) if isinstance(_dv, dict) else _dv)
                _defaulted.append(_k)
        missing = [k for k in _CDE_REQUIRED_FIELDS if k not in results]
        warns = results.get("envelope_warnings")
        if not isinstance(warns, list):
            warns = []
        if _defaulted:
            warns.append("CDE auto-defaulted empty required field(s): "
                         + ", ".join(sorted(_defaulted)))
        if missing:
            warns.append("CDE missing required field(s): " + ", ".join(missing))
        if warns:
            results["envelope_warnings"] = warns
    except Exception as _e:
        print("[" + str(TOOL) + "] CDE self-check skipped: " + str(_e), flush=True)
    try:
        import datetime
        prov = results.get("provenance")
        if not isinstance(prov, dict):
            prov = {} if prov in (None, "") else {"note": str(prov)}
        prov.setdefault(
            "finished_utc", datetime.datetime.utcnow().isoformat() + "Z")
        prov.setdefault("run_output_dir", _OUTPUT_DIR)
        _hashes = {}

        def _walk(node):
            if isinstance(node, str):
                if os.path.isfile(node):
                    _h = _hash_input_file(node)
                    if _h:
                        _hashes[os.path.basename(node)] = _h
            elif isinstance(node, dict):
                for _x in node.values():
                    _walk(_x)
            elif isinstance(node, (list, tuple)):
                for _x in node:
                    _walk(_x)

        _walk(results.get("inputs_ref"))
        # Always record the input-hash provenance key (even when empty) so the
        # audit chain is explicit rather than a silent gap. An empty map when
        # inputs_ref carried paths means those inputs were not hashable at
        # finalize time (e.g. a container mount no longer present).
        prov.setdefault("input_hashes", _hashes)
        results["provenance"] = prov
    except Exception as _e:
        print("[" + str(TOOL) + "] provenance stamp skipped: " + str(_e), flush=True)

    # --- runtime + peak-memory capture (migrate_runtime_capture.py) --------
    # _CDE_RUNTIME_CAPTURED_V1
    # Cost hints (slot-minutes) and `peak_ram_hint` were expert GUESSES: an audit
    # of 130 real CDEs found only 3 recording any runtime and none recording
    # memory, so every effort budget was calibrated against nothing. This records
    # what the run actually cost.
    #
    # Peak RSS of CHILDREN is the number that matters -- the heavy memory lives
    # in the yosys/openroad/eqy subprocesses, not in this wrapper. Repeated
    # exit-137 OOM kills in this campaign (LEC combine ~23GB; routing 2.18GB
    # against a then-2GB VM) were each diagnosed only forensically, after the
    # kill. Recording the peak on EVERY run makes the next one predictable.
    # Bookkeeping must never fail a design run, so nothing here is fatal.
    try:
        import datetime as _dt
        import time as _time
        _rt = {}
        _start_age = None
        try:
            # Process age on Linux, from the kernel's own accounting.
            #
            # NOT /proc/self mtime -- that looks like process start time but the
            # kernel refreshes it, so it reads ~0s for any run (verified in a
            # real container: a 2s sleep measured 0.006s). Use field 22 of
            # /proc/self/stat (`starttime`, in clock ticks since boot) against
            # /proc/uptime instead. comm (field 2) may itself contain spaces and
            # parentheses, so split after the LAST ')' -- index 19 of that tail
            # is field 22.
            with open("/proc/self/stat", "rb") as _f:
                _tail = _f.read().decode("utf-8", "replace").rsplit(")", 1)[1]
            _ticks = float(_tail.split()[19])
            _hz = float(os.sysconf("SC_CLK_TCK")) or 100.0
            with open("/proc/uptime", "rb") as _f:
                _up = float(_f.read().split()[0])
            _start_age = max(0.0, _up - (_ticks / _hz))
        except Exception:
            _start_age = None
        if _start_age is not None:
            _rt["started_utc"] = _dt.datetime.utcfromtimestamp(
                _time.time() - _start_age).isoformat() + "Z"
            _rt["elapsed_seconds"] = round(_start_age, 3)
            # the effort cost model is denominated in slot-minutes
            _rt["slot_minutes"] = round(_start_age / 60.0, 4)
            _rt["measurement"] = "proc_self_stat_starttime"
        else:
            # Honest absence beats a fabricated zero: a 0.0 here would silently
            # price a real run as free and understate campaign burn.
            _rt["measurement"] = "unavailable"
        try:
            import resource as _res
            # ru_maxrss is KILOBYTES on Linux (bytes on macOS -- containers here
            # are Linux). RUSAGE_CHILDREN covers children that have been waited
            # for, which is exactly how every EDA engine here is invoked
            # (subprocess.run / check_output).
            _self_kb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
            _kid_kb = _res.getrusage(_res.RUSAGE_CHILDREN).ru_maxrss
            _rt["peak_rss_mb_self"] = round(_self_kb / 1024.0, 1)
            _rt["peak_rss_mb_children"] = round(_kid_kb / 1024.0, 1)
            _rt["peak_rss_mb"] = round(max(_self_kb, _kid_kb) / 1024.0, 1)
        except Exception:
            pass
        _prov = results.get("provenance")
        if isinstance(_prov, dict):
            _prov.setdefault("runtime", _rt)
    except Exception as _e:
        print("[" + str(TOOL) + "] runtime capture skipped: " + str(_e),
              flush=True)
    # --- end runtime + peak-memory capture ---------------------------------
    # --- normalized progress contract (migrate_cde_progress.py) -------------
    # Emits the stable `progress` block (residual / verdict_normalized /
    # alignment) that effort budgets, stall detection and QoR analytics read.
    # Freeform `results` keys are NOT stable across attempts, so this mapping is
    # what makes any metric-driven decision possible. Never fatal.
    try:
        import cde_progress as _cde_progress   # _CDE_PROGRESS_STAMPED_V1
        _cde_progress.stamp_progress(results, results.get("stage") or TOOL)
    except Exception as _e:
        print("[" + str(TOOL) + "] progress stamp skipped: " + str(_e), flush=True)
    # --- end normalized progress contract ----------------------------------

    return results
# --- end production hardening --------------------------------------------

_REQUIRED = ["tech_lef", "liberty", "drc_rules", "lvs_rules", "layermap",
             "metal_stack", "spice_models"]

# Per-node ROUTING PROFILE -- the routing range the flow may use, and which layers
# `set_wire_rc` should model signal and clock nets on.
#
# WHY THIS IS A DECLARED PROFILE AND NOT A PURE DERIVATION: the routing range cannot
# be read off the tech LEF alone. sky130's tech LEF marks li1 as TYPE ROUTING, but li1
# is local interconnect that the open flow does NOT signal-route on, and the top metal
# is reserved for the power grid -- neither fact is expressible in LEF. The wire-RC
# layer pair is likewise a methodology choice (the layer whose per-unit R/C models a
# typical net), not a PDK constant. So the profile declares the choice WITH provenance
# and every layer it names is then cross-checked against the tech LEF (see
# _resolve_routing_layers), which is what makes a fabricated layer name fail closed.
#
# ABSENCE IS NOT BENIGN: chip-placement / chip-cts read the wire_rc pair to emit
# `set_wire_rc` before `estimate_parasitics`; without it OpenROAD raises RSZ-0089 and
# repair_design SILENTLY NO-OPS (0 buffers, 0 resizes) while still reporting success.
# chip-routing reads bottom_layer/top_layer and hard-fails without them.
_ROUTING_PROFILES = {
    "sky130": {
        "bottom_layer": "met1",
        "top_layer": "met4",
        "wire_rc_signal_layer": "met1",
        "wire_rc_clock_layer": "met3",
        "_provenance": {
            "bottom_layer": "li1 is local interconnect, not a signal-routing layer in "
                            "the open sky130 flow; the signal range starts at met1",
            "top_layer": "met5 is reserved for the power delivery network",
            "wire_rc_signal_layer": "OpenROAD-flow-scripts "
                                    "flow/platforms/sky130hd/setRC.tcl "
                                    "(set_wire_rc -signal -layer met1)",
            "wire_rc_clock_layer": "OpenROAD-flow-scripts "
                                   "flow/platforms/sky130hd/setRC.tcl "
                                   "(set_wire_rc -clock -layer met3)",
        },
    },
    "nangate45": {
        "bottom_layer": "metal2",
        "top_layer": "metal10",
        "wire_rc_signal_layer": "metal3",
        "wire_rc_clock_layer": "metal5",
        "_provenance": {
            "bottom_layer": "OpenROAD-flow-scripts "
                            "flow/platforms/nangate45/config.mk "
                            "(MIN_ROUTING_LAYER = metal2); metal1 is reserved "
                            "for the standard-cell rails and the PDN M1 grid",
            "top_layer": "OpenROAD-flow-scripts "
                         "flow/platforms/nangate45/config.mk "
                         "(MAX_ROUTING_LAYER = metal10)",
            "wire_rc_signal_layer": "OpenROAD-flow-scripts "
                                    "flow/platforms/nangate45/setRC.tcl "
                                    "(set_wire_rc -signal -layer metal3)",
            "wire_rc_clock_layer": "OpenROAD-flow-scripts "
                                   "flow/platforms/nangate45/setRC.tcl "
                                   "(set_wire_rc -clock -layer metal5)",
        },
    },
}

_ROUTING_LAYER_KEYS = ("bottom_layer", "top_layer",
                       "wire_rc_signal_layer", "wire_rc_clock_layer")

# ---------------------------------------------------------------------------
# NODE CAPABILITY MODEL
#
# WHY THIS EXISTS: until now the flow carried an UNSTATED assumption that every
# signoff gate is runnable, because on sky130 every gate happens to be. The
# assumption is invisible precisely because it has always been true. On a node
# that ships no rule deck for some gate, that silence resolves the wrong way --
# a stage either fabricates a limit or reports a vacuous clean, and both read
# downstream as signoff evidence.
#
# So capability is DECLARED, per node, per gate, with five states:
#
#   available              -- the gate runs and its coverage is complete
#   available_with_gaps    -- the gate runs, but named parts of it do not.
#                             Consumers MUST report pass_with_caveats, never pass.
#   degraded               -- the collateral exists but is weaker than signoff
#                             quality (e.g. geometry-only models, no timing)
#   not_applicable         -- THE NODE cannot do this; no rules exist anywhere
#   requires_provisioning  -- the node CAN do this, but THIS WORKSPACE has not
#                             been given the files (licence-gated download)
#
# `not_applicable` vs `requires_provisioning` is the distinction that matters
# most and is the easiest to collapse: fold them together and a provisioning gap
# silently acquires the authority of a technology fact.
#
# Every non-`available` state MUST carry a `reason`. An unknown node gets NOTHING
# (fail closed) -- absence of a capability profile is never evidence of capability.
_CAPABILITY_PROFILES = {
    "sky130": {
        # sky130 is the validated baseline: every gate is available, and these
        # entries encode the behaviour the flow ALREADY had. Recording it changes
        # nothing at runtime; it makes the previously-implicit assumption legible
        # so a second node cannot inherit it by accident.
        "drc": {"state": "available", "engines": ["klayout", "magic"],
                "mode": "all_must_pass",
                "note": "open_pdks ships complementary Magic and KLayout decks; "
                        "neither alone is a complete signoff"},
        "lvs": {"state": "available", "engine": "netgen"},
        "antenna": {"state": "available", "engine": "magic",
                    "note": "ruleset is the `antenna` directives inside "
                            "libs.tech/magic/sky130A.tech, run by Magic "
                            "antennacheck; there is NO KLayout antenna deck"},
        "density_fill": {"state": "available", "engine": "openroad"},
        "dfm_litho": {"state": "available"},
        "analog_spice": {"state": "available", "engine": "ngspice",
                         "note": "sky130_fd_pr device models ship with open_pdks"},
        "io_pads": {"state": "available", "library": "sky130_ef_io"},
        "sta_corners": {"state": "available"},
        "reliability_em": {
            "state": "available",
            "note": "the tech LEF declares DCCURRENTDENSITY AVERAGE per layer, so "
                    "the PSM EM screen can be ADJUDICATED against a real limit "
                    "(cut layers in mA/via, routing layers in mA/um)",
        },
        "vt_swap": {
            "state": "not_applicable",
            "reason": "sky130_fd_sc_hd is a SINGLE-Vt library; OpenROAD's "
                      "vt_swap move is a no-op here, so the ECO repertoire is "
                      "size/buffer/clone/pin-swap/load-split only",
        },
        # These two are declared for sky130 as well, even though they were added
        # while working on a different node. Leaving them absent here would make
        # the baseline indistinguishable from an UNKNOWN node for these gates --
        # both resolve to None -- and the whole point of the capability model is
        # that "not declared" and "declared available" must never look alike.
        # Both states below are MEASURED, not assumed:
        # sky130_fd_sc_hd ships 441 behavioural modules against 437 LEF macros,
        # with ZERO macros lacking a model (_n45/check_sky130_model_coverage.py).
        "gate_level_simulation": {
            "state": "available",
            "basis": "sky130_fd_sc_hd.v models every one of the 437 LEF macros "
                     "(441 modules, 0 unmodelled), so a gate-level netlist "
                     "elaborates completely",
        },
        "lec": {
            "state": "available",
            "basis": "complete functional-model coverage means no standard cell "
                     "needs to be black-boxed, so an equivalence result is "
                     "unconditional rather than assumption-bounded",
        },
        # Declared rather than inferred from the DRC engine list. On sky130 the
        # two happen to coincide, which is precisely why the coupling survived
        # unnoticed until a node arrived where they differ.
        "extraction": {
            "state": "available",
            "engine": "magic",
            "rationale": "Magic ext2spice is the sky130 open-flow extractor",
        },
    },
    "nangate45": {
        "drc": {
            # DECK IDENTITY IS PART OF THE CAPABILITY. There are two KLayout decks
            # in circulation for this node and they do NOT check the same rules, so
            # "nangate45 DRC coverage" is undefined until the deck is named. An
            # earlier revision of this entry described the ORFS fork and then
            # attributed its gaps to the node, which understated real coverage.
            # Rule-ID counts below are from `output("ID"` / `(ID)` occurrences on
            # non-commented lines (see _n45/compare_drc_decks3.py):
            #     laurentc2 BSD deck .... 131 live, 0 disabled   <- vendored
            #     ORFS GPL fork ......... 129 live, POLY.2/POLY.3 commented out
            #     magic.tech ............  65 live
            #     UNION (BSD + Magic) ... 157 distinct rule IDs
            "state": "available_with_gaps",
            "engines": ["klayout", "magic"],
            "mode": "all_must_pass",
            "deck_license": "BSD-3-Clause",
            "deck_origin": "laurentc2/FreePDK45_for_KLayout drc/drc_freepdk45.lydrc",
            # Magic is a SECOND REAL OPINION here, not a formality. Its 1749-line
            # techfile contributes 26 rule IDs the KLayout deck does not implement
            # at all -- the METALG/METALINT/METALSMG/METALTNG layer-class rules plus
            # VIA7.1/VIA7.2 -- because the two decks group the metal stack
            # differently. Running KLayout alone silently forgoes those checks.
            "engine_contribution": {
                "klayout": "131 rule IDs; the broad per-layer METALn/VIAn set",
                "magic": "65 rule IDs, of which 26 are UNIQUE to Magic "
                         "(METALG.*, METALINT.*, METALSMG.*, METALTNG.*, "
                         "VIA7.1, VIA7.2)",
            },
            "rule_coverage": {
                "WELL.2": "HARD GAP -- minimum spacing of well at different "
                          "potential (225nm) is not coded in ANY of the three "
                          "decks (KLayout BSD, KLayout GPL fork, or Magic). "
                          "This one is a property of the node's open collateral, "
                          "not of a packaging choice.",
                "METALx.3/METALx.4": "ADVISORY -- the via-enclosure rules are live "
                                     "in both KLayout decks and their "
                                     "implementations are byte-identical, but the "
                                     "ORFS maintainer recorded that they 'do not "
                                     "appear to correctly identify violations'. "
                                     "Since the code is the same upstream, treat a "
                                     "clean METALx.3/.4 result as weak evidence "
                                     "rather than as proof.",
            },
            # CONSUMER OBLIGATIONS -- the two settings that decide whether a DRC
            # number on this node describes the DESIGN or describes a broken
            # streamout. Both were got wrong here first, and both produced
            # confident, entirely fictitious violation counts.
            #
            #   1. LAYER MAP. FreePDK45.lyt ships an EMPTY <layer-map> together
            #      with <read-all-layers>true, so a LEF/DEF reader AUTO-ASSIGNS
            #      GDS numbers from LEF declaration order. Measured result:
            #          metal1 -> 3/0   which the decks read as NWELL
            #          via1   -> 4/0                          NPLUS
            #          metal2 -> 5/0                          PPLUS
            #          metal4 -> 9/0                          POLY
            #          via4   -> 10/0                         CONTACT
            #      Routing metal was therefore design-rule-checked AS WELLS AND
            #      IMPLANTS. The decks themselves state the correct numbers
            #      (drc_freepdk45.lydrc lines 64-92; lvs_freepdk45.lylvs lines
            #      67-113) and the vendor cell GDS already uses them.
            #
            #   2. DATABASE UNIT. NangateOpenCellLibrary.gds is written at
            #      dbu=0.0001 um and its geometry is natively 100% on the deck's
            #      2.5nm grid (measured: 818/818 hull vertices across DFF_X1,
            #      AND2_X1, INV_X1, TAPCELL_X1). Merging it into a layout whose
            #      dbu came from the DEF (0.0005) RESCALES every vendor shape 5x
            #      and knocks it off-grid, fabricating tens of thousands of
            #      "vertexes not on grid of 0.0025" errors.
            #
            # Effect of getting both right, same design, same decks:
            #      100843 KLayout items  ->  202
            # The ~100k was MY STREAMOUT, not the library.
            "consumer_obligations": {
                "layer_map": "REQUIRED. Map LEF/DEF layers (and their .PIN/"
                             ".LABEL/.NET/.VIA purposes) onto the FreePDK45 GDS "
                             "numbers from the decks; set read_all_layers=False "
                             "so nothing silently auto-assigns; then ASSERT the "
                             "mapping took effect before trusting any result.",
                "dbu": "REQUIRED. Merge at the CELL LIBRARY's native 0.0001 um. "
                       "0.0001 divides both the DEF grid (0.0005) and the deck "
                       "grid (0.0025) exactly, so neither side is rounded.",
                "single_top_cell": "Reading the full cell GDS brings in ~104 "
                                   "uninstantiated masters as extra top cells; "
                                   "LVS aborts with 'multiple top cells' and a "
                                   "tapeout GDS should not carry them anyway.",
                "pin_names": "produce_pin_names must be ON. The .lyt ships it "
                             "OFF, which yields a bare '.SUBCKT gcd' with NO "
                             "port list and no way for LVS to correspond the "
                             "top cell.",
            },
            # CORRECTION OF AN EARLIER CLAIM IN THIS FILE.
            # A previous revision recorded baseline_integrity=FAILS, asserting
            # that the decks and NangateOpenCellLibrary.gds came from mutually
            # inconsistent upstreams and that block-level DRC was therefore
            # NOT ASSESSABLE. That conclusion was WRONG. The negative control it
            # rested on (magic DRC on untouched DFF_X1 = 23 violations) was
            # itself run through the mis-mapped, mis-scaled setup above. The
            # collateral is self-consistent; the streamout was not.
            "baseline_integrity": {
                "status": "OK, CONDITIONAL on consumer_obligations being met",
                "evidence": "with layer map + native dbu applied, KLayout DRC on "
                            "the gcd bring-up fell from 100843 to 202 items and "
                            "the category list collapsed from 25 mostly-"
                            "well/implant/grid categories to POLY.3 and VIA1.1",
                "superseded_claim": "baseline_integrity=FAILS / NOT_ASSESSABLE "
                                    "(withdrawn: measured through a broken "
                                    "streamout, not a property of the PDK)",
            },
            # OPEN, do not report DRC as closed on this node until resolved.
            "open_discrepancy": {
                "observation": "on the SAME corrected GDS, KLayout reports 202 "
                               "violations and Magic reports 4821",
                "ruled_out": "NOT a Magic layer-mapping defect. magic.tech's "
                             "calma declarations were read and MATCH the decks "
                             "exactly (metal1=11/0, via1=12/0, metal2=13/0, "
                             "metal3=15/0, metal4=17/0, metal5=19/0).",
                "rule_sets_mostly_agree": "Magic fires METAL1.5 + POLY.3; "
                                          "KLayout fires VIA1.1 + POLY.3. POLY.3 "
                                          "is common to both, so the engines are "
                                          "finding the same defect and differ "
                                          "mainly in COUNTING GRANULARITY.",
                "leading_hypothesis": "KLayout counts hierarchically (once per "
                                      "unique cell master) while Magic flattens "
                                      "(once per instance). 4821/202 ~= 24, and "
                                      "the design instantiates 31 masters across "
                                      "918 components, which is the right order. "
                                      "NOT YET CONFIRMED -- do not treat the two "
                                      "numbers as measuring the same quantity.",
            },
            # WHO OWNS THE REMAINING VIOLATIONS. Established by reading the
            # vendor cell GDS DIRECTLY -- native dbu, native layer numbers, no
            # DEF merge, no rescaling, nothing of mine in the path. This is the
            # negative control that is actually valid, unlike the earlier one.
            "violation_attribution": {
                "control": "KLayout DRC on NangateOpenCellLibrary.gds read "
                           "natively, topcell=DFF_X1 -> 22 violations, ALL of "
                           "them POLY.3",
                "POLY.3": "INHERITED FROM THE LIBRARY. 'Poly overhang of "
                          "transistor < 55nm' is intra-cell geometry; no "
                          "placement or routing decision can create or remove "
                          "it. The 182 POLY.3 on the design are the library's, "
                          "and they need a WAIVER WITH A NAMED OWNER -- they "
                          "must not be silently subtracted, and they must not "
                          "be reported as a design defect either.",
                "VIA1.1": "COLLATERAL CONFLICT -- not a routing defect and not "
                          "fixable by the flow. The DRC deck requires every "
                          "via1 edge to be EXACTLY 65nm "
                          "(via1.edges.without_length(65.nm)), but the Nangate "
                          "tech LEF defines via1 as RECT -0.035..0.035 = 70nm, "
                          "and its CUT layer says WIDTH 0.07. Measured in the "
                          "GDS: every via1 is 0.07x0.07um, i.e. exactly what "
                          "the tech LEF specifies. 5 unique via1 shapes x 4 "
                          "edges = the 20 reported items. The deck encodes "
                          "FreePDK45 rules while the cells and tech LEF come "
                          "from the Nangate Open Cell Library -- different "
                          "origins that disagree on this dimension. Upstream "
                          "corroboration: the deck's own OpenRAM README records "
                          "that its memories were 'corrected after DRC under "
                          "KLayout due to some VIA1 and VIA2 errors', and its "
                          "OpenROAD-generated jpeg_nangate45 layout is "
                          "documented as DRC-checked only. Needs a WAIVER WITH A "
                          "NAMED OWNER citing the LEF/deck conflict; closing it "
                          "by resizing vias would violate the tech LEF.",
            },
            # LVS STATUS. Runs end to end and produces a result database; the
            # remaining delta is WELL/BULK connectivity, not logic.
            "lvs_findings": {
                "runs": "yes -- 741 instances on both sides, lvsdb written",
                "reference_netlist": "MUST be the POST-P&R netlist. Using the "
                                     "synthesis netlist is a flow error: the "
                                     "routed DEF carries 1249 components (403 "
                                     "repair_timing hold buffers, CTS buffers, "
                                     "63 tapcells, ~444 fillers) against 331 "
                                     "from synthesis. OpenROAD write_verilog "
                                     "-remove_cells 'FILLCELL_* TAPCELL_*' is "
                                     "the authoritative source.",
                "reference_pin_order": "MUST come from the CDL, not cells.v. "
                                       "cells.v declares DFF_X1(CK,D,Q,QN) while "
                                       "the CDL declares (D CK Q QN VDD VSS) -- "
                                       "different arity AND different order, so "
                                       "appending power pins to Yosys output "
                                       "mis-wires D and CK. All 135 CDL subckts "
                                       "end in exactly 'VDD VSS' (measured).",
                "remaining_mismatch": "PWELL vs VSS -- RESOLVED AS A LIBRARY "
                                      "PROPERTY, not a layout defect. Measured "
                                      "geometrically on the merged design with "
                                      "the deck's OWN tie definitions: "
                                      "ptie = active&pwell&pplus = 0.000 um^2 "
                                      "(0 polygons) and ntie = active&nwell&"
                                      "nplus = 0.000 um^2 (0 polygons). There "
                                      "are ZERO well taps anywhere in the "
                                      "design, so the deck's geometric tie path "
                                      "(pwell -> ptie -> cont -> metal1) has no "
                                      "geometry to act on and PWELL can never "
                                      "join VSS by extraction. TAPCELL_X1 is "
                                      "not a tap: it carries 0 pplus shapes. "
                                      "The deck states the cause itself -- its "
                                      "135 connect_implicit lines exist 'due to "
                                      "lack of taps insides the cells'.",
                "why_it_still_fails": "Read off the deck, not recalled. The "
                                      "deck has TWO connect_explicit branches. "
                                      "The OpenRAM branch (line 215) is "
                                      "connect_explicit(pat, ['BULK','PWELL',"
                                      "'gnd']) -- it NAMES PWELL. The Nangate "
                                      "digital branch actually covering this "
                                      "design (line 221) is connect_explicit("
                                      "pat, ['BULK','VSS']) -- PWELL IS OMITTED. "
                                      "Since connect_global(pwell,'PWELL') put "
                                      "every p-well shape on net PWELL and no "
                                      "tap joins it to VSS, PWELL is left "
                                      "dangling, which is exactly the reported "
                                      "'Net PWELL is not matching any net from "
                                      "reference netlist' (24x) and KLayout's "
                                      "own hint 'Connecting nets VSS and PWELL "
                                      "is making a better match' (17x). "
                                      "Compounding it, both branches iterate a "
                                      "fixed list of LIBRARY cell-name patterns "
                                      "(AND*, OAI*, DFF* ...); a P&R top cell "
                                      "such as 'gcd' matches none, and the deck "
                                      "never mentions TAPCELL at all (0 hits), "
                                      "so the must-connect obligation is never "
                                      "discharged at top level -- reported as "
                                      "'Must-connect nets NWELL and VDD of "
                                      "circuit OAI221_X1 must be connected "
                                      "further up in the hierarchy'.",
                "correct_fix": "Add PWELL to the Nangate branch's connect_"
                               "explicit list (making line 221 consistent with "
                               "line 215, which already does this) and extend "
                               "the pattern list to cover the design top cell. "
                               "That is the deck's OWN documented mechanism for "
                               "a tapless library. It is NOT same_nets: "
                               "same_nets forces two nets equal during compare "
                               "and the KLayout manual warns it 'may mask real "
                               "errors', whereas connect_explicit declares a "
                               "real physical intent the library cannot express "
                               "geometrically. The deck is VENDORED and hashed, "
                               "so editing it is a blast-radius action needing "
                               "its own review -- NOT done here.",
                "upstream_precedent": "Searched. The deck's own working LVS "
                                      "examples (INV.cir, OpenRAM sram_*.sp) "
                                      "are TRANSISTOR-LEVEL custom layouts, "
                                      "where the designer draws taps by hand. "
                                      "The repo also ships an OpenROAD P&R "
                                      "layout (jpeg_nangate45.gds.gz) whose "
                                      "README records a DRC check ONLY -- no "
                                      "LVS. So there is no public precedent for "
                                      "gate-level P&R LVS on this deck, and the "
                                      "tapless top-level gap is the reason.",
                "verdict": "LVS is NOT closed, but the residual is now "
                           "ATTRIBUTED: it is the tapless-library/top-cell gap "
                           "above, not an unexplained logic mismatch. Report "
                           "pass_with_caveats ONLY after the connect_explicit "
                           "extension is reviewed and applied; until then "
                           "not_assessable.",
            },
            "reason": "both engines run and jointly cover 157 rule IDs, but WELL.2 "
                      "is unchecked by every available deck, the via-enclosure "
                      "rules are of doubtful sensitivity, and the KLayout/Magic "
                      "counts currently disagree 20x; consumers must report "
                      "pass_with_caveats, never pass",
        },
        "lvs": {
            "state": "available_with_gaps",
            "engine": "klayout",
            "deck_license": "BSD-3-Clause",
            "deck_origin": "laurentc2/FreePDK45_for_KLayout lvs/lvs_freepdk45.lylvs",
            "source_netlist": "NangateOpenCellLibrary.cdl",
            "note": "DIFFERENT ENGINE FROM sky130 (klayout, not netgen). ORFS's own "
                    "flow/platforms/nangate45/lvs/FreePDK45.lylvs is a dangling "
                    "reference -- an ORFS packaging gap, not a PDK capability gap",
            "cell_coverage": {
                "basis": "Nangate cells carry no internal well taps, so the deck "
                         "cannot resolve bulk connectivity geometrically and "
                         "asserts it per-cell via connect_implicit(<cell>, VDD/VSS). "
                         "That list is CLOSED over the standard-cell set.",
                "omitted": ["TAPCELL_X1", "*_L (LVT variants)",
                            "fakeram45_*", "dummy pads"],
                "enforcement": "chip-lvs must FAIL CLOSED when the netlist contains "
                               "a master outside the asserted set -- never report "
                               "it as a design mismatch",
            },
            "known_deck_bugs": [
                "tolerance() names PMOS_LVT/GVT/HVT and NMOS_LVT/GVT/HVT, but "
                "extract_devices registers PMOS_VTL/VTG/VTH and NMOS_VTL/VTG/VTH "
                "(suffixes transposed), so the 1nm W/L tolerances bind to device "
                "classes that do not exist and default tolerance is used instead",
            ],
            "reason": "deck exists and is in production use (OpenRAM), but its "
                      "per-cell power list does not cover every master the flow "
                      "can place",
        },
        "antenna": {
            "state": "available",
            "engine": "klayout",
            "rule_source": "drc/drc_freepdk45.lydrc ANTENNA group "
                           "(laurentc2 BSD deck, same file as the DRC rules)",
            "ratio": 300.0,
            "layers": "metal1..metal10",
            "note": "MIRROR IMAGE OF sky130, which is magic-engine. The antenna "
                    "ruleset is embedded in the KLayout DRC deck "
                    "(antenna_check(gate, metalN, 300.0, diode)) rather than "
                    "shipped as a standalone deck -- structurally the same "
                    "pattern as sky130 embedding antenna in sky130A.tech",
        },
        # GATE-LEVEL SIMULATION AND LEC ARE LIMITED BY MODEL COVERAGE, not by
        # tool availability -- which is why they are declared here rather than
        # assumed from the fact that Icarus and Yosys both run on this node.
        # cells.v models 100 of 135 cells and omits 29 functional ones.
        "gate_level_simulation": {
            "state": "available_with_gaps",
            "reason": "the behavioural library (work_around_yosys/cells.v) "
                      "models 100 of 135 standard cells. A netlist using any of "
                      "the 29 unmodelled functional cells elaborates to an EMPTY "
                      "black box rather than failing, so the simulation can pass "
                      "while the cell does nothing.",
            "post_scan": "NOT ASSESSABLE -- chip-logic-synthesis stitches "
                         "DFF_X1 -> SDFF_X1 and NO scan flop has a model, so "
                         "every post-DFT netlist on this node contains "
                         "unmodelled state elements",
            "enforcement": "report unmodelled masters by name and degrade the "
                           "verdict; never report a clean run over a netlist "
                           "that could not be fully elaborated",
        },
        "lec": {
            "state": "available_with_gaps",
            "reason": "same root cause as gate_level_simulation: the 29 "
                      "unmodelled cells must be declared black boxes, and a "
                      "black box makes the proof conditional on an assumption "
                      "rather than complete",
            "enforcement": "list every black-boxed master in the evidence; an "
                           "equivalence result that silently black-boxes the "
                           "scan flops is not an equivalence proof of the scan "
                           "netlist",
        },
        # OpenRCX, NOT Magic ext2spice -- and this must be stated rather than
        # derived. magic.tech does carry an `extract` section, so an inference
        # keyed on "is Magic available?" lands on the wrong answer defensibly.
        # The flow's extractor is OpenRCX because that is what produces the
        # per-corner SPEF the three-corner STA on this node consumes, and the
        # node ships Nangate45.rcx_rules to drive it.
        "extraction": {
            "state": "available",
            "engine": "openrcx",
            "rationale": "nangate45 extraction runs OpenROAD OpenRCX against "
                         "Nangate45.rcx_rules, producing the per-corner SPEF "
                         "multi-corner STA needs; Magic's techfile has an "
                         "extract section but is not this flow's extractor",
        },
        "density_fill": {
            "state": "not_applicable",
            "reason": "FreePDK45 publishes no pattern-density rules in any deck, "
                      "so there is no density window to fill toward or measure "
                      "against",
        },
        "dfm_litho": {
            "state": "not_applicable",
            "reason": "the NangateOpenCellLibrary README states the library is "
                      "'purposely non-manufacturable'; no DFM, litho or "
                      "recommended-rule collateral exists",
        },
        "analog_spice": {
            "state": "requires_provisioning",
            "reason": "FreePDK45 base-kit device models (PTM) are a gated "
                      "Si2/Silvaco download and are NOT redistributable, so they "
                      "are absent from this workspace. This is a provisioning gap, "
                      "NOT a statement that the node cannot do analog",
        },
        "io_pads": {
            "state": "degraded",
            "reason": "only dummy pad LEFs exist (OpenROAD "
                      "src/pdn/test/nangate_bsg_black_parrot/dummy_pads*.lef plus "
                      "fake_bumps.lef). They carry geometry and PDN shapes only -- "
                      "no Liberty, no timing, no behavioural model -- so a padring "
                      "can be floorplanned and power-connected but the I/O ring "
                      "must NEVER be reported as functionally verified",
        },
        "sta_corners": {
            "state": "available",
            "note": "THREE corners ship in OpenROAD test/Nangate45: "
                    "Nangate45_slow.lib, Nangate45_typ.lib, Nangate45_fast.lib. "
                    "Multi-corner STA and the slow-corner synthesis shift-left "
                    "both work unchanged. The ORFS platform directory alone is "
                    "misleading -- it references only the typical Liberty",
        },
        "reliability_em": {
            "state": "degraded",
            "reason": "the FreePDK45 tech LEF declares NO DCCURRENTDENSITY (verified "
                      "against the ORFS platform tree: sky130hd/hs, gf180 and "
                      "ihp-sg13g2 all declare it, nangate45 does not). PSM can still "
                      "emit a per-segment CURRENT table, so the screen is "
                      "run-but-UNCOMPARED: every layer is unresolved and em_status "
                      "must be not_assessable. Importing another node's limit would "
                      "manufacture a margin out of nothing",
        },
        "vt_swap": {
            "state": "available",
            "vt_library_count": 2,
            "libraries": ["Nangate45 (nominal)", "Nangate45_lvt"],
            "note": "INVERTS THE sky130 RULE. Nangate45_lvt.lef/.lib provide a "
                    "genuine second Vt flavour (SDFF_X1_L etc.), so VT swap is a "
                    "REAL ECO transformation here. Suppressing it on this node "
                    "would under-repair timing",
        },
    },
}

_CAPABILITY_STATES = (
    "available",
    "available_with_gaps",
    "degraded",
    "not_applicable",
    "requires_provisioning",
)

# Every state except `available` must explain itself. A bare "not_applicable"
# with no reason is indistinguishable from an unfilled field.
_CAPABILITY_STATES_REQUIRING_REASON = (
    "available_with_gaps",
    "degraded",
    "not_applicable",
    "requires_provisioning",
)


def _capability_profile_for(pdk):
    """Return the capability profile for a node, or {} when the node is unknown."""
    pdk = str(pdk or "").strip().lower()
    for name, profile in _CAPABILITY_PROFILES.items():
        if pdk.startswith(name):
            return profile
    return {}


def _capability_state(pdk, gate):
    """State of one gate on one node; None when undeclared.

    Returning None (rather than a cheerful default) is the point: a caller that
    cannot find a declaration must fail closed, not assume the gate is runnable.
    """
    entry = _capability_profile_for(pdk).get(gate)
    if isinstance(entry, dict):
        return entry.get("state")
    return None


def _resolve_capabilities(params):
    """Resolve the binding's per-gate `capabilities` block.

    Precedence matches routing_layers / tool_policy / density_windows:
      1. caller-supplied capabilities pass through   -> `caller_supplied`
      2. a known node applies its declared profile   -> `pdk_default`
      3. an unknown node emits NOTHING               -> `none`

    Case 3 is deliberate and is the whole safety property: an unknown node does
    not get a default set of `available` gates, because that would hand a brand
    new PDK a full set of signoff capabilities it was never shown to have.
    """
    explicit = params.get("capabilities")
    if isinstance(explicit, dict) and explicit:
        return dict(explicit), "caller_supplied", _capability_problems(explicit)
    profile = _capability_profile_for(params.get("pdk") or params.get("node"))
    if not profile:
        return {}, "none", []
    resolved = {gate: dict(entry) for gate, entry in profile.items()}
    return resolved, "pdk_default", _capability_problems(resolved)


def _capability_problems(capabilities):
    """Reject a capability block that cannot be acted on.

    A malformed capability is worse than a missing one: `{"state": "nonsense"}`
    reads as a declaration while meaning nothing, and a `not_applicable` with no
    reason cannot be distinguished from an unfilled template field.
    """
    problems = []
    for gate, entry in sorted(capabilities.items()):
        if not isinstance(entry, dict):
            problems.append("capability %s is not an object" % gate)
            continue
        state = entry.get("state")
        if state not in _CAPABILITY_STATES:
            problems.append(
                "capability %s has unknown state %r (expected one of %s)"
                % (gate, state, ", ".join(_CAPABILITY_STATES)))
            continue
        if state in _CAPABILITY_STATES_REQUIRING_REASON:
            explanation = (entry.get("reason") or entry.get("note")
                           or entry.get("rule_coverage")
                           or entry.get("absent_engines"))
            if not explanation:
                problems.append(
                    "capability %s is %s but carries no reason/note -- a "
                    "non-available state must explain itself" % (gate, state))
    return problems

_CTS_PROFILES = {
    "sky130": {
        "clock_buffers": [
            "sky130_fd_sc_hd__clkbuf_1",
            "sky130_fd_sc_hd__clkbuf_2",
            "sky130_fd_sc_hd__clkbuf_4",
            "sky130_fd_sc_hd__clkbuf_8",
            "sky130_fd_sc_hd__clkbuf_16",
        ],
        "root_buffer_cell": "sky130_fd_sc_hd__clkbuf_16",
        "_provenance": {
            "approved_set": "Sky130 standard-cell LEF and every bound core Liberty corner",
            "root_selection": "open_pdks Sky130A sky130_fd_sc_hd CTS_ROOT_BUFFER",
        },
    },
    "nangate45": {
        "clock_buffers": [
            "CLKBUF_X1",
            "CLKBUF_X2",
            "CLKBUF_X3",
        ],
        "root_buffer_cell": "CLKBUF_X3",
        # TWO UPSTREAMS DISAGREE ABOUT THESE CELLS, so the choice is recorded
        # rather than left implicit:
        #   ORFS flow/platforms/nangate45/config.mk
        #       DONT_USE_CELLS = TAPCELL_X1 FILLCELL_X1 AOI211_X1 OAI211_X1
        #       -> CLKBUF_* permitted. This is the PRODUCTION platform
        #          definition and it is the one this binding follows.
        #   OpenROAD test/Nangate45/Nangate45.vars
        #       dont_use {CLKBUF_* AOI211_X1 OAI211_X1}; cts_buffer BUF_X4
        #       -> CLKBUF_* banned. This is a REGRESSION-TEST config.
        # The cells exist in the Liberty either way, which is exactly what makes
        # this dangerous: a tool handed a dont_use cell does not error, it
        # builds the clock tree and reports success. A consumer that follows the
        # OpenROAD vars must override clock_buffers to ["BUF_X4"] EXPLICITLY
        # rather than assume this default matches its own flow config.
        "dont_use_conflict": {
            "cells": ["CLKBUF_X1", "CLKBUF_X2", "CLKBUF_X3"],
            "permitted_by": "ORFS config.mk (followed here)",
            "banned_by": "OpenROAD test/Nangate45/Nangate45.vars "
                         "(dont_use CLKBUF_*, cts_buffer BUF_X4)",
            "fallback": "BUF_X4",
        },
        "_provenance": {
            "approved_set": "NangateOpenCellLibrary clock-buffer family; every name is "
                            "cross-checked against the bound cell LEF and Liberty "
                            "before it is emitted "
                            "(_n45/validate_nangate45_collateral.py)",
            "root_selection": "CLKBUF_X3 is the strongest clock buffer the library "
                              "ships (the ladder stops at X3, unlike sky130's X16)",
        },
    },
}

_PDN_PROFILES = {
    "sky130": {
        "fixed_vias": ["M1M2_PR", "M2M3_PR", "M3M4_PR", "M4M5_PR"],
        "settings": {
            "rail": {"layer": "met1", "width": 0.48, "followpins": True},
            "straps": [
                {"layer": "met4", "width": 1.6, "pitch": 56.0, "offset": 2.0},
                {"layer": "met5", "width": 1.6, "pitch": 56.0, "offset": 2.0},
            ],
            "connects": [
                {"layers": ["met1", "met4"]},
                {"layers": ["met4", "met5"]},
            ],
        },
        "rationale": (
            "Sky130 HD follow-pin geometry and the OpenROAD-flow-scripts PDN "
            "baseline; all layers and fixed vias are cross-checked against the "
            "pinned technology LEF"
        ),
    },
    "nangate45": {
        "fixed_vias": [],
        "settings": {
            "rail": {"layer": "metal1", "width": 0.17, "followpins": True},
            "straps": [
                {"layer": "metal4", "width": 0.48, "pitch": 56.0, "offset": 2.0},
                {"layer": "metal7", "width": 1.40, "pitch": 40.0, "offset": 2.0},
            ],
            "connects": [
                {"layers": ["metal1", "metal4"]},
                {"layers": ["metal4", "metal7"]},
            ],
        },
        "rationale": (
            "OpenROAD-flow-scripts flow/platforms/nangate45/"
            "grid_strategy-M1-M4-M7.tcl (M1 follow-pin rail, M4 and M7 straps). "
            "fixed_vias is deliberately EMPTY: unlike sky130 the FreePDK45 tech LEF "
            "declares no named fixed-via rules, so pdngen generates vias from the "
            "cut rules. An empty list is the honest answer; a fabricated via name "
            "would fail the tech-LEF cross-check anyway."
        ),
    },
}

_FUNCTIONAL_MODEL_PROFILES = {
    "sky130": {
        "yosys": {
            "reference": "cell_models",
            "defines": ["FUNCTIONAL", "UNIT_DELAY="],
        },
        "iverilog": {
            "references": ["primitives", "cell_models"],
            "defines": {"FUNCTIONAL": None},
        },
        "yosys_io": {
            "references": ["io_cell_models", "io_wrapper_models"],
            "defines": [],
            "input_bridges": [
                {
                    "module": "sky130_fd_io__top_gpiov2",
                    "external_port": "PAD",
                    "internal_port": "IN",
                },
            ],
        },
        "provenance": (
            "Open_PDKs sky130 standard-cell functional Verilog contract"
        ),
    },
    "nangate45": {
        "yosys": {
            "reference": "cell_models",
            "defines": [],
        },
        "iverilog": {
            "references": ["cell_models"],
            "defines": {},
        },
        # MODEL COVERAGE IS PARTIAL, AND THE MISSING SET IS NOT RANDOM.
        # cells.v defines 100 modules against 135 LEF macros. Eight of the 37
        # absentees are physical-only (FILLCELL_*, TAPCELL_X1, ANTENNA_X1) and
        # correctly have no behaviour. The remaining 29 are REAL LOGIC, and they
        # cluster on exactly the cells a backend flow inserts for you:
        #   - every scan flop   SDFF_X1/X2, SDFFR_*, SDFFS_*, SDFFRS_*
        #   - every clock gate  CLKGATE_X*, CLKGATETST_X*
        #   - every tristate    TBUF_X*, TINV_X1
        #   - every latch       DLH_*, DLL_*, TLAT_X1   and DFFRS_X1/X2
        # The scan entry is the sharp one: chip-logic-synthesis stitches
        # DFF_X1 -> SDFF_X1, so the post-DFT netlist is guaranteed to contain a
        # cell that cells.v cannot elaborate. A simulator handed that netlist
        # does not fail loudly -- it infers an empty black box and the testbench
        # then passes over a design whose state elements do nothing.
        "coverage": {
            "modelled": 100,
            "lef_macros": 135,
            "physical_only_absent": ["ANTENNA_X1", "TAPCELL_X1", "FILLCELL_*"],
            "functional_absent": [
                "SDFF_X1", "SDFF_X2", "SDFFR_X1", "SDFFR_X2",
                "SDFFS_X1", "SDFFS_X2", "SDFFRS_X1", "SDFFRS_X2",
                "CLKGATE_X1", "CLKGATE_X2", "CLKGATE_X4", "CLKGATE_X8",
                "CLKGATETST_X1", "CLKGATETST_X2", "CLKGATETST_X4",
                "CLKGATETST_X8", "DFFRS_X1", "DFFRS_X2",
                "DLH_X1", "DLH_X2", "DLL_X1", "DLL_X2", "TLAT_X1",
                "TBUF_X1", "TBUF_X2", "TBUF_X4", "TBUF_X8", "TBUF_X16",
                "TINV_X1",
            ],
            "enforcement": "A consumer that elaborates a netlist containing any "
                           "of these MUST report the cell as an unmodelled black "
                           "box and degrade its verdict. Post-scan GLS and "
                           "post-scan LEC are NOT ASSESSABLE on this node from "
                           "the vendored collateral -- that is different from, "
                           "and must never be reported as, a clean run.",
        },
        # No `yosys_io` entry, and that absence is DELIBERATE: FreePDK45 ships no
        # I/O pad library. The dummy pad LEFs in OpenROAD's test tree carry
        # geometry and PDN shapes only -- no Liberty, no behavioural model -- so
        # there is no module to bridge and no PAD->IN input bridge can be
        # declared. Emitting an empty io profile here would read downstream as
        # "checked, nothing to do" rather than "this node has no I/O models".
        "provenance": (
            "OpenROAD test/Nangate45/work_around_yosys/cells.v -- behavioural "
            "Verilog for the NangateOpenCellLibrary standard cells. The name "
            "says it: this is a Yosys WORKAROUND file, not a signoff "
            "simulation library, which is why its coverage is partial."
        ),
    },
}


def _resolve_functional_cell_models(params, pinned):
    """Bind a pinned functional HDL model to its node-owned read options."""
    pdk = str(params.get("pdk") or "").lower()
    node = next((name for name in _FUNCTIONAL_MODEL_PROFILES
                 if pdk.startswith(name)), None)
    profile = _FUNCTIONAL_MODEL_PROFILES.get(node, {})
    yosys_profile = profile.get("yosys", {})
    reference = params.get("functional_cell_model_reference")
    source = "caller_supplied" if reference is not None else "pdk_default"
    if reference is None:
        reference = yosys_profile.get("reference")
    simulation_references = params.get("functional_simulation_model_references")
    if simulation_references is None:
        simulation_references = (profile.get("iverilog") or {}).get("references")
    if reference is None and simulation_references is None:
        return None, "none", []
    if not isinstance(reference, str) or not reference:
        return None, source, [
            "functional_cell_model_reference must name a pinned reference"
        ]

    model = pinned.get(reference) if reference is not None else None
    if not isinstance(model, dict):
        return None, source, [
            "functional cell-model reference is missing or unpinned: " + reference
        ]
    defines = params.get("functional_cell_model_defines")
    if defines is None:
        defines = yosys_profile.get("defines", [])
    safe_define = re.compile(
        r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_+./:-]*)?")
    if not isinstance(defines, list) or not all(
            safe_define.fullmatch(str(item)) for item in defines):
        return None, source, [
            "functional_cell_model_defines contains an unsafe token"
        ]
    result = {
        "yosys_model": {
            **model,
            "defines": [str(item) for item in defines],
        },
        "provenance": {
            "reference": reference,
            "basis": profile.get("provenance", "caller supplied"),
        },
    }

    if simulation_references is not None:
        if not isinstance(simulation_references, list) or not simulation_references:
            return None, source, [
                "functional_simulation_model_references must be a non-empty list"
            ]
        missing = [str(item) for item in simulation_references
                   if not isinstance(pinned.get(str(item)), dict)]
        if missing:
            return None, source, [
                "functional simulation model reference is missing or unpinned: "
                + ", ".join(missing)
            ]
        simulation_defines = params.get("functional_simulation_model_defines")
        if simulation_defines is None:
            simulation_defines = (profile.get("iverilog") or {}).get("defines", {})
        safe_name = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
        if not isinstance(simulation_defines, dict) or not all(
                safe_name.fullmatch(str(key))
                and (value is None or re.fullmatch(r"[A-Za-z0-9_+./:-]*", str(value)))
                for key, value in simulation_defines.items()):
            return None, source, [
                "functional_simulation_model_defines contains an unsafe token"
            ]
        result["iverilog_model"] = {
            "files": [
                {"reference": str(item), **pinned[str(item)]}
                for item in simulation_references
            ],
            "defines": dict(simulation_defines),
        }

    io_references = (profile.get("yosys_io") or {}).get("references")
    if io_references:
        missing = [str(item) for item in io_references
                   if not isinstance(pinned.get(str(item)), dict)]
        if missing:
            return None, source, [
                "Yosys IO hierarchy model reference is missing or unpinned: "
                + ", ".join(missing)
            ]
        result["yosys_io_hierarchy"] = {
            "files": [
                {"reference": str(item), **pinned[str(item)]}
                for item in io_references
            ],
            "defines": list((profile.get("yosys_io") or {}).get("defines", [])),
            "input_bridges": list(
                (profile.get("yosys_io") or {}).get("input_bridges", [])),
        }

    return result, source, []


def _view_defines_cell(path, cell):
    if not isinstance(path, str) or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as source:
            text = source.read()
    except OSError:
        return False
    escaped = re.escape(cell)
    # LIBERTY ACCEPTS THE CELL NAME QUOTED **OR** BARE, and the two open PDKs
    # happen to disagree:
    #     sky130    cell ("sky130_fd_sc_hd__clkbuf_1") {
    #     nangate45 cell (CLKBUF_X1) {
    # This predicate used to require the quotes. That made it a sky130-shaped
    # assumption wearing the costume of a syntax check: on nangate45 it returned
    # False for EVERY cell in a perfectly valid Liberty, so clock-buffer
    # verification could never pass and CTS failed closed. The damage is the
    # misdirection -- the report says the library is missing its clock buffers,
    # which points the reader at the PDK instead of at this regex.
    liberty = r'(?m)^\s*cell\s*\(\s*(?:"' + escaped + r'"|' + escaped + \
              r')\s*\)\s*\{'
    return (
        re.search(r"(?m)^MACRO\s+" + escaped + r"\s*$", text) is not None
        or re.search(liberty, text) is not None
    )


def _resolve_clock_buffers(params, refs):
    explicit = params.get("clock_buffers")
    pdk = str(params.get("pdk") or "").lower()
    node = next((name for name in _CTS_PROFILES if pdk.startswith(name)), None)
    profile = _CTS_PROFILES.get(node, {})
    if explicit is not None:
        cells, source = explicit, "caller_supplied"
    elif profile:
        cells, source = profile["clock_buffers"], "pdk_default"
    else:
        return None, None, "none", {}, []

    problems = []
    if not isinstance(cells, list) or not cells:
        return None, None, source, {}, [
            "clock_buffers must be a non-empty list of cell masters"
        ]
    cells = [str(cell) for cell in cells]
    if any(not cell for cell in cells) or len(set(cells)) != len(cells):
        problems.append("clock_buffers must contain unique non-empty cell masters")

    root = params.get("root_buffer_cell")
    if root is None:
        root = profile.get("root_buffer_cell")
    if not isinstance(root, str) or not root:
        problems.append("root_buffer_cell is required")
    elif root not in cells:
        problems.append("root_buffer_cell must be a member of clock_buffers")

    view_paths = []
    stdcell_lef = refs.get("stdcell_lef")
    if stdcell_lef:
        view_paths.append(("stdcell_lef", stdcell_lef))
    for key, path in sorted(refs.items()):
        if key == "liberty" or key.startswith("liberty_"):
            view_paths.append((key, path))
    if not stdcell_lef:
        problems.append("clock_buffers require a bound stdcell_lef")
    if not any(key == "liberty" or key.startswith("liberty_")
               for key in refs):
        problems.append("clock_buffers require at least one bound core Liberty view")

    missing_by_view = {}
    for key, path in view_paths:
        missing = [cell for cell in cells if not _view_defines_cell(path, cell)]
        if missing:
            missing_by_view[key] = missing
    if missing_by_view:
        problems.append("clock buffer masters missing from bound views: %s"
                        % json.dumps(missing_by_view, sort_keys=True))

    evidence = {
        "verified_views": [key for key, _path in view_paths],
        "all_cells_present_in_every_view": not missing_by_view,
        "provenance": profile.get("_provenance", {}),
    }
    return cells, root, source, evidence, problems


def _magic_density_window_size(active_text, step, span):
    """Account for the checker's prorated tenth row and column."""
    totals = set(re.findall(
        r"atotal\s*=\s*([0-9.]+)\s*\+\s*([0-9.]+)\s*\*\s*locxfrac"
        r"\s*\+\s*([0-9.]+)\s*\*\s*locyfrac"
        r"\s*\+\s*locxfrac\s*\*\s*locyfrac", active_text))
    if len(totals) != 1:
        return None
    base, edge_x, edge_y = map(float, next(iter(totals)))
    if base != span * span or edge_x != span or edge_y != span:
        return None
    return step * (span + 1)


def _parse_magic_density_rules(path):
    """Extract metal-density windows from a pinned Open_PDKs checker.

    The binding stores the values, but the producer must not independently encode
    them: otherwise a PDK update can change the checker while this generator keeps
    emitting stale limits. Fail closed unless the source contains one unambiguous
    step size, aggregation span, and min/max pair for every MET1..MET5 layer.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as source:
            text = source.read()
    except OSError:
        return None

    # Open_PDKs keeps older checker examples as full-line comments. Exclude
    # comments before extracting policy so retired values cannot make a valid,
    # pinned checker look ambiguous.
    active_text = "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )
    step_matches = set(re.findall(
        r"box size\s+([0-9.]+)um\s+\1um", active_text))
    span_matches = set(re.findall(
        r"for w in range\(y,\s*y \+ ([0-9]+)\)", active_text))
    if len(step_matches) != 1 or len(span_matches) != 1:
        return None
    step = float(next(iter(step_matches)))
    span = int(next(iter(span_matches)))
    if step <= 0 or span <= 0:
        return None

    layers = {}
    for number in range(1, 6):
        variable = "met%daccum" % number
        match = re.search(
            r"if\s+%s\s*<\s*([0-9.]+):.*?"
            r"elif\s+%s\s*>\s*([0-9.]+):" % (variable, variable),
            active_text,
            re.DOTALL,
        )
        if match is None:
            return None
        layers["met%d" % number] = {
            "minimum": float(match.group(1)),
            "maximum": float(match.group(2)),
        }

    window = _magic_density_window_size(active_text, step, span)
    if window is None:
        return None
    return {
        "scope": "terminal",
        "window_um": {
            "width": window,
            "height": window,
            "measurement_step": step,
        },
        "layers": layers,
        "terminal_policy": {
            "layers_must_be_exhaustive": True,
            "every_maximum_window_must_pass": True,
            "zero_fill_induced_shorts": True,
            "zero_fill_induced_opens": True,
        },
    }


def _density_terminal_policy(params):
    """Return node-owned density severity.

    THREE states, not two. The original code was binary -- sky130 advisory, every
    other node hard -- which is fail-closed and therefore safe, but it cannot
    express the case where a node publishes NO density rule at all. Reporting
    "hard minimum-density violation" against a node that defines no minimum is a
    fabricated limit, and fabricating a limit is the same class of defect as
    dropping one. So a node whose `density_fill` capability is `not_applicable`
    (FreePDK45/nangate45 publishes no pattern-density rules at all) is
    dispositioned `not_applicable`, and the metal-fill stage reports
    `not_applicable` rather than inventing a pass or a fail.

    An UNKNOWN node still defaults hard -- absence of a profile is not evidence
    of absence of a rule.
    """
    pdk = str(params.get("pdk") or params.get("node") or "").strip().lower()
    capability = _capability_state(pdk, "density_fill")
    if pdk.startswith("sky130"):
        minimum = {
            "severity": "advisory",
            "disposition": "not_gating",
            "gating": False,
            "basis": "mX.pd.1 RR/A/AL recommended CMP guidance; met5 has no published minimum-density rule",
        }
    elif capability == "not_applicable":
        minimum = {
            "severity": "not_applicable",
            "disposition": "not_assessable",
            "gating": False,
            "basis": "the node publishes no pattern-density rule, so there is no "
                     "minimum to measure against; see capabilities.density_fill",
        }
    else:
        minimum = {
            "severity": "hard",
            "disposition": "gating",
            "gating": True,
            "basis": "fail_closed_default_until_the_PDK_profile_declares_otherwise",
        }
    maximum = {
        "severity": "hard",
        "disposition": "gating",
        "gating": True,
        "basis": "maximum-density overage is always a hard fill gate",
    }
    if capability == "not_applicable" and not pdk.startswith("sky130"):
        maximum = {
            "severity": "not_applicable",
            "disposition": "not_assessable",
            "gating": False,
            "basis": "the node publishes no pattern-density rule, so there is no "
                     "maximum to measure against; see capabilities.density_fill",
        }
    return {
        "minimum_density": minimum,
        "maximum_density": maximum,
        "fill_induced_shorts": {
            "severity": "hard", "disposition": "gating", "gating": True,
        },
        "fill_induced_opens": {
            "severity": "hard", "disposition": "gating", "gating": True,
        },
    }


def _resolve_density_windows(params, refs):
    """Resolve the binding's `density_windows` block.

    Precedence mirrors routing_layers/tool_policy: an explicit caller
    `density_windows` wins (`caller_supplied`); else a known-node profile is
    applied (`pdk_default`), citing the pinned `density_rules` reference when
    present in `refs`; an unknown node emits NOTHING (`none`) -- never fabricated,
    so the metal-fill stage then fails closed rather than dispositioning against a
    made-up window.
    """
    explicit = params.get("density_windows")
    if isinstance(explicit, dict) and explicit:
        return dict(explicit), "caller_supplied"
    density_ref = refs.get("density_rules")
    if not density_ref or not os.path.isfile(density_ref):
        return None, "none"
    windows = _parse_magic_density_rules(density_ref)
    info = _hash(density_ref)
    if windows is None or info is None:
        return None, "none"
    windows["terminal_policy"].update(_density_terminal_policy(params))
    windows["provenance"] = {
        "source_reference": "density_rules",
        "source_path": density_ref,
        "source_sha256": info["sha256"],
        "source_bytes": info["bytes"],
        "open_pdks_commit": params.get("version"),
        "extraction": "parsed_from_pinned_magic_checker",
    }
    return windows, "pdk_default"


def _lef_routing_layers(path):
    """Ordered list of TYPE ROUTING layer names in a tech LEF, or None if unreadable.

    Order is bottom-to-top as declared in the LEF, which is the stack order.
    """
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return None
    layers, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^LAYER\s+(\S+)", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"^TYPE\s+(\w+)", line)
        if m and current is not None:
            if m.group(1).upper() == "ROUTING":
                layers.append(current)
            current = None
    return layers


def _lef_vias(path):
    """Return fixed VIA names declared by a tech LEF, or None if unreadable."""
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as stream:
            return sorted(set(re.findall(r"^\s*VIA\s+(\S+)", stream.read(), re.M)))
    except OSError:
        return None


def _resolve_pdn_fixed_vias(params, refs):
    explicit = params.get("fixed_vias")
    if explicit is not None:
        vias, source = list(explicit), "caller_supplied"
    else:
        pdk = str(params.get("pdk") or "").lower()
        node = next((name for name in _PDN_PROFILES if pdk.startswith(name)), None)
        if node is None:
            return [], "none", []
        vias, source = list(_PDN_PROFILES[node]["fixed_vias"]), "pdk_default"
    available = _lef_vias(refs.get("tech_lef"))
    problems = []
    if available:
        unknown = sorted(set(vias) - set(available))
        if unknown:
            problems.append("fixed_vias absent from bound tech LEF: %s" %
                            ", ".join(unknown))
    return vias, source, problems


def _pdn_policy_problems(params, policy):
    pdk = str(params.get("pdk") or "").lower()
    known = any(pdk.startswith(name) for name in _PDN_PROFILES)
    pdn = policy.get("pdn") if isinstance(policy, dict) else None
    if not isinstance(pdn, dict):
        return ["tool_policy.pdn is missing"] if known else []
    settings = pdn.get("settings", pdn)
    if not isinstance(settings, dict):
        return ["tool_policy.pdn.settings must be an object"]
    stack = params.get("metal_stack")
    rows = stack.get("layers") if isinstance(stack, dict) else None
    allowed = {str(row.get("name")) for row in (rows or [])
               if isinstance(row, dict) and row.get("name")}
    if not allowed:
        return ["PDN policy cannot be checked without metal_stack.layers"]
    layer_keys = {"layer", "layers", "ongrid", "min_width_layers",
                  "connect_to_pad_layers", "obstructions", "pins"}
    used = set()

    def walk(node, key=None):
        if isinstance(node, dict):
            for child_key, value in node.items():
                walk(value, child_key)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif key in layer_keys and isinstance(node, str):
            used.add(node)

    walk(settings)
    unknown = sorted(used - allowed)
    return (["PDN policy references layers absent from metal_stack: %s" %
             ", ".join(unknown)] if unknown else [])


def _resolve_routing_layers(params, refs):
    """Resolve the binding's `routing_layers` block.

    Precedence mirrors tool_policy: an explicit caller `routing_layers` wins, else the
    node profile is applied. Either way every named layer is cross-checked against the
    tech LEF's TYPE ROUTING set, so a fabricated or mistyped layer name fails closed
    instead of reaching a stage as a silent no-op.

    Returns (layers_or_None, source, problems). `source` is `caller_supplied`,
    `pdk_default`, or `none`; `problems` is a list of human-readable strings (non-empty
    means the block is NOT trustworthy and must fail the binding).
    """
    explicit = params.get("routing_layers")
    if isinstance(explicit, dict) and explicit:
        layers, source = dict(explicit), "caller_supplied"
    else:
        pdk = str(params.get("pdk") or "").lower()
        node = next((n for n in _ROUTING_PROFILES if pdk.startswith(n)), None)
        if node is None:
            return None, "none", []  # unknown node: surface it, never fabricate.
        layers, source = dict(_ROUTING_PROFILES[node]), "pdk_default"

    problems = []
    missing_keys = [k for k in _ROUTING_LAYER_KEYS if not layers.get(k)]
    if missing_keys:
        problems.append("routing_layers missing key(s): %s" % ", ".join(missing_keys))

    lef = refs.get("tech_lef")
    available = _lef_routing_layers(lef)
    # An EMPTY routing set is unverifiable, not contradicted: a LEF we cannot read and
    # a LEF that declares no LAYER ... TYPE ROUTING look identical from here, and
    # treating empty as authoritative would reject every correct layer name.
    if not available:
        layers.setdefault("_provenance", {})
        layers["_provenance"]["lef_cross_check"] = (
            "tech_lef declared no TYPE ROUTING layers at bind time; layer names NOT "
            "verified")
        return layers, source, problems

    index = {name.lower(): i for i, name in enumerate(available)}
    for key in _ROUTING_LAYER_KEYS:
        name = layers.get(key)
        if isinstance(name, str) and name.lower() not in index:
            problems.append(
                "routing_layers.%s = '%s' is not a TYPE ROUTING layer in the bound "
                "tech LEF (available: %s)" % (key, name, ", ".join(available)))

    bottom, top = layers.get("bottom_layer"), layers.get("top_layer")
    if (isinstance(bottom, str) and isinstance(top, str)
            and bottom.lower() in index and top.lower() in index):
        lo, hi = index[bottom.lower()], index[top.lower()]
        if lo > hi:
            problems.append("routing_layers.bottom_layer '%s' is above top_layer '%s'"
                            % (bottom, top))
        else:
            for key in ("wire_rc_signal_layer", "wire_rc_clock_layer"):
                name = layers.get(key)
                if isinstance(name, str) and name.lower() in index:
                    if not (lo <= index[name.lower()] <= hi):
                        problems.append(
                            "routing_layers.%s = '%s' is outside the routing range "
                            "%s-%s" % (key, name, bottom, top))

    layers.setdefault("_provenance", {})
    layers["_provenance"]["lef_cross_check"] = (
        "every layer name verified as TYPE ROUTING in %s" % lef)
    return layers, source, problems


def quick_setup(output_dir="/output", work_dir="/workdir"):
    global _OUTPUT_DIR, _WORK_DIR
    output_dir = _env_dir(output_dir, "CHIP_OUTPUT_DIR", "OUTPUT_DIR")
    work_dir = _env_dir(work_dir, "CHIP_WORK_DIR", "WORK_DIR")
    _OUTPUT_DIR, _WORK_DIR = output_dir, work_dir
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)


def _report_fmt_val(v):
    if isinstance(v, dict):
        if "value" in v:
            return (str(v["value"]) + " " + str(v.get("unit", ""))).strip()
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        if v and all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(str(x) for x in v)
        return None
    return v


def _report_kv_rows(d):
    rows = []
    for k, v in d.items():
        fv = _report_fmt_val(v)
        if fv is None or fv == "":
            continue
        rows.append("| " + str(k) + " | " + str(fv) + " |")
    return rows


def _render_report_md(r):
    tool = r.get("tool", "tool")
    status = str(r.get("status", "unknown"))
    L = ["# " + tool + " — human summary", ""]
    L.append("- **Status:** " + status.upper())
    if r.get("objective"):
        L.append("- **Objective:** " + str(r["objective"]))
    val = r.get("validation") or {}
    if isinstance(val, dict) and val.get("verdict"):
        note = (" — " + str(val["note"])) if val.get("note") else ""
        L.append("- **Verdict:** " + str(val["verdict"]) + note)
    if r.get("error"):
        L += ["", "> **Error:** " + str(r["error"])]
    for title, key in (("Key metrics", "qor_metrics"),
                       ("Results", "results"),
                       ("Signoff evidence", "signoff_evidence")):
        d = r.get(key)
        if isinstance(d, dict) and d:
            rows = _report_kv_rows(d)
            if rows:
                L += ["", "## " + title, "", "| Metric | Value |", "| --- | --- |"] + rows
    tu = r.get("tools_used")
    if isinstance(tu, list) and tu:
        names = []
        for t in tu:
            if isinstance(t, dict):
                names.append((str(t.get("name", "?")) + " " + str(t.get("version", ""))).strip())
            else:
                names.append(str(t))
        L += ["", "## Tools", "", ", ".join(names)]
    prov = r.get("provenance") or {}
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        L += ["", "_Runtime: " + str(prov["runtime_s"]) + " s_"]
    L += ["", "_Full machine-readable envelope: `common_design_envelope.json`._", ""]
    return "\n".join(L)


def _write_report_md(results):
    path = os.path.join(_OUTPUT_DIR, "REPORT.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_report_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def _organize_output():
    """Split the flat /output dir into the skill's results/reports/logs layout,
    in-container, so every run is born conformant (no external post-processing).

    - final_results.json stays at the attempt root (downstream + skill expect it).
    - reports/  <- *.rpt, *.md (REPORT/EXECUTIVE_SUMMARY/TOOL_REPORT), *_report.json, *.csv
    - logs/     <- *.log, *.tcl, *.ys, *.sp, *.sh, *.do, run_command.txt, *.txt
    - results/  <- everything else (*.def, *.spef, netlists, *.lef, *.lib, *.gds,
                  *.sdf, *.upf, *.sv, *.py, data *.json, ...)  == next-stage inputs
    Idempotent: re-running finds only final_results.json + the 3 subdirs at root."""
    root = _OUTPUT_DIR
    for d in ("results", "reports", "logs"):
        os.makedirs(os.path.join(root, d), exist_ok=True)

    def _classify(name):
        if name.startswith("."):
            return None
        low = name.lower()
        if low in ("common_design_envelope.json", "final_results.json", "summary.md"):
            return None
        if (low.endswith(".rpt") or low.endswith(".md")
                or low.endswith("_report.json") or low == "verify_report.json"
                or low.endswith(".csv")):
            return "reports"
        if (low.endswith((".log", ".tcl", ".ys", ".sp", ".sh", ".do"))
                or low == "run_command.txt" or low.endswith(".txt")):
            return "logs"
        return "results"

    for entry in list(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isfile(full):
            continue
        dest = _classify(entry)
        if dest is None:
            continue
        target = os.path.join(root, dest, entry)
        try:
            if os.path.exists(target):
                os.remove(target)
            os.replace(full, target)
        except Exception as _e:
            print("[" + str(TOOL) + "] organize: could not move " + entry + ": " + str(_e), flush=True)



def _render_summary_md(r):
    """Read-me-first summary for the stage-version root: what was done, the verdict,
    key results, insights/caveats, provenance, and where to find detail. Built from
    the Common Design Envelope the tool already produced."""
    tool = r.get("tool", "tool")
    status = str(r.get("status", "unknown"))
    val = r.get("validation") or {}
    verdict = str(val.get("verdict", "")) if isinstance(val, dict) else ""
    L = ["# " + tool + " \u2014 run summary", ""]
    head = "**" + status.upper() + "**"
    if verdict:
        head += " \u00b7 verdict: **" + verdict + "**"
    L += [head, ""]
    if r.get("objective"):
        L += ["## What was done", "", str(r["objective"]), ""]
    tu = r.get("tools_used")
    if isinstance(tu, list) and tu:
        names = []
        for t in tu:
            if isinstance(t, dict):
                names.append((str(t.get("name", "?")) + " " + str(t.get("version", ""))).strip())
            else:
                names.append(str(t))
        L += ["_Tools:_ " + ", ".join(names), ""]
    if isinstance(val, dict) and val.get("note"):
        L += ["## Verdict", "", (verdict + " \u2014 " if verdict else "") + str(val["note"]), ""]
    if r.get("error"):
        L += ["> **Error:** " + str(r["error"]), ""]
    merged = {}
    for key in ("qor_metrics", "results", "signoff_evidence"):
        d = r.get(key)
        if isinstance(d, dict):
            for k, v in d.items():
                merged.setdefault(k, v)
    if merged:
        rows = _report_kv_rows(merged)
        if rows:
            L += ["## Key results", "", "| Metric | Value |", "| --- | --- |"] + rows + [""]
    insights = []
    for k in ("key_insights", "insights", "findings", "caveats", "assumptions", "notes"):
        v = r.get(k)
        if isinstance(v, list):
            insights += [str(x) for x in v if x]
        elif isinstance(v, str) and v.strip():
            insights.append(v.strip())
    if insights:
        L += ["## Key insights & caveats", ""] + ["- " + s for s in insights] + [""]
    prov = r.get("provenance") or {}
    plines = []
    if isinstance(prov, dict) and prov.get("runtime_s") is not None:
        plines.append("- Runtime: " + str(prov["runtime_s"]) + " s")
    pb = r.get("pdk_binding")
    if pb and pb != "none":
        plines.append("- PDK binding: " + (str(pb) if not isinstance(pb, dict) else str(pb.get("pdk", pb))))
    iref = r.get("inputs_ref")
    if isinstance(iref, dict) and iref:
        plines.append("- Upstream inputs: " + ", ".join(sorted(str(k) for k in iref.keys())))
    if plines:
        L += ["## Provenance", ""] + plines + [""]
    L += ["## Where to find more", "",
          "- `common_design_envelope.json` \u2014 full machine-readable envelope (this dir)",
          "- `results/` \u2014 machine artifacts consumed by the next stage",
          "- `reports/` \u2014 detailed reports (`REPORT.md`, tables, `*.rpt`)",
          "- `logs/` \u2014 verbatim tool logs and the exact run command", ""]
    return "\n".join(L)


def _write_summary_md(results):
    return  # option b: SUMMARY.md removed (tool emits REPORT.md; agent emits EXECUTIVE_SUMMARY.md)
    path = os.path.join(_OUTPUT_DIR, "SUMMARY.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render_summary_md(results))
    print("[" + str(TOOL) + "] wrote " + path, flush=True)


def save_final_results(results):
    results = _finalize_envelope(results)
    path = os.path.join(_OUTPUT_DIR, "common_design_envelope.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    try:
        _write_report_md(results)
    except Exception as _rep_e:
        print("[" + str(TOOL) + "] report generation skipped: " + str(_rep_e), flush=True)
    try:
        _write_summary_md(results)
    except Exception as _sum_e:
        print("[" + str(TOOL) + "] summary generation skipped: " + str(_sum_e), flush=True)
    try:
        _organize_output()
    except Exception as _org_e:
        print("[" + str(TOOL) + "] output organize skipped: " + str(_org_e), flush=True)


def _cde(objective, status, pdk_binding=None, signoff=None, results=None,
         assumptions=None, validation=None, error=None):
    env = {
        "tool": TOOL, "status": status, "objective": objective,
        "tools_used": [{"name": "Open_PDKs/volare", "version": "resolver-1.0.0"}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": {},
        "signoff_evidence": signoff or {}, "margin": {"method": "hash_pinning"},
        "validation": validation or {"verdict": "review"},
        "provenance": {"engine": "sha256 reference pinning"},
    }
    if error:
        env["error"] = error
    return env


def _hash(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "bytes": os.path.getsize(path)}


def _resolve_reference_path(path):
    """Resolve OpenLane/LibreLane layout aliases deterministically.

    Open_PDKs revisions may expose equivalent flow collateral under either
    ``libs.tech/openlane`` or ``libs.tech/librelane``. The caller's path remains
    first choice; only this exact directory alias is tried as a fallback.
    """
    if not isinstance(path, str):
        return path, None
    if os.path.exists(path):
        return path, None
    aliases = (
        ("libs.tech/openlane/", "libs.tech/librelane/"),
        ("libs.tech/librelane/", "libs.tech/openlane/"),
        ("libs.tech\\openlane\\", "libs.tech\\librelane\\"),
        ("libs.tech\\librelane\\", "libs.tech\\openlane\\"),
    )
    for source, target in aliases:
        if source in path:
            candidate = path.replace(source, target, 1)
            if os.path.exists(candidate):
                return candidate, {"requested_path": path, "resolved_path": candidate,
                                   "reason": "openlane_librelane_alias"}
    return path, None


def _build_binding(params):
    refs = dict(params.get("references", {}))
    if str(params.get("pdk") or "").lower().startswith("sky130"):
        io_blackbox = refs.get("io_cell_models")
        if isinstance(io_blackbox, str):
            io_dir = os.path.dirname(io_blackbox)
            refs.setdefault(
                "io_wrapper_models", os.path.join(io_dir, "sky130_ef_io.v"))
    pinned = {}
    missing = []
    resolved_refs = {}
    resolutions = {}
    for kind, path in refs.items():
        resolved_path, resolution = _resolve_reference_path(path)
        resolved_refs[kind] = resolved_path
        if resolution:
            resolutions[kind] = resolution
        info = _hash(resolved_path)
        if info is None:
            missing.append(kind)
        else:
            pinned[kind] = {"path": resolved_path, **info,
                            "version": params.get("version", "pinned")}
    # required references not provided at all
    for req in _REQUIRED:
        if req not in refs:
            missing.append(req)
    clock_buffers, root_buffer_cell, clock_buffers_source, clock_buffers_evidence, \
        clock_buffer_problems = _resolve_clock_buffers(params, resolved_refs)
    if clock_buffer_problems:
        missing.append("clock_buffers")
    policy_params = dict(params)
    policy_params["clock_buffers"] = clock_buffers
    policy_params["root_buffer_cell"] = root_buffer_cell
    tool_policy, policy_source, policy_hashes = _build_tool_policy(
        policy_params, resolved_refs)
    fixed_vias, fixed_vias_source, fixed_via_problems = _resolve_pdn_fixed_vias(
        params, resolved_refs)
    pdn_policy_problems = _pdn_policy_problems(params, tool_policy)
    if fixed_via_problems or pdn_policy_problems:
        missing.append("pdn_policy")
    routing_layers, routing_source, routing_problems = _resolve_routing_layers(
        params, resolved_refs)
    # A layer name that contradicts the tech LEF is a fabrication, not a deferral --
    # emitting it would reach a stage as a silent no-op (RSZ-0089), so fail closed.
    if routing_problems:
        missing.append("routing_layers")
    density_windows, density_source = _resolve_density_windows(params, resolved_refs)
    pad_io_terminal_mappings, pad_io_terminal_mappings_source = \
        _resolve_pad_io_terminal_mappings(params)
    functional_cell_models, functional_cell_models_source, \
        functional_cell_model_problems = _resolve_functional_cell_models(
            params, pinned)
    if functional_cell_model_problems:
        missing.append("functional_cell_models")
    capabilities, capabilities_source, capability_problems = _resolve_capabilities(
        params)
    # A malformed capability block is a fabrication risk, not a cosmetic defect:
    # a gate would read a meaningless state and resolve it however it liked.
    if capability_problems:
        missing.append("capabilities")
    fill_config = resolved_refs.get("fill_config") or resolved_refs.get("fill_rules")
    if fill_config and not density_windows:
        missing.append("density_windows")
    binding = {
        "pdk": params.get("pdk"),
        "stdcell_library": params.get("stdcell_library"),
        "corners": params.get("corners", []),
        "clock_buffers": clock_buffers,
        "clock_buffers_source": clock_buffers_source,
        "clock_buffers_evidence": clock_buffers_evidence,
        "root_buffer_cell": root_buffer_cell,
        "fixed_vias": fixed_vias,
        "fixed_vias_source": fixed_vias_source,
        "fixed_via_problems": fixed_via_problems,
        "metal_stack": params.get("metal_stack"),
        "routing_layers": routing_layers,
        "routing_layers_source": routing_source,
        "routing_layers_problems": routing_problems,
        "fill_config": fill_config,
        "density_windows": density_windows,
        "density_windows_source": density_source,
        "pad_io_terminal_mappings": pad_io_terminal_mappings,
        "pad_io_terminal_mappings_source": pad_io_terminal_mappings_source,
        "functional_cell_models": functional_cell_models,
        "functional_cell_models_source": functional_cell_models_source,
        "functional_cell_model_problems": functional_cell_model_problems,
        "capabilities": capabilities,
        "capabilities_source": capabilities_source,
        "capability_problems": capability_problems,
        "engine_class": params.get("engine_class", "oss"),
        "references": pinned,
        "tool_policy": tool_policy,
        "tool_policy_source": policy_source,
        "tool_policy_hashes": policy_hashes,
        "pdn_policy_problems": pdn_policy_problems,
        "reference_resolutions": resolutions,
    }
    return binding, sorted(set(missing))


def _resolve_pad_io_terminal_mappings(params):
    """Return node-owned pad master/pin mappings for top-level BTerm binding.

    The empty return is NOT interchangeable with "this node has no pads". It
    used to be reached by `not pdk.startswith("sky130")`, so every non-sky130
    node got `[]` with source `none`, which downstream reads as "checked, found
    nothing" -- indistinguishable from a node whose pad library genuinely has
    zero entries. The `io_pads` capability now carries that distinction
    explicitly, so the source string reports WHY the list is empty.
    """
    explicit = params.get("pad_io_terminal_mappings")
    if explicit is not None:
        return list(explicit), "caller_supplied"
    pdk = str(params.get("pdk") or "").lower()
    mappings = _PAD_IO_PROFILES.get(
        next((name for name in _PAD_IO_PROFILES if pdk.startswith(name)), None))
    if mappings is None:
        state = _capability_state(pdk, "io_pads")
        if state in ("not_applicable", "degraded", "requires_provisioning"):
            # The node was EXAMINED and declared; the emptiness is a fact about
            # the node, not an unexamined default.
            return [], "capability_%s" % state
        return [], "none"
    return [dict(entry) for entry in mappings], "pdk_default"


_PAD_IO_PROFILES = {
    "sky130": [
        {"master": "sky130_ef_io__gpiov2_pad", "pin": "PAD",
         "inst_pin_pattern": "*/PAD"},
        {"master": "sky130_ef_io__vccd_lvc_clamped_pad", "pin": "VCCD_PAD",
         "inst_pin_pattern": "*/VCCD_PAD"},
        {"master": "sky130_ef_io__vssd_lvc_clamped_pad", "pin": "VSSD_PAD",
         "inst_pin_pattern": "*/VSSD_PAD"},
        {"master": "sky130_ef_io__vddio_hvc_clamped_pad", "pin": "VDDIO_PAD",
         "inst_pin_pattern": "*/VDDIO_PAD"},
        {"master": "sky130_ef_io__vssio_hvc_clamped_pad", "pin": "VSSIO_PAD",
         "inst_pin_pattern": "*/VSSIO_PAD"},
        {"master": "sky130_ef_io__analog_esd_pad", "pin": "P_PAD",
         "inst_pin_pattern": "*/P_PAD"},
        {"master": "sky130_ef_io__analog_minesd_pad", "pin": "P_PAD",
         "inst_pin_pattern": "*/P_PAD"},
        {"master": "sky130_ef_io__analog_minesd_pad_short", "pin": "P_PAD",
         "inst_pin_pattern": "*/P_PAD"},
        {"master": "sky130_ef_io__analog_noesd_pad", "pin": "P_PAD",
         "inst_pin_pattern": "*/P_PAD"},
        {"master": "sky130_ef_io__analog_pad", "pin": "P_PAD",
         "inst_pin_pattern": "*/P_PAD"},
    ],
    # NO `nangate45` ENTRY, and that absence is load-bearing. FreePDK45 ships no
    # I/O pad library at all; the dummy pad LEFs in OpenROAD's test tree are
    # geometry/PDN only. The `io_pads` capability records that as `degraded`, so
    # the resolver returns ([], "capability_degraded") -- an empty list with a
    # stated reason, rather than an empty list that reads as "none found".
}


def _build_tool_policy(params, refs):
    """Emit the PDK's recommended tool policy (which engines + settings each flow
    stage should use). Precedence: an explicit caller `tool_policy` is passed
    through; otherwise a default is synthesized for known open PDKs. Any file
    reference the policy names is sha256-pinned for reproducibility.

    Returns (policy_dict, source, ref_hashes). `source` is `caller_supplied`,
    `pdk_default`, or `none`."""
    explicit = params.get("tool_policy")
    if explicit:
        policy, source = dict(explicit), "caller_supplied"
    else:
        policy, source = _default_tool_policy(params, refs), None
        source = "pdk_default" if policy else "none"

    # Pin every file path the policy names (settings values that exist on disk).
    ref_hashes = {}

    def _pin_paths(node, trail):
        if isinstance(node, dict):
            for k, v in node.items():
                _pin_paths(v, trail + "." + str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _pin_paths(v, trail + f"[{i}]")
        elif isinstance(node, str) and os.path.isfile(node):
            info = _hash(node)
            if info:
                ref_hashes[trail.lstrip(".")] = {"path": node, **info}

    _pin_paths(policy, "")
    return policy, source, ref_hashes


def _default_tool_policy(params, refs):
    """Synthesize the recommended tool policy for a known open PDK from the
    references already resolved. Returns {} for unknown PDKs (no fabrication).

    Covered node families:
      * sky130  (SkyWater 130 nm, sky130A/sky130B)
      * gf180mcu (GlobalFoundries 180 nm MCU)
          both ship complementary Magic + KLayout DRC decks, Netgen LVS and
          Magic extraction in the open flow.
      * nangate45 (FreePDK45 / NangateOpenCellLibrary)
          DIFFERENT SHAPE, and the difference is the whole point of this branch:
          dual-engine DRC like sky130 but with a DIFFERENT second engine pairing,
          KLayout LVS (not Netgen), and OpenRCX extraction (not Magic ext2spice).
          Deriving these from the capability profile rather than assuming the
          sky130 shape is what stops a second node inheriting sky130's engines --
          and equally stops a node being denied an engine it actually ships.
    """
    pdk = str(params.get("pdk") or "").lower()
    _families = ("sky130", "gf180", "nangate45")
    node = next((f for f in _families if pdk.startswith(f)), None)
    if node is None:
        return {}
    capabilities = _capability_profile_for(pdk)
    magicrc = refs.get("magicrc") or refs.get("magic_rcfile")
    magic_tech = refs.get("magic_tech")
    magic_settings = {"drc_euclidean": True}
    if magicrc:
        magic_settings["magicrc"] = magicrc
    if magic_tech:
        magic_settings["magic_tech"] = magic_tech
    _libtech = "libs.tech/{magic,klayout}"

    # --- DRC: engine set comes from the capability declaration, not a constant.
    drc_cap = capabilities.get("drc") or {}
    drc_engines = list(drc_cap.get("engines") or ["klayout", "magic"])
    drc_mode = drc_cap.get("mode") or "all_must_pass"
    if len(drc_engines) > 1:
        # The deck LOCATION is node-specific; only sky130/gf180 keep decks under
        # libs.tech. Asserting that layout for every multi-engine node states a
        # path that does not exist on nangate45, and a rationale citing a
        # fictitious path is worse than a vague one -- it looks verifiable.
        # The surrounding wording is held BYTE-IDENTICAL for sky130: this string
        # is covered by the parity guard, and "improving" its phrasing is a
        # silent change to the baseline node's recorded policy.
        where = drc_cap.get("deck_origin") or _libtech
        drc_rationale = (f"{node} provides complementary Magic and KLayout DRC "
                         f"decks under {where}; a complete DRC signoff requires "
                         "both engines clean")
    else:
        absent = drc_cap.get("absent_engines") or {}
        drc_rationale = (
            "%s ships a usable deck for %s only%s"
            % (node, ", ".join(drc_engines),
               ("; " + "; ".join("%s: %s" % kv for kv in sorted(absent.items())))
               if absent else ""))
    drc_settings = {engine: ({} if engine == "klayout" else magic_settings)
                    for engine in drc_engines}

    # --- LVS: sky130/gf180 use Netgen + Magic extraction; nangate45 uses a
    # KLayout LVS deck compared against the library CDL. Never assume Netgen.
    lvs_cap = capabilities.get("lvs") or {}
    lvs_engine = lvs_cap.get("engine") or "netgen"
    if lvs_engine == "netgen":
        lvs_entry = {
            "engine": "netgen",
            "mode": "must_match",
            "rationale": f"Netgen is the {node} reference LVS engine; layout netlist "
                         "extracted with Magic",
            "settings": {"magic": ({"magicrc": magicrc} if magicrc else {})},
        }
    else:
        lvs_entry = {
            "engine": lvs_engine,
            "mode": "must_match",
            "rationale": "%s has no Netgen setup; LVS runs the %s deck against the "
                         "library CDL netlist" % (node, lvs_engine),
            "settings": {lvs_engine: {
                "source_netlist": lvs_cap.get("source_netlist"),
                "cell_coverage": lvs_cap.get("cell_coverage"),
            }},
        }

    # --- Extraction: DECLARED, not inferred.
    #
    # This used to read `if "magic" in drc_engines`, using the DRC engine list as
    # a proxy for "has a usable Magic techfile". That proxy silently broke the
    # moment nangate45 correctly gained Magic as a SECOND DRC ENGINE: the node
    # flipped from OpenRCX to Magic ext2spice without a single line of
    # extraction code changing, and nothing reported an error -- it simply began
    # naming a different extractor. Two capabilities that happen to correlate on
    # the baseline node are not the same capability, so extraction now comes
    # from its own declaration and falls back to the old proxy only for nodes
    # that have not declared one.
    extraction_cap = capabilities.get("extraction") or {}
    extraction_engine = extraction_cap.get("engine")
    if extraction_engine is None:
        extraction_engine = "magic" if "magic" in drc_engines else "openrcx"
    if extraction_engine == "magic":
        extraction_entry = {
            "engine": "magic",
            "rationale": extraction_cap.get("rationale")
            or f"Magic ext2spice is the {node} open-flow extractor",
            "settings": {"magic": {"cthresh": 0, "rthresh": 0}},
        }
    else:
        extraction_entry = {
            "engine": "openrcx",
            "rationale": extraction_cap.get("rationale")
            or ("%s ships no usable Magic techfile; OpenROAD OpenRCX is "
                "the extractor, driven by the node rcx rules" % node),
            "settings": {"openrcx": {
                "rcx_rules": refs.get("rcx_rules") or refs.get("rc_tech"),
            }},
        }

    policy = {
        "drc": {
            "engines": drc_engines,
            "mode": drc_mode,
            "rationale": drc_rationale,
            "settings": drc_settings,
        },
        "lvs": lvs_entry,
        "extraction": extraction_entry,
        "physical_integrity": {
            "engine": "openroad",
            "mode": "required_checks_must_pass",
            "rationale": "OpenROAD/OpenDB provides deterministic physical-database "
                         "integrity reports; supplied signoff evidence remains "
                         "independently fail-closed",
            "settings": {},
        },
        "opendb_utilities": {
            "engine": "openroad",
            "rationale": "OpenROAD is the reference OpenDB reader, editor, and "
                         "view writer for the open physical-design flow",
            "settings": {},
        },
        "streamout_xor": {
            "engine": "klayout",
            "mode": "zero_geometric_difference",
            "rationale": "KLayout performs the independent geometric XOR between "
                         "Magic and KLayout streamout products",
            "settings": {},
        },
    }
    clock_buffers = params.get("clock_buffers")
    root_buffer_cell = params.get("root_buffer_cell")
    if clock_buffers and root_buffer_cell:
        policy["cts"] = {
            "engine": "openroad",
            "rationale": (
                "OpenROAD TritonCTS consumes only the binding-approved clock "
                "buffer set and explicit root selection"
            ),
            "settings": {
                "clock_buffer": list(clock_buffers),
                "root_buffer_cell": root_buffer_cell,
            },
        }
    pdn_profile = _PDN_PROFILES.get(node)
    if pdn_profile:
        policy["pdn"] = {
            "engine": "openroad",
            "rationale": pdn_profile["rationale"],
            "settings": json.loads(json.dumps(pdn_profile["settings"])),
        }
    # Metal fill: recommend the node fill rules config when the binding names it.
    fill_cfg = refs.get("fill_config") or refs.get("fill_rules")
    if fill_cfg:
        policy["fill"] = {
            "engine": "openroad",
            "rationale": f"OpenROAD density_fill with the {node} fill rules config; "
                         "terminal validation checks every bound metal-layer "
                         "maximum-density window and requires zero fill-induced "
                         "shorts/opens",
            "settings": {"fill_config": fill_cfg,
                         "density_windows": "binding:density_windows"},
        }
    # STA signoff corners: recommend the node's setup+hold signoff corners so every
    # STA run signs off the same corner set.
    corners = params.get("corners") or []
    if corners:
        policy["sta"] = {
            "engine": "opensta",
            "mode": "all_corners",
            "rationale": "sign off timing across the node's recommended corner set",
            "settings": {"corners": list(corners)},
        }
    # Antenna: the engine is genuinely node-specific and must match the bound
    # `antenna_rules.engine`. sky130 has no KLayout antenna deck (the ruleset is
    # the `antenna` directives inside sky130A.tech, run by Magic antennacheck);
    # nangate45 is the mirror image -- its antenna rules are the ANTENNA group
    # INSIDE the KLayout DRC deck. Recommending the wrong one is not a cosmetic
    # error: running KLayout antenna against a DRC-only deck finds zero
    # violations and reports clean.
    antenna_cap = capabilities.get("antenna") or {}
    antenna_engine = antenna_cap.get("engine")
    if antenna_engine:
        antenna_settings = {}
        if antenna_cap.get("rule_source"):
            antenna_settings["rule_source"] = antenna_cap["rule_source"]
        if antenna_cap.get("ratio") is not None:
            antenna_settings["ratio"] = antenna_cap["ratio"]
        policy["antenna"] = {
            "engine": antenna_engine,
            "mode": "zero_unwaived_violations",
            "rationale": antenna_cap.get("note")
            or ("%s antenna rules are evaluated by %s" % (node, antenna_engine)),
            "settings": {antenna_engine: antenna_settings},
        }
    return policy


def _resolve(params):
    if not params.get("pdk"):
        return _cde(objective="resolve PDK binding", status="failed",
                    error="'pdk' is required", validation={"verdict": "fail"})
    binding, missing = _build_binding(params)
    complete = not missing
    policy = binding.get("tool_policy") or {}
    routing = binding.get("routing_layers") or {}
    return _cde(
        objective=f"resolve PDK binding for {params.get('pdk')}",
        status="completed" if complete else "failed",
        pdk_binding=binding,
        results={"references_pinned": {"value": len(binding["references"]), "unit": "count"},
                 "missing_references": {"value": len(missing), "unit": "count"},
                 "tool_policy_stages": {"value": len(policy), "unit": "count"}},
        signoff={"complete": complete, "missing_references": missing,
                 "required": _REQUIRED,
                 "tool_policy_source": binding.get("tool_policy_source"),
                 "tool_policy_stages": sorted(policy.keys()),
                 "tool_policy_pinned_refs": sorted(
                     (binding.get("tool_policy_hashes") or {}).keys()),
                 "routing_layers_source": binding.get("routing_layers_source"),
                 "routing_layers": {k: routing.get(k) for k in _ROUTING_LAYER_KEYS},
                 "routing_layers_problems": binding.get("routing_layers_problems") or []},
        assumptions=["completeness measured against the required reference set; "
                     "every present reference is sha256-pinned",
                     "tool_policy carries the PDK's recommended engines + settings "
                     "per flow stage; caller-supplied policy overrides the default",
                     "routing_layers carries the signal routing range plus the "
                     "set_wire_rc signal/clock layer pair; every layer name is "
                     "cross-checked against the tech LEF's TYPE ROUTING set. An "
                     "unknown node emits no block (never fabricated) -- physical "
                     "stages then fail closed rather than no-op"],
        validation={"verdict": "pass" if complete else "fail",
                    "note": "binding complete" if complete
                    else "incomplete binding; fail closed"},
    )


def _validate(params):
    return _resolve(params)


def _switch(params):
    new, missing = _build_binding(params)
    prev = params.get("previous", {}) or {}
    prev_refs = (prev.get("references") or {})
    new_refs = new["references"]
    added = [k for k in new_refs if k not in prev_refs]
    removed = [k for k in prev_refs if k not in new_refs]
    changed = [k for k in new_refs if k in prev_refs
               and new_refs[k].get("sha256") != prev_refs[k].get("sha256")]
    orphaned = removed  # references a stage agent may still expect
    complete = not missing
    # Tool-policy diff: a node switch may recommend a different engine set per
    # stage; surface it so stage agents/reviewers see the changed recommendation.
    prev_policy = (prev.get("tool_policy") or {})
    new_policy = (new.get("tool_policy") or {})
    policy_changed = []
    for stage in sorted(set(prev_policy) | set(new_policy)):
        if prev_policy.get(stage) != new_policy.get(stage):
            policy_changed.append({
                "stage": stage,
                "was_engines": (prev_policy.get(stage) or {}).get("engines")
                or (prev_policy.get(stage) or {}).get("engine"),
                "now_engines": (new_policy.get(stage) or {}).get("engines")
                or (new_policy.get(stage) or {}).get("engine")})
    return _cde(
        objective=f"switch node to {params.get('pdk')}",
        status="completed" if complete else "failed",
        pdk_binding=new,
        results={"added": {"value": len(added), "unit": "count"},
                 "removed": {"value": len(removed), "unit": "count"},
                 "changed": {"value": len(changed), "unit": "count"},
                 "tool_policy_stages_changed": {"value": len(policy_changed),
                                                "unit": "count"}},
        signoff={"diff": {"added": added, "removed": removed, "changed": changed},
                 "orphaned_references": orphaned, "missing_references": missing,
                 "tool_policy_diff": policy_changed,
                 "tool_policy_source": new.get("tool_policy_source"),
                 "complete": complete},
        assumptions=["node switch requires zero stage-agent logic changes; only "
                     "the binding changes",
                     "a changed tool_policy recommends different engines/settings "
                     "for a stage; stage agents pick it up automatically"],
        validation={"verdict": "pass" if complete and not orphaned else "fail"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s == "resolve_binding":
        return _resolve(params)
    if s == "validate_binding":
        return _validate(params)
    if s == "switch_node":
        return _switch(params)
    return _cde(objective="pdk binding", status="failed",
                error=f"unknown scenario '{s}'", validation={"verdict": "fail"})


# --- attempt capture (BEGIN) -- vendored by catalog/migrate_attempt_capture.py
# Records WHAT THE STAGE WAS ASKED TO DO alongside what it measured, so that an
# attempt chain (stage.1 -> stage.N) can be mined for which knob actually moved the
# residual. Without it a CDE says the residual fell from 102 to 9 but not why, and
# the causal knowledge is lost the moment the run ends.
#
# Hooked as wrappers rather than edits to dispatch()/save_final_results() so this
# migration never has to understand tool-specific code.
_ATTEMPT_CAPTURE = {}

#: Substrings that mark a value as secret. Envelopes are committed to git, so a
#: credential that reaches one is durable and public. Narrow on purpose: a broad
#: "key" match would redact legitimate EDA parameters (`clock_key`, `map_key`).
_CAPTURE_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key",
                         "apikey", "credential", "private_key", "auth")

_CAPTURE_MAX_STR = 512
_CAPTURE_MAX_SEQ = 64
_CAPTURE_MAX_DEPTH = 6


def _capture_digest(obj):
    import hashlib
    import json as _json
    try:
        blob = _json.dumps(obj, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = repr(obj)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _capture_head(value, limit=120):
    """Truncate an excerpt on a LINE boundary so it never ends mid-token.

    A raw byte slice cuts wherever the count lands, and 120 bytes into this
    campaign's RTL lands inside `campaigns/.../spec.3/reports/bsum16.md`, leaving
    `campaigns/.../spec.3/repor`. The publication citation scanner reads any
    path-shaped string as a citation, so the excerpt turns a real reference into a
    dangling one and blocks the whole publication transaction -- a provenance
    failure manufactured entirely by the truncation.
    """
    if len(value) <= limit:
        return value
    window = value[:limit]
    cut = window.rfind("\n")
    if cut <= 0:
        cut = max(window.rfind(" "), window.rfind("\t"))
    if cut <= 0:
        # One unbroken token wider than the window: nothing to cut back to.
        return window
    return window[:cut]


def _capture_normalize(value, depth=0):
    """Bound the size of a captured value without losing change-detection.

    Elision keeps a sha256 of the ELIDED PART, so a parameter that changed between
    two attempts still shows a different hash even when its content is too big to
    store. Silently dropping it would make the delta look empty -- i.e. would
    report "nothing changed" for a run that changed something.
    """
    if depth > _CAPTURE_MAX_DEPTH:
        return {"_elided": "depth", "sha256": _capture_digest(value)}
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _CAPTURE_MAX_STR:
            return {"_elided": "str", "chars": len(value),
                    "sha256": _capture_digest(value),
                    "head": _capture_head(value)}
        return value
    if isinstance(value, dict):
        out = {}
        for key in list(value)[:_CAPTURE_MAX_SEQ]:
            low = str(key).lower()
            if any(hint in low for hint in _CAPTURE_SECRET_HINTS):
                out[key] = {"_redacted": "secret-like key"}
                continue
            out[key] = _capture_normalize(value[key], depth + 1)
        if len(value) > _CAPTURE_MAX_SEQ:
            out["_elided"] = {"keys": len(value), "sha256": _capture_digest(value)}
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > _CAPTURE_MAX_SEQ:
            return {"_elided": "list", "len": len(value),
                    "sha256": _capture_digest(value),
                    "head": [_capture_normalize(v, depth + 1) for v in value[:8]]}
        return [_capture_normalize(v, depth + 1) for v in value]
    return {"_elided": type(value).__name__, "sha256": _capture_digest(value)}


def _capture_params(params):
    import datetime
    if not isinstance(params, dict):
        return
    intent = params.get("attempt_intent")
    _ATTEMPT_CAPTURE.clear()
    _ATTEMPT_CAPTURE.update({
        "schema": "attempt-capture/1",
        # Hash the RAW params, before elision -- see _capture_normalize.
        "parameters_sha256": _capture_digest(params),
        "parameters": _capture_normalize(params),
        "intent": intent or None,
        "intent_missing": not bool(intent),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


try:
    _dispatch_undecorated = dispatch

    def dispatch(params):  # noqa: F811
        _capture_params(params)
        return _dispatch_undecorated(params)
except NameError:  # pragma: no cover - a tool without dispatch()
    pass


try:
    _save_final_results_undecorated = save_final_results

    def save_final_results(results):  # noqa: F811
        if isinstance(results, dict):
            # Fall back to the fail-closed path's own copy: run.py sets
            # `input_parameters` when it fails BEFORE dispatch, which is exactly
            # when _ATTEMPT_CAPTURE would otherwise be empty.
            if not _ATTEMPT_CAPTURE and isinstance(
                    results.get("input_parameters"), dict):
                _capture_params(results["input_parameters"])
            if _ATTEMPT_CAPTURE:
                results.setdefault("attempt_capture", dict(_ATTEMPT_CAPTURE))
        return _save_final_results_undecorated(results)
except NameError:  # pragma: no cover - a tool without save_final_results()
    pass
# --- attempt capture (END) ---


# --- magic PDK_ROOT env (BEGIN) -- vendored by catalog/migrate_magic_env.py
# sky130A.magicrc (and the open_pdks family generally) resolves its techfile via
# $PDK_ROOT and falls back to the ORIGINAL BUILD MACHINE's absolute path when
# that variable is unset. A tool that does not set PDK_ROOT therefore runs Magic
# with NO TECHNOLOGY LOADED -- and Magic does not fail: it reads no geometry,
# extracts an empty cell, reports zero violations and EXITS 0. That is a silent
# false clean on a mandatory tapeout gate, which is the worst value these tools
# can emit. Setting PDK_ROOT is what makes the vendor magicrc work unmodified.
def _magic_pdk_root(techfile=None, rcfile=None, params=None):
    """Derive a PDK_ROOT that makes the vendor magicrc resolve, or None.

    Precedence: explicit caller param > already-set environment > derived from
    the techfile/rcfile path. Never guesses: a derived root is returned only
    when the expected <root>/<variant>/libs.tech/magic directory really exists,
    so a wrong layout yields None (and the caller fails closed) rather than a
    plausible-but-wrong path.
    """
    if params:
        explicit = params.get("pdk_root") or (
            (params.get("pdk_binding") or {}).get("pdk_root")
            if isinstance(params.get("pdk_binding"), dict) else None)
        if explicit and os.path.isdir(str(explicit)):
            return str(explicit)
    env_root = os.environ.get("PDK_ROOT")
    if env_root and os.path.isdir(env_root):
        return env_root
    for path in (techfile, rcfile):
        if not path:
            continue
        p = os.path.abspath(str(path))
        # <root>/<variant>/libs.tech/magic/<file>  ->  climb four levels.
        magic_dir = os.path.dirname(p)
        libs_tech = os.path.dirname(magic_dir)
        variant = os.path.dirname(libs_tech)
        root = os.path.dirname(variant)
        if (os.path.basename(magic_dir) == "magic"
                and os.path.basename(libs_tech) == "libs.tech"
                and os.path.isdir(os.path.join(variant, "libs.tech", "magic"))
                and os.path.isdir(root)):
            return root
    return None


def _magic_env(techfile=None, rcfile=None, params=None, extra=None):
    """Environment for a Magic subprocess, with PDK_ROOT resolved."""
    env = dict(os.environ)
    env.setdefault("MAGTYPE", "mag")
    root = _magic_pdk_root(techfile, rcfile, params)
    if root:
        env["PDK_ROOT"] = root
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
# --- magic PDK_ROOT env (END) ---
