#!/usr/bin/env python3
"""cde_progress.py -- canonical Common Design Envelope PROGRESS contract.

WHY THIS EXISTS
---------------
Every chip-* tool authors its ``results`` block freeform. A 2026-08-21 audit of
129 real campaign envelopes found **0% key stability**: across all 18 multi-attempt
stage series, not one shared a single common ``results`` key between its own
attempts, and ``verdict`` was absent from 79/129 (with six spellings plus one
free-text sentence in the enum field).

That makes any metric-driven decision -- effort budgets, stall/ROI roll-off,
cross-run QoR trajectories -- unimplementable, because there is no field a
consumer can reliably read.

This module fixes that WITHOUT forcing 42 tools to agree on a schema. It maps
each stage's freeform output onto ONE stable, always-present block:

    "progress": {
      "schema": "cde-progress/1",
      "metric_id": "reachable_unhit",     # what was measured
      "residual": 2.0,                    # DISTANCE TO GATE CLOSURE
      "closes_at": 0,                     # residual == closes_at  <=>  gate closes
      "direction": "minimize",
      "metric_kind": "continuous",
      "unit": "points",
      "source": "qor_metrics.holes",      # where it was actually read from
      "denominator": 45,                  # population, for Goodhart detection
      "verdict_normalized": "fail",       # controlled enum, always present
      "gate_closed": false,
      "alignment": "ok"                   # or "metric_defect" -- see below
    }

So a consumer reads ``progress.residual`` for EVERY stage. Per-stage variation
lives here, in one reviewed registry, instead of in 42 tool implementations.

THE CLOSURE INVARIANT
---------------------
A progress metric is only appropriate if it is the RESIDUAL OF THE STAGE'S OWN
GATE -- the distance to the closure condition already written in the task's
validationRequirements. That makes appropriateness machine-checkable rather than
a matter of opinion::

    residual == closes_at   <=>   gate closes

``alignment`` reports that check on every envelope:

  * ``ok``            -- invariant holds
  * ``metric_defect`` -- gate passed with residual != closes_at, or gate failed
                         with residual == closes_at. This is a defect in the
                         METRIC (or in the verdict), not in the design, and must
                         be raised against the stage owner.

This is not hypothetical: the audit found ``<myDesign>/lec.11`` reporting
``verdict: partial_pass`` / ``status: completed`` while carrying
``eqy_verdict: FAIL`` and 695 of 1455 partitions unproved. The residual (695) was
more truthful than the verdict. ``alignment`` catches exactly that.

GOODHART GUARD
--------------
``denominator`` records the measured population alongside the residual. A
residual that improves because the POPULATION SHRANK (e.g. reclassifying a
reachable coverage point as structurally unreachable) is not progress. Consumers
compare denominators across attempts and treat a moving population as a metric
defect.

CONTRACT NOTES
--------------
* Purely ADDITIVE and non-destructive: it never edits ``results``/``qor_metrics``
  and never overwrites an explicit ``progress`` block a tool authored itself.
* Flow-position scope is explicit. A metric that is not physically actionable at
    one flow position remains visible under ``deferred_family_metrics`` but cannot
    enter that position's active gate residual. The downstream obligation is not
    waived; ``validate_deferral_closure.py`` proves that it is eventually gated.
* Never raises. A stage with no recoverable residual emits
  ``residual: null`` + ``metric_kind: "unavailable"`` -- an honest "no metric
  here" that consumers must treat as NOT ITERABLE, rather than a fabricated zero.
* Binary-gate stages (equivalence proofs) declare ``metric_kind: "binary"``: they
  do not get "closer", so they are excluded from stall/ROI reasoning by design.

Canonical copy: catalog/tools/cde_progress.py -- vendored into each tool build
context by catalog/migrate_cde_progress.py. Edit the canonical copy, then re-run
the migration.
"""

import argparse
import json
import os
import re
import sys

SCHEMA = "cde-progress/1"

# Controlled verdict vocabulary. Everything the fleet actually emits maps here.
VERDICT_PASS = "pass"
VERDICT_PASS_WITH_CAVEATS = "pass_with_caveats"
VERDICT_FAIL = "fail"
VERDICT_NOT_ASSESSABLE = "not_assessable"
VERDICT_ERROR = "error"

# Verdicts that mean the gate is FULLY closed. A caveated pass is deliberately
# excluded: its caveat is unfinished work, so the stage stays iterable.
CLOSING_VERDICTS = (VERDICT_PASS,)

_VERDICT_MAP = {
    "pass": VERDICT_PASS,
    "passed": VERDICT_PASS,
    "ok": VERDICT_PASS,
    "equivalent": VERDICT_PASS,
    "clean": VERDICT_PASS,
    # A caveated pass is NOT an unconditional closure: the caveat is exactly the
    # residual the effort framework must keep working on. Treating it as `pass`
    # would let a stage stop iterating while its gate is still open.
    "pass_with_caveats": VERDICT_PASS_WITH_CAVEATS,
    "pass_with_caveat": VERDICT_PASS_WITH_CAVEATS,
    "conditional_pass": VERDICT_PASS_WITH_CAVEATS,
    "partial_pass": VERDICT_FAIL,   # partial closure is NOT closure
    "fail": VERDICT_FAIL,
    "failed": VERDICT_FAIL,
    "not_equivalent": VERDICT_FAIL,
    "violation": VERDICT_FAIL,
    "not_assessable": VERDICT_NOT_ASSESSABLE,
    "unassessable": VERDICT_NOT_ASSESSABLE,
    "inconclusive": VERDICT_NOT_ASSESSABLE,
    "unknown": VERDICT_NOT_ASSESSABLE,
    "skipped": VERDICT_NOT_ASSESSABLE,
    "review": VERDICT_NOT_ASSESSABLE,
    "flag": VERDICT_NOT_ASSESSABLE,
    "error": VERDICT_ERROR,
    "invalid": VERDICT_ERROR,
    "crash": VERDICT_ERROR,
}

# Stage aliases: CDE `stage` values and on-disk stage-dir names -> registry key.
#
# SOURCE OF TRUTH: catalog/policy/stage-roles.json. Checks L2/L3 of
# catalog/validate_stage_naming.py require every canonical token to resolve to
# its role's progress_key, and every registry alias to resolve to SOMETHING. An
# unaliased spelling returns None, which degrades the stage to
# `metric_kind: unavailable` -- downstream that is indistinguishable from a clean
# gate, so a missing alias is a SILENT PASS, not a loud gap. The registry is not
# imported here because this module ships inside tool images that do not carry it.
_STAGE_ALIASES = {
    "functional_verification": "funcverif",
    "functional-verification": "funcverif",
    "func_verif": "funcverif",
    "funcsim": "funcverif",
    "simulation": "funcverif",
    # `verification` is what the functional-verification tool stamped on several
    # real runs. It is deliberately spelled out rather than left to suffix
    # matching: an unaliased gate name resolves to None and reports NO METRIC,
    # which downstream reads as "no violation" instead of "not measured".
    "verification": "funcverif",
    "functional_coverage": "funccov",
    "functional-coverage": "funccov",
    "code_coverage": "codecov",
    "code-coverage": "codecov",
    "coverage": "codecov",
    "structural_coverage": "codecov",
    "logic_synthesis": "synthesis",
    "logic-synthesis": "synthesis",
    "synth": "synthesis",
    "equivalence": "lec",
    "logical_equivalence": "lec",
    "post_synth_lec": "lec",
    "post-synth-lec": "lec",
    "post_dft_lec": "lec",
    "formal_verification": "formal",
    "formal-verification": "formal",
    "cdc_rdc": "cdc",
    "cdc-rdc": "cdc",
    "cdc_rdc_signoff": "cdc",
    "rdc": "cdc",
    "rtl_design": "rtl",
    "rtl-design": "rtl",
    "rtl_lint": "lint",
    "rtl-lint": "lint",
    "constraints_sdc": "constraints",
    "constraints-sdc": "constraints",
    "sdc": "constraints",
    "static_timing_analysis": "sta",
    "timing": "sta",
    "eco": "eco",
    "signoff_eco": "eco",
    "signoff-eco": "eco",
    "timing_eco": "eco",
    "chip-eco": "eco",
    "parasitic_extraction": "extraction",
    "parasitics": "extraction",
    "metal_fill": "metal-fill",
    "metalfill": "metal-fill",
    "scaninteg": "dft",
    "scan-integrity": "dft",
    "power": "power-ir",
    "power_ir": "power-ir",
    "reliability": "power-ir",
    "power-ir-drop": "power-ir",
    "drc_lvs_erc": "drc",
    "drc-lvs-erc": "drc",
    "antenna_erc": "antenna",
    "gds_assembly": "gds",
    "scan_insert": "dft",
    "dft_scan": "dft",
    # -> `dft`: its `direct` fields (broken_chains / orphan_flops /
    # flush_sim_failures) ARE the scan-integrity gate. `scan-chain` was
    # never a STAGE_RESIDUALS key, so this aliased to nothing.
    "scan-chain-integrity": "dft",
    "scan_chain_integrity": "dft",
    # the label the scan-integrity leaves actually carry
    "scan-integrity": "dft",
    "scan_integrity": "dft",
    "testbench_generation": "testbench",
    "assertion_generation": "assertions",
    "atpg": "atpg",
    "fault_atpg": "atpg",
    "gls": "gls",
    "gate_level_simulation": "gls",
    "gate-level-sim": "gls",
    "decap-fill": "decap-fill",
    "decap_fill": "decap-fill",
    "decap-filler": "decap-fill",
    "streamout_xor": "streamout-xor",
    "xor_gds": "streamout-xor",
    "dual_streamout_xor": "streamout-xor",
    "physical-integrity-checker": "integrity",
    "physical_integrity_checker": "integrity",
    "integrity_check": "integrity",
    "opendb-utilities": "opendb",
    "opendb_utilities": "opendb",
    # Tool `TOOL` constants, which do not always match their stage name. Without
    # these a tool that omits results["stage"] silently reports no metric.
    "power_analysis": "power-ir",
    "power_intent_upf": "low-power",
    "design_intent": "spec",
    "pdk_binding": "pdk",
    "gds_assembly": "gds",
    "floorplanning": "floorplan",
    "antenna_erc_check": "antenna",
    "library_characterization": "library",
    "dse_optimization": "ppa-dse",
    "soc_integration": "soc-integration",
}

# Per-stage residual specification.
#
#   direct     -- field names whose value IS ALREADY the residual (0 == closed)
#   pct_to_100 -- coverage percentages; residual = 100 - value (worst wins)
#   neg_slack  -- signed slack fields; residual = abs(min(0, value))
#   bool_ok    -- BOOLEAN gate fields where True == closed; residual 0 / 1
#   population -- field names giving the measured population (Goodhart guard)
#   kind       -- continuous | discrete | binary | unavailable
#   iterating  -- False for stages where re-running cannot improve the metric
#
# `bool_ok` exists because several tools express their gate as a pass/fail flag
# (`synthesizable: true`, `sim_passed: true`) rather than a count. That IS a
# residual -- 0 when closed, 1 when open -- and ignoring it left whole scenarios
# unreadable. It is an explicit per-stage allow-list, never "any boolean": a
# field like `instrumented: true` says nothing about whether the gate closed.
#
# UNIT FAMILIES: `direct` yields the `count` family, `pct_to_100` the
# `percent_gap` family, `neg_slack` the `slack_ns` family. These are NOT
# commensurable, so each carries its own residual and they are never compared to
# each other. `primary_family` names the one a scalar consumer sees, and
# `unit_count` gives the unit of the `direct` family when a stage has several.
#
# NAMED FAMILIES (`named_families`): maps an EXPLICIT family name to its candidate
# source fields, instead of collapsing everything into the shared `count` family.
# Needed whenever a gate has several same-unit-but-CAUSALLY-DISTINCT components
# that different upstream owners repair: STA's DRV checks are all "violation
# counts", so `direct` would fold them into one `count` family whose residual is
# just the max -- which erases WHICH check is failing.  That distinction is what
# catalog/policy/reopen-repertoire.json keys on to pick the causal reopen owner,
# so collapsing it makes the autonomous rung-2 path unable to route.  Family names
# emitted here are a CONTRACT with `residual_class_map` in that repertoire file --
# renaming one without the other silently degrades reopen selection to
# nearest-predecessor guessing.
#
# Ordering within each list is PRIORITY ORDER: the most authoritative field name
# for that stage comes first.
#
# Some stages report a NUMERATOR/DENOMINATOR pair for the SAME gating claim
# (proved vs. compared). The residual invariant above cannot catch a mixed-basis
# triple: it only compares `residual` (the direct metric) against `gate_closed`,
# and a stray correctly-zero `unproven_points` still satisfies that check even
# when the paired `equivalent_points`/`total_partitions` came from a DIFFERENT
# proof run. MEASURED 2026-09 (<TaskID>, <myDesign-A> lec.1): a run legitimately
# used two proof engines -- a partitioned EQY pass (19 partitions, 15 proved, 4
# FAILED) and a superseding flat whole-design proof (49/49 proven, 0 unproven).
# The verdict correctly derived from the flat proof, but `equivalent_points`
# (15) and `total_partitions` (19) were left over from the superseded EQY run
# while `unproven_points` (0) came from the flat one -- 19-15=4, not 0, and
# `alignment` self-reported "ok" because nothing ever checked that arithmetic.
# So this is a SEPARATE, stage-declared check: whenever all three named fields
# resolve to numbers, `total == proven + unproven` must hold, or the triple is
# internally incoherent regardless of what closed the gate.
_BALANCE_CHECKS = {
    "lec": {"total": "total_partitions", "proven": "equivalent_points",
            "unproven": "unproven_points"},
}


STAGE_RESIDUALS = {
    "codecov": {
        "metric_id": "uncovered_code_points",
        "direct": ["reachable_unhit", "uncovered_points", "uncovered_lines"],
        "pct_to_100": ["line_percent", "branch_percent", "toggle_percent",
                       "line", "branch", "toggle"],
        "population": ["total_points", "coverable_points", "total_lines"],
        # A point count and a percentage gap are different quantities; the count
        # is authoritative when present because the gate is `reachable_unhit == 0`.
        "primary_family": "count", "unit_count": "points",
        "unit": "points", "kind": "continuous", "iterating": True,
        # <TaskID> REWORK: `percent_gap` (line/branch/toggle-below-100%) is a
        # DIAGNOSTIC coverage-completeness reading, not an independent gate --
        # the stage's own documented gate is `reachable_unhit == 0` (see above).
        # MEASURED on `code-coverage.2` (<myTopDesign>): `count` closed at 0 while
        # `toggle` sat at 97.42% (a 2.58 percent-point gap on unreachable-adjacent
        # toggle points that are not part of the `reachable_unhit` gate), and the
        # generic "closed primary must not mask an open sibling" promotion (below)
        # then promoted `percent_gap` to primary and forced `metric_defect` on a
        # genuinely-closed gate. Without this exclusion the model's own stated
        # authority (`count`/`reachable_unhit`) would be silently overridden by a
        # metric it explicitly disclaims as non-gating.
        "diagnostic_only_families": ["percent_gap"],
        # Reachable-unhit is the ACTUAL gate (`reachable_unhit == 0`), so name it
        # rather than folding it into the shared `count` family -- `count` is
        # emitted by 37 stages with 9 different units and cannot be routed on.
        "named_families": {
            "reachable_unhit": ["reachable_unhit"],
        },
        # <TaskID> (item 5, wave 5): ADDITIVE -- `<myTopDesign>.1/code-coverage.2`'s
        # own hand-authored `progress` names SIX per-type/per-check
        # obligations (`line`/`branch`/`toggle`/`top_pad_toggle`/
        # `regression`/`traceability`) that neither `count`/`percent_gap`/
        # `reachable_unhit` above reproduce -- MEASURED: a fresh recompute
        # only ever emits 3 families, so `finalize_cde --fix` was silently
        # REFUSING to write this attempt at all (<TaskID> basis-narrowing
        # guard), masking the gap behind an apparently-unchanged harness
        # diff. Each family below is sourced from the real per-type
        # covered/total pair this dialect emits (also aliased to
        # `<myDesign-B>.1/code-coverage.4`'s own `{line,branch,toggle}_coverage`
        # spelling so neither producer's naming is favoured over the
        # other's), plus the two boolean/count checks
        # (`regression_failed`, `full_applicable_traceability`) this
        # producer records directly.
        "obligation_families": {
            "line": [
                {"kind": "gap",
                 "population_paths": ["results.line.total",
                                       "results.line_coverage.total"],
                 "achieved_paths": ["results.line.covered",
                                     "results.line_coverage.covered"]},
            ],
            "branch": [
                {"kind": "gap",
                 "population_paths": ["results.branch.total",
                                       "results.branch_coverage.total"],
                 "achieved_paths": ["results.branch.covered",
                                     "results.branch_coverage.covered"]},
            ],
            "toggle": [
                {"kind": "gap",
                 "population_paths": ["results.toggle.total",
                                       "results.toggle_coverage.total"],
                 "achieved_paths": ["results.toggle.covered",
                                     "results.toggle_coverage.covered"]},
            ],
            "top_pad_toggle": [
                {"kind": "gap",
                 "population_paths": ["results.top_pad_toggle.total",
                                       "results.signal_pad_toggle.total"],
                 "achieved_paths": ["results.top_pad_toggle.covered",
                                     "results.signal_pad_toggle.covered"]},
            ],
            "regression": [
                {"kind": "count", "paths": ["results.regression_failed"]},
            ],
            "traceability": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.full_applicable_traceability"]},
            ],
        },
    },
    "funccov": {
        "metric_id": "coverage_holes",
        # *** A FUNCCOV GATE FAILS ON THREE INDEPENDENT THINGS, NOT ONE. ***
        # MEASURED 2026-09-02: two envelopes carried verdict=fail WITH
        # residual=0.0 because only `holes` was declared here, while the gate had
        # actually failed on something else:
        #   <myDesign-A>/functional-coverage.1 -- holes=0 but tests_failed=1
        #   <myTopDesign>/coverage.6             -- holes=0 but reachable_unhit=10
        # The violating component was not merely masked by a clean one, it was
        # UNDECLARED, so it could not be recorded at all. That is the inverse of
        # the laundering shape and just as dangerous: a scalar consumer reads
        # residual 0 as a closed gate, and the stall machinery reads a metric
        # pinned at 0 as CONVERGED while the stage is failing every attempt.
        "direct": ["holes", "goal_gap", "uncovered_bins", "unhit_bins",
                   "reachable_unhit", "tests_failed"],
        "pct_to_100": ["overall_percent", "overall_functional_coverage",
                       "functional_coverage_percent"],
        "population": ["modeled_points", "total_bins", "named_bins_requested"],
        "primary_family": "count", "unit_count": "bins",
        "unit": "bins", "kind": "continuous", "iterating": True,
        # Three CAUSALLY DISTINCT owners: an unhit bin needs more stimulus, an
        # unhit REACHABLE point needs targeted stimulus or a reachability ruling,
        # and a failing test needs a design/testbench fix. Collapsing them into
        # one `count` family would erase which one is open, which is exactly what
        # reopen-repertoire keys on to pick the causal owner. `reachable_unhit`
        # and `test_failures` are already mapped in residual_class_map.
        "named_families": {
            "coverage_holes": ["holes", "uncovered_bins", "unhit_bins", "goal_gap"],
            "reachable_unhit": ["reachable_unhit"],
            "test_failures": ["tests_failed"],
        },
    },
    "funcverif": {
        "metric_id": "failing_tests",
        "direct": ["failures", "mismatches", "scoreboard_mismatches",
                   "failing_tests", "errors", "analyze_errors",
                   "elaboration_errors", "error_lines"],
        "bool_ok": ["sim_passed"],
        "population": ["tests", "executed_comparisons", "tests_run",
                       "directed_tests_completed"],
        "unit": "tests", "kind": "discrete", "iterating": True,
        # An elaboration error means the model never ran; a scoreboard mismatch
        # means it ran and disagreed. Reporting both as one `count` hides which.
        "named_families": {
            "test_failures": ["failures", "failing_tests", "mismatches",
                              "scoreboard_mismatches"],
            "elab_errors": ["elaboration_errors", "analyze_errors"],
        },
    },
    "formal": {
        "metric_id": "unproven_properties",
        "direct": ["unproven_assertions", "assert_failed_count",
                   "assertions_failed", "counterexamples",
                   "counterexample_traces", "failing_properties",
                   "unknown_count"],
        "population": ["assertions_checked_against_dut", "assert_cells_total",
                       "assertions", "assert_passed_count"],
        "unit": "properties", "kind": "discrete", "iterating": True,
        # An inconclusive (bounded-depth "unknown") property is NOT a failing one:
        # one needs more depth, the other needs a design or property fix.
        "named_families": {
            "unproven_properties": ["unproven_assertions", "failing_properties",
                                    "assertions_failed", "assert_failed_count",
                                    "counterexamples", "counterexample_traces"],
            "inconclusive_properties": ["unknown_count"],
        },
        # <TaskID> (WAVE 1, item 3): ADDITIVE obligation_families -- the three
        # pinned `formal` pointers use THREE different named-family sets none
        # of which is `unproven_properties`/`inconclusive_properties` above
        # (MEASURED, all stale/hand-authored): <myDesign-A>.1/formal.1 names
        # `unproven_assertions`/`vacuity`; <myDesign-B>.1/formal.2 names `proof`/
        # `counterexample`/`vacuity`/`property_work`; <myTopDesign>.1/formal.7
        # (<TaskID> is concurrently adjudicating its VR-205 disposition --
        # validated here against crc16/<myDesign-B> ONLY, per <TaskID> wave-1
        # instructions, and applied to <myTopDesign> no earlier than after <TaskID>)
        # names `counterexamples`/`self_waivers`/`source_assumptions`/
        # `unproven_assertions`/`unreached_antecedent_covers`. Every name from
        # every dialect is declared below so none is dropped regardless of
        # which dialect produced the CDE.
        "obligation_families": {
            # <TaskID> FIX 1: `unproven_assertions`, `counterexamples` and
            # `self_waivers` each ALSO carry a `gap` recipe cross-checking the
            # producer's declared GATING population (`results.gating_assertions`)
            # against the AUTHORED population it was narrowed FROM
            # (`results.source_assertions`) -- present on the SAME envelope,
            # not loaded from an upstream file. MEASURED on
            # <myTopDesign>.1/formal.7: `source_assertions`=12 (grep of
            # formal_top.sv, basis note says so explicitly), `gating_assertions`
            # =11 (12 minus VR-205, "excluded by construction, not a gating
            # property" -- with NO citation to a human waiver ruling). That
            # 12-11=1 gap IS an undisclosed self-waiver: the stage shrank its
            # own denominator and then reported a clean residual over the
            # remainder. Both `count` recipes below still read the dialect's
            # face-value fields (0 in this case) so a genuinely-zero dialect is
            # untouched; the `gap` recipe's residual is the WORST of the two
            # per `_finalize_slots`, so a real gap always wins over a
            # self-reported zero. On <myDesign-A>.1/formal.1 and
            # <myDesign-B>.1/formal.2 neither `source_assertions` nor
            # `gating_assertions` exists (their gating population IS their
            # full authored population -- verified against
            # assertions.1's `assertion_count`=11 / `assertions_authored`=9,
            # both matching exactly), so this recipe never binds there and
            # those two dialects are unaffected.
            "unproven_assertions": [
                {"kind": "count", "paths": [
                    "results.unproven_assertions", "results.failed_count"]},
                {"kind": "declared_threshold", "paths": [
                    "results.bmc_isolated_proved", "results.unbounded_proved"]},
                {"kind": "gap",
                 "population_paths": ["results.source_assertions"],
                 "achieved_paths": ["results.gating_assertions"]},
            ],
            "counterexamples": [
                {"kind": "count", "paths": [
                    "results.counterexamples", "results.counterexample_count",
                    "results.counterexamples_gating", "results.bmc_assert_failures"]},
                {"kind": "gap",
                 "population_paths": ["results.source_assertions"],
                 "achieved_paths": ["results.gating_assertions"]},
            ],
            # <myDesign-A>.1/formal.1's OWN `vacuity` family groups exactly
            # these two real counts (MEASURED).
            "vacuity": [
                {"kind": "count", "paths": [
                    "results.vacuous_proofs", "results.vacuous_count",
                    "results.unreached_antecedent_covers"]},
            ],
            "unreached_antecedent_covers": [
                {"kind": "count", "paths": [
                    "results.unreached_antecedent_covers",
                    "results.cover_targets_unreached"]},
                {"kind": "declared_threshold", "paths": [
                    "results.cover_targets_reached"]},
            ],
            # `self_waivers` / `source_assumptions` are ONLY meaningful on a
            # dialect that tracks them (MEASURED: <myTopDesign>.1/formal.7 only)
            # -- a dialect with neither key correctly resolves not_assessable
            # rather than a fabricated zero.
            "self_waivers": [
                {"kind": "declared_threshold", "paths": ["results.self_waivers"]},
                {"kind": "count", "paths": ["results.self_waivers"]},
                {"kind": "gap",
                 "population_paths": ["results.source_assertions"],
                 "achieved_paths": ["results.gating_assertions"]},
            ],
            "source_assumptions": [
                {"kind": "declared_threshold", "paths": [
                    "results.source_assumption_cells"]},
                {"kind": "count", "paths": ["results.source_assumption_cells"]},
            ],
            # <myDesign-B>.1/formal.2's own family names.
            "proof": [
                {"kind": "count", "paths": [
                    "results.failed_count", "results.unproven_assertions"]},
            ],
            "counterexample": [
                {"kind": "count", "paths": [
                    "results.counterexample_count", "results.counterexamples"]},
            ],
            "property_work": [
                {"kind": "exclusive_floor", "floor": 0,
                 "paths": ["results.property_work_count"]},
            ],
        },
    },
    "lec": {
        # *** THE "NO MEASURABLE RESIDUAL" CLAIM WAS SELF-INFLICTED. *** This
        # stage was kind=binary / iterating=False on the rationale that
        # "equivalence does not get closer". MEASURED 2026-09-02, that conflated
        # two different things:
        #   - CLOSURE is binary and STAYS binary. 15-of-19 partitions proven is
        #     NOT "79% equivalent"; it is an INCOMPLETE PROOF. Only 0 unproven
        #     closes the gate. Nothing here relaxes that.
        #   - PROGRESS is measurable and demonstrably moves between attempts.
        #     EQY prints "Failed to prove equivalence for 4/19 partitions", and a
        #     config change moved a real partition from failing to proved (adding
        #     `splitnets -ports` fixed the aliased-output-port partition on BOTH
        #     <myDesign-B> and crc16).
        # The residual only LOOKED absent because the tool's parser searched for
        # "N of M partitions proven" -- a string EQY never emits -- so all 7 real
        # attempts recorded unproven=None and the stall machinery had nothing to
        # act on. With the parser fixed the residual is real, so this stage can
        # iterate: LEC failures are very often SETUP (partitioning, key-point
        # mapping, engine choice), which is precisely rung-1 in-stage work.
        "metric_id": "unproven_key_points",
        "direct": ["unproven_points", "unproved_partitions", "failing_points",
                   "disproved_partitions", "unmapped_points", "counterexamples"],
        # POPULATION IS LOAD-BEARING HERE, NOT DECORATIVE: `unproven_points`
        # alone is Goodhart-able because re-partitioning changes the DENOMINATOR
        # -- 4-of-19 followed by 2-of-4 reads as progress while proving strictly
        # less. The tool also records the partition NAME SET in
        # signoff.partition_scope so a CHANGED QUESTION is distinguishable from
        # an IMPROVED PROOF.
        "population": ["total_partitions", "mapped_points", "equivalent_points"],
        "unit": "key_points", "kind": "discrete", "iterating": True,
        # An unmapped key point is a SETUP problem (the two netlists were not
        # aligned); a disproved partition is a genuine non-equivalence. Different
        # causes, different owners, so they must not share one family.
        "named_families": {
            "equivalence_proof": ["unproven_points", "failing_points",
                                  "disproved_partitions", "counterexamples"],
            "key_point_mapping": ["unmapped_points", "unproved_partitions"],
        },
        # <TaskID> (item 3, wave 4): MEASURED on `<myDesign-A>.1/lec-post-eco.7`
        # (hand-authored `progress.families`) and `<myTopDesign>.1/lec-post-
        # dft.9`/`lec-post-synth.18` -- THREE more causally distinct LEC
        # obligations beyond the proof/mapping pair above: an unexpected-
        # residual-cell scope check (a cell survived that neither netlist's
        # declared model set explains), a black-box-scope check (only the
        # INTENTIONAL, symmetric black boxes -- e.g. I/O pads -- are
        # present, nothing else), and a functional-projection-determinism
        # check (the mission-mode wrapper reduces to one deterministic
        # functional netlist on both sides). None of these were derivable
        # before; a fresh recompute previously silently dropped all three
        # relative to the hand-authored blocks that named them.
        "obligation_unit": "cells",
        "obligation_families": {
            "model_scope": [
                {"kind": "count", "paths": [
                    "qor_metrics.unexpected_residual_cells",
                    "results.unexpected_residual_cells"]},
            ],
            "black_box_scope": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unintended_black_boxes",
                    "validation.zero_unintended_blackboxes",
                    "validation.intentional_io_blackboxes_only"]},
            ],
            "functional_projection": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.functional_projection_deterministic",
                    "validation.functional_projection_deterministic"]},
            ],
        },
    },
    "lint": {
        "metric_id": "unwaived_violations",
        # `check_problems` / `elaboration_errors` / `inferred_latches` were found
        # in real microwatt envelopes that reported no residual at all.
        #
        # DELIBERATELY EXCLUDED from this list, though they sit alongside those
        # keys in the same envelopes:
        #   in_scope_sanctioned_violations -- "sanctioned" means ALREADY WAIVED;
        #       counting it would re-open approved waivers as open violations.
        #   canonical_format_files_identical_to_golden -- higher is BETTER, so
        #       reading it as a residual inverts the direction of progress.
        "direct": ["gate_violations_unwaived", "unwaived_gate_violations",
                   "lint_violations", "fatal_errors", "check_problems",
                   "elaboration_errors", "inferred_latches",
                   # MEASURED 2026-09-02 (<myTopDesign>/lint.1): the gate failed on
                   # formatting_failures=2 while lint_violations=0, so the whole
                   # residual read 0.0 on a FAILING gate. Unlike the
                   # higher-is-better field excluded above, this is a count that
                   # must reach zero, so it is a correct-direction residual.
                   "formatting_failures"],
        "population": ["source_files_linted", "member_entities_linted"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        # An inferred latch is a DESIGN defect an `rtl` reopen fixes; a style
        # violation is not. Collapsing both into one count erases which one is open.
        "named_families": {
            "lint_violations": ["gate_violations_unwaived", "unwaived_gate_violations",
                                "lint_violations", "check_problems"],
            "inferred_latches": ["inferred_latches"],
            "elab_errors": ["elaboration_errors", "fatal_errors"],
            # Reformatting is a mechanical fix with a different owner than a
            # rule violation; `format` is already mapped in residual_class_map.
            "format": ["formatting_failures"],
        },
        # <TaskID> (item 3, wave 5): MEASURED -- real attempts across all 3
        # designs record the canonical-formatting obligation as
        # `unformatted_files`/`format_violations`, never as the
        # `formatting_failures` alias the `format` named_family above maps
        # to. That alias never matches real data, so a fresh recompute of
        # `<myTopDesign>.1/lint.6` (on-disk `count` included
        # `qor_metrics.unformatted_files`) previously dropped the format
        # obligation entirely rather than merely mis-naming it.
        "obligation_unit": "violations",
        "obligation_families": {
            "format": [
                {"kind": "count", "paths": [
                    "results.unformatted_files.value",
                    "results.format_violations.value",
                    "qor_metrics.unformatted_files",
                    "qor_metrics.format_violations"]},
            ],
        },
    },
    "cdc": {
        "metric_id": "unwaived_cdc_violations",
        "direct": ["unwaived_violations", "unwaived_violations_reported",
                   "unsynchronized_crossings", "unsynchronized_crossings_reported"],
        "population": ["crossings", "cdc_crossings", "sequential_cells_extracted",
                       "clock_domain_crossings_reported"],
        "unit": "crossings", "kind": "discrete", "iterating": True,
        "named_families": {
            "unsynchronized_crossings": ["unsynchronized_crossings",
                                         "unsynchronized_crossings_reported"],
            "cdc_violations": ["unwaived_violations",
                               "unwaived_violations_reported"],
        },
        # <TaskID> (item 3, wave 4): MEASURED on `<myTopDesign>.1/cdc.5` -- a
        # far richer structural+formal CDC/RDC signoff dialect than the
        # <myDesign-B>/<myDesign-A> structural-only screens above: synchronizer
        # inventory reconciliation, reconvergence, and THREE distinct
        # bounded-model-checking task classes (bmc/prove/cover), each with
        # its own exact-work-count guard. `progress` was previously entirely
        # absent for this attempt (`null`).
        "obligation_unit": "violations",
        "obligation_families": {
            "synchronizer_verification": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.synchronizer_pass",
                    "validation.all_declared_synchronizers_verified"]},
            ],
            "reconvergence": [
                {"kind": "count", "paths": [
                    "results.reconvergence_violations",
                    "qor_metrics.reconvergence_violations"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.reconvergence_pass"]},
            ],
            "crossing_classification": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_crossings_classified"]},
            ],
            "reset_resolution": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.reset_resolution_preserved"]},
            ],
            "formal_bmc": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.bmc_task_pass",
                    "validation.checks.bmc_all_final_pass"]},
            ],
            "formal_prove": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.prove_task_pass",
                    "validation.checks.prove_all_final_pass"]},
            ],
            "formal_cover": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.cover_task_pass",
                    "validation.checks.cover_all_final_pass"]},
            ],
            "formal_work_positive": [
                {"kind": "exclusive_floor", "floor": 0, "paths": [
                    "results.formal_positive_work_count",
                    "qor_metrics.formal_positive_work_count"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.formal_positive_work",
                    "validation.checks.no_skipped_formal_properties"]},
            ],
        },
    },
    "rtl": {
        "metric_id": "rtl_hygiene_defects",
        "direct": ["elaboration_errors", "inferred_latch_count", "inferred_latches",
                   "inferred_latches_total", "multidriven_nets",
                   "multidriven_nets_total", "check_problems", "undriven_nets",
                   "undriven_nets_total"],
        "bool_ok": ["synthesizable", "elaborates"],
        "population": ["member_entities_total", "rtl_source_files"],
        "unit": "defects", "kind": "discrete", "iterating": True,
        # <TaskID> (item 3, wave 5): MEASURED across all 3 designs' `rtl`
        # dialect -- `reset_hygiene_violations`, `unwaived_lint_diagnostics`
        # / `lint_violations`, `contract_checks_failed`, and
        # `traced_requirements_failed` were NOT in the `direct` list above,
        # so a fresh recompute previously read them as zero contribution to
        # the single collapsed `count` family (or dropped entirely). Real
        # attempts already hand-author these as distinct named families
        # (`hygiene`/`contract`/`lint` on <myDesign-A>.1/rtl.2) precisely
        # because each is a structurally distinct check with a different
        # owner: an inferred latch is a synthesis-visible design defect, a
        # reset topology defect is a CDC/RDC-adjacent structural finding, a
        # lint/format violation is style, and a contract/traced-requirement
        # failure is a spec-conformance gap.
        "obligation_unit": "defects",
        "obligation_families": {
            "elaboration": [
                {"kind": "bool_true_ok", "paths": [
                    "results.synthesizable.value", "results.synthesizable",
                    "validation.all_modules_elaborate",
                    "validation.correct_module_elaborated"]},
            ],
            "inferred_latches": [
                {"kind": "count", "paths": [
                    "results.inferred_latch_count.value",
                    "results.inferred_latch_count",
                    "signoff_evidence.diagnostics.inferred_latches"]},
            ],
            "driver_hygiene": [
                {"kind": "count", "paths": [
                    "results.check_problems.value", "results.check_problems"]},
            ],
            "reset_hygiene": [
                {"kind": "count", "paths": [
                    "results.reset_hygiene_violations.value",
                    "results.reset_hygiene_violations",
                    "results.reset_hygiene_violations_real_rtl_scope.value"]},
            ],
            # A multi-bit payload given one 2-flop chain per bit has no latch, no
            # undriven net and clean reset style, so every family above reads zero
            # while the design is wrong. Measured on <myTopDesign> rtl.2.
            "synchronizer_hygiene": [
                {"kind": "count", "paths": [
                    "results.synchronizer_hygiene_violations.value",
                    "results.synchronizer_hygiene_violations"]},
            ],
            "lint": [
                {"kind": "count", "paths": [
                    "results.unwaived_lint_diagnostics.value",
                    "results.lint_violations.value",
                    "qor_metrics.lint_violations"]},
            ],
            "contract_conformance": [
                {"kind": "count", "paths": [
                    "results.contract_checks_failed.value",
                    "results.contract_checks_failed"]},
            ],
            "traced_requirements": [
                {"kind": "count", "paths": [
                    "results.traced_requirements_failed.value",
                    "results.traced_requirements_failed",
                    "qor_metrics.rtl_requirement_failures"]},
            ],
        },
    },
    "constraints": {
        "metric_id": "unconstrained_endpoints",
        # `unclocked_indicators` is what the tool actually emits; without it a
        # real constraints run reported nothing.
        #
        # `unconstrained_indicators` is DELIBERATELY EXCLUDED (it is labelled
        # DIAGNOSTIC by the tool). MEASURED on a real sandbox run: it counted 2
        # on an SDC whose true defect count was ZERO -- one hit was the tool's
        # own `__UNCONSTRAINED__` section banner, the other a REQUIRED
        # `set_false_path` on an async reset. A keyword count cannot tell a
        # correct exception from a real gap, so making it the residual pins the
        # gate above zero on a design that is right. `warnings` is excluded for
        # the same reason: advisory noise must not make a gate unclosable.
        "direct": ["unconstrained_endpoints", "missing_clock_endpoints",
                   "unclocked_indicators"],
        "pct_to_100": ["constraint_coverage_percent"],
        "population": ["sequential_endpoints", "clock_objects",
                       "unconstrained_indicators"],
        "primary_family": "count", "unit_count": "endpoints",
        "unit": "endpoints", "kind": "continuous", "iterating": True,
        # <TaskID> (item 5, wave 5): the shared `count` family above binds only
        # `unconstrained_endpoints` -- MEASURED across every blessed
        # constraints/constraints-post-dft pointer (all 3 designs), each
        # attempt's own `results` records several MORE causally distinct
        # obligations `chip-constraints-sdc` genuinely checks
        # (clock definition, delay-command qualification, corner binding,
        # exception hygiene, intent completeness, scan-constraint coverage),
        # none of which any prior alias reached: `<myDesign-B>.1/constraints.7`
        # and `<myDesign-A>.1/constraints.8` both carry NO `progress.families`
        # key at all despite `verdict: pass`/`gate_closed: true` (the exact
        # empty-basis defect this task exists to catch), and
        # `<myDesign-B>.1/constraints-post-dft.1` was found BLOCKING on a fresh
        # census (its old hand-authored `progress` cites an external
        # `reports/scan_constraint_coverage.json` file path as `source`,
        # which no dotted-path resolver can ever follow). Each family below
        # is sourced from a real key this stage's own `results`/
        # `validation.checks` records -- `declared_threshold` reads the
        # producer's OWN `class`/`closes_at` wrapper where present (crc16's
        # `results.clock_count`-style dialect); the plain-int/boolean
        # fallbacks cover the <myDesign-B>/post-dft dialects that record the same
        # fact unwrapped.
        "obligation_families": {
            "clock_definition": [
                {"kind": "declared_threshold", "paths": ["results.clock_count"]},
                {"kind": "target_delta", "paths": [
                    "results.functional_clock_count"], "target": 1},
            ],
            "delay_qualification": [
                {"kind": "declared_threshold", "paths": [
                    "results.missing_delay_bits"]},
                {"kind": "declared_threshold", "paths": [
                    "results.qualified_input_delay_bits"]},
                {"kind": "declared_threshold", "paths": [
                    "results.qualified_output_delay_bits"]},
            ],
            "corner_binding": [
                {"kind": "declared_threshold", "paths": [
                    "results.bound_corners_passed"]},
                {"kind": "gap", "population_paths": ["results.bound_corners"],
                 "achieved_paths": ["results.passing_corners"]},
            ],
            # A NONZERO false/multicycle/case-analysis count is not itself a
            # defect (<myDesign-A>.1/constraints-post-dft.3 legitimately has
            # none; <myTopDesign>.1/constraints-post-dft.2 legitimately has
            # THREE DR220-justified false paths) -- the genuine obligation
            # is that none is FABRICATED/undisclosed, which is exactly what
            # this stage's own `no_fabricated_false_or_multicycle_paths`/
            # `no_case_analysis` booleans and `declared_threshold`-wrapped
            # counts (where present) already certify.
            "exception_hygiene": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.no_fabricated_false_or_multicycle_paths"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.no_case_analysis"]},
                {"kind": "declared_threshold", "paths": [
                    "results.false_path_count"]},
                {"kind": "declared_threshold", "paths": [
                    "results.multicycle_path_count"]},
                {"kind": "declared_threshold", "paths": [
                    "results.case_analysis_count"]},
            ],
            "intent_completeness": [
                {"kind": "count", "paths": ["results.unsupplied_intent_holes"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unsupplied_intent_holes"]},
            ],
            "scan_constraint_coverage": [
                {"kind": "count", "paths": [
                    "results.unconstrained_scan_endpoints"]},
                {"kind": "gap",
                 "population_paths": ["results.scan_ports_required"],
                 "achieved_paths": ["results.scan_ports_constrained"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unconstrained_scan_endpoints"]},
            ],
            "object_resolution": [
                {"kind": "count", "paths": ["results.unresolved_objects"]},
            ],
            "electrical_completeness": [
                {"kind": "count", "paths": [
                    "results.missing_required_electrical_commands"]},
            ],
            "unclocked_register_pins": [
                {"kind": "count", "paths": ["results.unclocked_register_pins"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unclocked_register_pins"]},
            ],
        },
    },
    "synthesis": {
        "metric_id": "synthesis_gate_defects",
        # *** THE DECLARED ALIASES MATCHED NOTHING THE TOOL EMITS. *** MEASURED
        # 2026-09-02: 3 of 3 COMPLETED synthesis attempts carried residual=null
        # while their envelopes plainly reported `latches: 0`,
        # `unresolved_cells: 0`, `port_mismatches: 0`. The registry asked for
        # `inferred_latches` / `unintended_blackboxes` / `generic_unmapped_cells`,
        # which chip-logic-synthesis never writes -- so every lookup missed and a
        # CLEAN stage read as UNMEASURABLE. Same false-absence class as the
        # sta/lec/formal parser bugs: a name that matches nothing produces
        # silence, and silence reads as "no metric", not "no violation".
        # The original names are KEPT so another/older producer still resolves.
        "direct": ["inferred_latches", "latches",
                   "dont_use_violations",
                   "unintended_blackboxes", "unresolved_cells",
                   "generic_unmapped_cells", "port_mismatches"],
        "neg_slack": ["setup_tns_ns", "estimated_tns"],
        # `cell_count`/`cell_area` are POPULATION and PPA, never residuals: a
        # 245-cell design is not 245 defects away from closing.
        "population": ["cell_count", "mapped_cell_count"],
        # Structural defects gate synthesis; timing is tracked as its own family
        # so a 0-latch result can never vouch for a multi-million-ns TNS.
        "primary_family": "count", "unit_count": "defects",
        "unit": "defects", "kind": "discrete", "iterating": True,
        # <TaskID-A> (WAVE 1, item 2): ADDITIVE obligation_families -- <TaskID-B>
        # currently stands on THREE hand-authored progress blocks (one per
        # pinned pointer) whose named families do not match anything the
        # `direct`/`neg_slack` lists above derive (MEASURED: fresh
        # derivation with only the spec above yields a single `count`
        # family for all three pinned CDEs, so --fix would have dropped
        # every one of these names). Three DIFFERENT dialects name the same
        # obligations differently -- <myDesign-B>.1/synthesis.6 groups into
        # `structural`/`timing`/`area`/`policy`/`scan`, <myDesign-A>.1/
        # synthesis.4 into `structural`/`timing`/`area`/`scan`, and
        # <myTopDesign>.1/synthesis.2 names each structural defect type as its
        # OWN family (`unmapped_cells`, `inferred_latches`,
        # `dont_use_violations`, `port_contract_mismatches`) plus `timing`/
        # `area`. All names from all three dialects are declared below so
        # none is dropped regardless of which dialect produced the CDE.
        "obligation_families": {
            "unmapped_cells": [
                {"kind": "count", "paths": ["results.unmapped_cells"]}],
            "inferred_latches": [
                {"kind": "count", "paths": ["results.inferred_latches"]}],
            "dont_use_violations": [
                {"kind": "count", "paths": ["results.dont_use_violations"]}],
            "port_contract_mismatches": [
                {"kind": "count", "paths": [
                    "results.port_contract_mismatches",
                    "results.port_mismatches",
                    "results.top_port_contract_mismatches"]}],
            "structural": [
                {"kind": "count", "paths": [
                    "results.unmapped_cells", "results.inferred_latches",
                    "results.dont_use_violations", "results.port_mismatches",
                    "results.top_port_contract_mismatches",
                    "results.port_contract_mismatches",
                    "results.mapped_reload_problems",
                    "results.mapped_flop_count_delta"]}],
            "policy": [
                {"kind": "count", "paths": [
                    "results.dont_use_violations",
                    "results.generated_liberty_files",
                    "results.set_load_commands"]}],
            # `scan_fusion_enabled` is a boolean whose CORRECT direction
            # (fused scan must stay disabled until the dedicated DFT stage)
            # is only knowable from the producer's own `class: gating` +
            # `closes_at: "== false"` declaration (MEASURED on
            # <myDesign-A>.1/synthesis.4's `synthesis_fused_scan_enabled`,
            # `class: gating`) -- guessing `True == closed` here would have
            # <TaskID> (REOPENED, item 1c): `declared_threshold` alone treated a
            # PRESENT-BUT-FALSY boolean as ABSENT evidence. MEASURED on
            # <myDesign-B>.1/synthesis.6: `results.scan_fusion_enabled` is the bare
            # boolean `False` with no `class`/`closes_at` wrapper (unlike
            # <myDesign-A>.1/synthesis.4's `synthesis_fused_scan_enabled`,
            # which IS wrapped and gating) -- `declared_threshold` correctly
            # refuses an untagged node, but nothing else was declared to read
            # a bare boolean, so real evidence (fused scan is OFF) was
            # reported as "no evidence". The correct DIRECTION for this exact
            # field name is not a guess here: <myDesign-A>.1/synthesis.4's own
            # `class: gating, closes_at: "== false"` on the same semantic
            # field (fused scan must stay disabled until the dedicated DFT
            # stage) is the producer's own stated contract, reused as a
            # same-field fallback rather than invented. `bool_false_ok` binds
            # ONLY when the value is an actual Python bool (never a stray
            # falsy string/0), so it cannot misread absence as False.
            "scan": [
                {"kind": "declared_threshold", "paths": [
                    "results.synthesis_fused_scan_enabled",
                    "results.scan_fusion_enabled"]},
                {"kind": "bool_false_ok", "paths": [
                    "results.synthesis_fused_scan_enabled",
                    "results.scan_fusion_enabled"]},
            ],
            # <TaskID> (REOPENED, item 1a): `estimated_wns` is `{value: ns,
            # unit: "ns"}` -- `declared_threshold` demanded `unit: "defects"`
            # semantics (a defect COUNT), so ns and defects were never
            # commensurable and the family correctly refused to coerce one
            # into the other. It is ALSO explicitly `class: "diagnostic"` on
            # every dialect checked (<myTopDesign>.1/synthesis.2,
            # <myDesign-A>.1/synthesis.4 -- MEASURED), with the producer's own
            # note: "PRE-LAYOUT AND SDC-UNAWARE ... gating on it would
            # launder a timing claim the run cannot support; chip-sta is the
            # authoritative owner." That disclaimer is binding: this family
            # is bound as a REAL, correctly-unitted `ns` observation (residual
            # = abs(min(0, WNS)), i.e. it WOULD close at WNS >= 0), but it is
            # declared `diagnostic_only` at the stage level below so it is
            # visible and reviewable without ever gating synthesis closure --
            # doing otherwise would make synthesis a second, weaker timing
            # signoff gate in direct contradiction of the producer's own
            # authority statement. Reported prominently in <TaskID>'s
            # completion note rather than silently resolved either way.
            "timing": [
                {"kind": "neg_slack", "unit": "ns",
                 "paths": ["results.estimated_wns"]}],
            # `scoped_area_margin` (<myDesign-A>) and `inside_pad_ring_area`
            # (<myTopDesign>) both carry `class: gating` with an explicit
            # `closes_at`, so they stay as the first-priority paths for those
            # two dialects. <myDesign-B>.1/synthesis.6 declares neither -- its real
            # area measurement is `results.cell_area` ({value: um^2}, `class:
            # "diagnostic"`, MEASURED), added below as the correct key name.
            # It still will not bind via `declared_threshold` (no `class:
            # gating` tag on ANY dialect's `cell_area`), which is the HONEST
            # outcome: `<myDesign-B>/spec/spec.11/results/physical_constraints.json`
            # declares only a top-level (<myTopDesign>-scoped) SR-071 budget
            # (30000 um^2 for "top standard cells plus macro footprints") and
            # a per-macro UTILIZATION target explicitly marked
            # "REPORTED, NOT GATED" (SR-072) -- there is NO <myDesign-B>-scoped
            # absolute area budget to gate on. Inventing one from the
            # top-level figure is exactly the area-budget trap <TaskID> warns
            # against, so `area` is declared `acceptance_critical` below
            # instead: a gate must not close while an acceptance-criterion
            # family is not_assessable, so <myDesign-B>.1/synthesis.6 correctly
            # OPENS rather than closing over an absent budget.
            "area": [
                {"kind": "declared_threshold", "paths": [
                    "results.scoped_area_margin",
                    "results.inside_pad_ring_area",
                    "results.cell_area"]}],
        },
        # <TaskID> (REOPENED, item 1): a gate must never report CLOSED while a
        # `not_assessable` family covers one of <TaskID>'s acceptance criteria
        # (area, timing). `timing` is now bound-but-diagnostic (see above) so
        # this only fires for `area` today, but both are declared so a future
        # dialect losing its `class: gating` timing tag is caught the same
        # way rather than silently reopening this exact defect.
        "acceptance_critical_obligations": ["area", "timing"],
        # `timing`'s ns-unit family is a real, correctly-derived observation
        # of the producer's own disclaimed pre-layout estimate; it must never
        # be allowed to vouch for (or block) synthesis closure, which is
        # chip-sta's authority alone.
        "diagnostic_only_families": ["timing"],
    },
    "sta": {
        "metric_id": "total_negative_slack",
        "neg_slack": ["tns_ns", "setup_tns_ns", "worst_tns_ns", "wns_ns"],
        "direct": ["violating_paths", "failing_endpoints"],
        # Each DRV check is its own family: they share a unit (violations) but NOT
        # a repair owner, and reopen-target selection routes on the family name.
        # A `None` value means "not characterized by the bound Liberty" and is
        # SKIPPED (see _record_named) rather than recorded as a clean 0 -- "we did
        # not look" must never read as "we looked and it was clean".
        "named_families": {
            "drv.max_tran": ["max_transition_violations"],
            "drv.max_cap": ["max_capacitance_violations"],
            "drv.max_fanout": ["max_fanout_violations"],
            "drv.min_pulse_width": ["min_pulse_width_violations"],
            "drv.min_period": ["min_period_violations"],
            "drv.max_skew": ["max_skew_violations"],
            "drv.recovery": ["recovery_violations"],
            "drv.removal": ["removal_violations"],
            "drv.clock_gating_setup": ["clock_gating_setup_violations"],
            "drv.clock_gating_hold": ["clock_gating_hold_violations"],
        },
        "named_family_unit": "violations",
        "population": ["analyzed_paths", "endpoints"],
        "primary_family": "slack_ns", "unit_count": "paths",
        "unit": "ns", "kind": "continuous", "iterating": True,
        # <TaskID>: THE FLAGSHIP CASE the task named explicitly. MEASURED on
        # `<myDesign-A>.1/sta.7` -- its OWN previously-recorded `progress`
        # block names nine obligations (`setup`, `hold`, `max_transition`,
        # `max_capacitance`, `max_fanout`, `minimum_pulse_width`,
        # `parasitic_annotation`, `constraint_coverage`,
        # `propagated_clock`), but a fresh recompute with only `neg_slack`/
        # `named_families` above collapses to a DIFFERENT ten
        # (`count`/`slack_ns`/`drv.*`) -- family COUNT rises 9->10 while
        # EVERY ONE of the nine original names vanishes (none of `count`,
        # `slack_ns`, `drv.max_tran`, ... is textually any of the nine).
        # A count-based guard would wave this through; only a NAMED-set diff
        # catches it. Each of the nine is bound below from an exact real key
        # this attempt actually records (`qor_metrics.*`, `signoff_evidence.
        # *`, `validation.checks.*`). `obligation_unit` stays `violations`
        # (the DRV counts' real unit); `setup`/`hold` override to `ns`.
        "obligation_unit": "violations",
        # Reuses the SAME `flow_scopes.pre_layout_estimate.deferred_family_
        # groups` declared below (currently just `["drv"]`) so a pre-layout
        # STA attempt defers these obligations to post-route exactly as it
        # already deferred `drv.max_tran` etc. via `named_families` --
        # without this, `obligation_families`' bare (unprefixed) naming
        # bypasses that flow-scope policy entirely (MEASURED: 21-46 real
        # `max_transition` violations on 6 registered pre-layout `sta-pre-
        # synth`/`sta-pre-dft` attempts were surfacing as a false
        # `metric_defect`/`blocking` for DRV checks the stage's own policy
        # says are not this attempt's to close).
        "obligation_deferral_groups": {
            "max_transition": "drv", "max_capacitance": "drv",
            "max_fanout": "drv", "minimum_pulse_width": "drv",
            "recovery": "drv", "removal": "drv",
            "clock_gating_setup": "drv", "clock_gating_hold": "drv",
            # MEASURED on `<myDesign-B>.1/sta-pre-synth.3` etc: the producer's OWN
            # `signoff_evidence.descriptive` block stamps `spef_corners: 0`
            # with an explicit disclaimer ("configuration/context, not a
            # gate and not a progress signal") for `pre_layout_estimate`
            # mode -- real parasitic annotation is a post-extraction
            # obligation this flow position cannot have yet.
            "parasitic_annotation": "parasitics",
        },
        "obligation_families": {
            "setup": [
                {"kind": "neg_slack", "unit": "ns",
                 "paths": ["qor_metrics.wns_ns", "margin.wns_ns"]},
                {"kind": "bool_true_ok", "paths": ["signoff_evidence.setup_met"]},
            ],
            "hold": [
                {"kind": "neg_slack", "unit": "ns",
                 "paths": ["qor_metrics.hold_slack_ns"]},
                {"kind": "bool_true_ok", "paths": ["signoff_evidence.hold_met"]},
            ],
            "max_transition": [
                {"kind": "count", "paths": [
                    "qor_metrics.max_transition_violations"]},
            ],
            "max_capacitance": [
                {"kind": "count", "paths": [
                    "qor_metrics.max_capacitance_violations"]},
            ],
            "max_fanout": [
                {"kind": "count", "paths": [
                    "qor_metrics.max_fanout_violations"]},
            ],
            "minimum_pulse_width": [
                {"kind": "count", "paths": [
                    "qor_metrics.min_pulse_width_violations"]},
            ],
            "parasitic_annotation": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.non_vacuous_parasitic_annotation",
                    "validation.checks.three_distinct_nonempty_spefs"]},
                # A second, REAL dialect (<myDesign-B>.1/sta.13 e.g.) has no
                # `validation.checks` block at all but DOES record how many
                # distinct corner SPEFs were annotated
                # (`signoff_evidence.descriptive.spef_corners`). Three
                # corners (tt/ss/ff) is this campaign's genuine multi-corner
                # signoff population, so >=3 -- not merely >0 -- is the real
                # closing condition; `exclusive_floor` with floor=2 makes
                # "value>2" i.e. "at least 3" the pass condition.
                {"kind": "exclusive_floor", "floor": 2, "paths": [
                    "signoff_evidence.descriptive.spef_corners"]},
            ],
            "constraint_coverage": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.constraint_coverage.fully_constrained",
                    "validation.checks.zero_unconstrained_endpoints"]},
                {"kind": "count", "paths": [
                    "signoff_evidence.constraint_coverage.unconstrained_endpoints"]},
            ],
            "propagated_clock": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.propagated_clock_count_one",
                    "signoff_evidence.signoff_population."
                    "propagated_clock_command_executed"]},
            ],
            # Real, genuinely-checked additional obligations this attempt
            # records (`qor_metrics.recovery_violations` etc., all present
            # and zero) that the original nine never named -- kept as
            # ADDITIONS beyond the required nine, never a replacement for
            # any of them, per the "never fabricate a family to pad, never
            # drop a named family" rule.
            "recovery": [
                {"kind": "count", "paths": ["qor_metrics.recovery_violations"]},
            ],
            "removal": [
                {"kind": "count", "paths": ["qor_metrics.removal_violations"]},
            ],
            "clock_gating_setup": [
                {"kind": "count", "paths": [
                    "qor_metrics.clock_gating_setup_violations"]},
            ],
            "clock_gating_hold": [
                {"kind": "count", "paths": [
                    "qor_metrics.clock_gating_hold_violations"]},
            ],
            # <TaskID> (item 3, wave 2b): MEASURED on `<myTopDesign>.1/sta-pre-
            # dft.2` -- a distinct pre-layout scan-shift STA dialect (no
            # `qor_metrics.wns_ns`) that names three obligations the
            # post-route dialect above never records: a functional-mode
            # slow-corner setup check, a positive-path-population non-
            # vacuity guard, and a shift-mode hold-assessability guard.
            "functional_setup": [
                {"kind": "neg_slack", "unit": "ns", "paths": [
                    "results.functional_slow_setup_wns"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.slow_corner_setup_wns_nonnegative"]},
            ],
            "non_vacuity": [
                {"kind": "exclusive_floor", "floor": 0, "paths": [
                    "results.work_count", "qor_metrics.work_count"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.positive_path_work_count"]},
            ],
            "shift_hold_assessability": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.shift_hold_assessable",
                    "signoff_evidence.shift_hold_assessable"]},
            ],
        },
        # The pre-layout gate is setup-only by AMEND-PRELAYOUT-STA-SCOPE-001.
        # DRV remains measured and reviewable, but placement/CTS/routing owns its
        # repair and post-route STA owns its gate. Keeping this in the registry --
        # rather than hard-coding STA in compute_progress -- makes the flow-position
        # contract explicit and testable alongside the family declaration.
        "flow_scopes": {
            "pre_layout_estimate": {
                "gate": "setup_timing",
                "deferred_family_groups": ["drv", "parasitics"],
                "deferred_to": "post_cts_post_route_sta",
            },
        },
    },
    "eco": {
        # The ECO stage's gate is the SAME gate as STA's -- it exists only to
        # close STA's residual -- so it shares the residual family. Reusing the
        # key matters: the effort framework compares an ECO wave's residual
        # against the STA attempt that triggered it, and a differently-named
        # metric would make that trajectory unreadable.
        "metric_id": "total_negative_slack",
        "neg_slack": ["tns_ns", "setup_tns_ns", "worst_tns_ns", "wns_ns"],
        "direct": ["violating_paths", "failing_endpoints"],
        # Same per-check families as `sta`: ECO repairs a SUBSET of them
        # (setup/hold/max_tran/max_cap/max_fanout) and can only DETECT the
        # rest. A detect-only family reports None -> _record_named SKIPS it,
        # so "no repair engine exists" can never be stamped as a clean 0.
        # KEPT for the `<myDesign-B>.1/eco.4` (rejected, not currently swept)
        # dialect, which records these under LITERAL dotted-string keys
        # (`"physical_drv.max_transition"`, one flat key, not nested) that
        # `obligation_families`'s dotted-PATH resolver (`_find_dotted`, which
        # splits on every `.` and walks nested dicts) cannot address -- the
        # bare leaf-name search this mechanism uses still can.
        "named_families": {
            "drv.max_tran": ["max_transition_violations",
                             "physical_drv.max_transition"],
            "drv.max_cap": ["max_capacitance_violations",
                            "physical_drv.max_capacitance"],
            "drv.max_fanout": ["max_fanout_violations",
                               "physical_drv.max_fanout"],
            "drv.min_pulse_width": ["min_pulse_width_violations"],
            "drv.min_period": ["min_period_violations"],
            "drv.max_skew": ["max_skew_violations"],
            "drv.recovery": ["recovery_violations"],
            "drv.removal": ["removal_violations"],
            "drv.clock_gating_setup": ["clock_gating_setup_violations"],
            "drv.clock_gating_hold": ["clock_gating_hold_violations"],
        },
        "named_family_unit": "violations",
        "population": ["analyzed_paths", "endpoints"],
        "primary_family": "slack_ns", "unit_count": "paths",
        "unit": "ns", "kind": "continuous", "iterating": True,
        # <TaskID>: MEASURED on `<myDesign-A>.1/eco.1` (the CURRENT pointer) --
        # its `mandatory_checks` block is a NESTED dialect
        # (`mandatory_checks.max_transition.violations`, `.setup.worst_slack_
        # ns`, ...), a different shape from `named_families`'s flat-leaf
        # aliases above, none of which this attempt's fields match. The nine
        # obligations the census found collapsing to a bare `slack_ns`/`count`
        # pair are each backed by their own exact key here. `obligation_unit`
        # is `violations` (the DRV-count obligations' real unit); `setup`/
        # `hold` override to `ns` per-recipe since a slack obligation is
        # measured in a different unit than a violation count.
        "obligation_unit": "violations",
        # Family names deliberately MATCH the `drv.`/`timing.` prefixes
        # `named_families` already used above (and the existing pinned
        # attempt's own recorded progress block) -- a rename to unprefixed
        # names is a NAMED-SET diff even when the underlying obligation is
        # identical, and `finalize_cde.py --fix`'s basis-narrowing guard
        # (correctly) refused to regenerate <myDesign-A>.1/eco.1 the first
        # time this recipe used bare names for exactly that reason.
        "obligation_families": {
            "timing.setup": [
                {"kind": "neg_slack", "unit": "ns", "paths": [
                    "mandatory_checks.setup.worst_slack_ns",
                    "qor_metrics.terminal_setup_wns_ns"]},
            ],
            "timing.hold": [
                {"kind": "neg_slack", "unit": "ns", "paths": [
                    "mandatory_checks.hold.worst_slack_ns",
                    "qor_metrics.terminal_hold_wns_ns"]},
            ],
            "drv.max_tran": [
                {"kind": "count", "paths": [
                    "mandatory_checks.max_transition.violations"]},
            ],
            "drv.max_cap": [
                {"kind": "count", "paths": [
                    "mandatory_checks.max_capacitance.violations"]},
            ],
            "drv.max_fanout": [
                {"kind": "count", "paths": [
                    "mandatory_checks.max_fanout.violations"]},
            ],
            "drv.recovery": [
                {"kind": "count", "paths": [
                    "mandatory_checks.recovery.violations"]},
            ],
            "drv.removal": [
                {"kind": "count", "paths": [
                    "mandatory_checks.removal.violations"]},
            ],
            "drv.clock_gating_setup": [
                {"kind": "count", "paths": [
                    "mandatory_checks.clock_gating_setup.violations"]},
            ],
            "drv.clock_gating_hold": [
                {"kind": "count", "paths": [
                    "mandatory_checks.clock_gating_hold.violations"]},
            ],
        },
    },
    "drc": {
        "metric_id": "unwaived_drc_violations",
        "direct": ["unwaived_violations", "violation_count", "violations",
                   "drc_violations"],
        "population": ["rules_checked", "checked_shapes"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        "named_families": {
            "drc_violations": ["unwaived_violations", "violation_count",
                               "violations", "drc_violations"],
        },
        # <TaskID> (item 3, wave 2b): MEASURED on `<myDesign-A>.1/drc.3` -- its
        # dual-engine dialect names TWO per-engine obligations (`klayout`,
        # `magic`), each independently a real, non-vacuous DRC run, sourced
        # from `qor_metrics.klayout_violations`/`magic_violations` (real
        # per-engine counts) with the dialect's own `validation.checks.*`
        # non-vacuity/zero-unwaived booleans as a second alias.
        # `<myDesign-B>.1/drc.4` collapses both engines into one `qor_metrics.
        # per_engine.{klayout,magic}` count pair under the shared `count`/
        # `drc_violations` families above (no separate names to preserve).
        "obligation_unit": "violations",
        "obligation_families": {
            "klayout": [
                {"kind": "count", "paths": ["qor_metrics.klayout_violations",
                                            "qor_metrics.per_engine.klayout"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unwaived_klayout"]},
            ],
            "magic": [
                {"kind": "count", "paths": ["qor_metrics.magic_violations",
                                            "qor_metrics.per_engine.magic"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unwaived_magic"]},
            ],
        },
    },
    "lvs": {
        "metric_id": "lvs_mismatches",
        "direct": ["mismatched_devices", "mismatched_nets", "property_mismatches",
                   "mismatches"],
        "population": ["total_devices", "total_nets"],
        "unit": "mismatches", "kind": "discrete", "iterating": True,
        # Device / net / property mismatches have different causes: a device
        # mismatch is usually a netlist or extraction problem, a net mismatch a
        # connectivity one, a property mismatch a parameter one.
        "named_families": {
            "lvs_device_mismatch": ["mismatched_devices"],
            "lvs_net_mismatch": ["mismatched_nets"],
            "lvs_property_mismatch": ["property_mismatches"],
        },
        # <TaskID> (item 3, wave 2b): MEASURED on `<myDesign-A>.1/lvs.3` -- its
        # dialect flattens each mismatch class under its OWN bare name
        # (`device_mismatches`, `net_mismatches`, `property_mismatches`,
        # `port_mismatches`) rather than the `mismatched_*` spelling the
        # `named_families` above alias, and additionally names a `port`
        # obligation (named-port count reconciliation) neither `direct` nor
        # `named_families` covers at all.
        "obligation_unit": "mismatches",
        "obligation_families": {
            "device": [
                {"kind": "count", "paths": ["results.device_mismatches"]},
            ],
            "net": [
                {"kind": "count", "paths": ["results.net_mismatches"]},
            ],
            "property": [
                {"kind": "count", "paths": ["results.property_mismatches"]},
            ],
            "port": [
                {"kind": "count", "paths": ["results.port_mismatches"]},
            ],
        },
    },
    "antenna": {
        "metric_id": "antenna_violations",
        "direct": ["unwaived_violations", "violation_count", "violations"],
        "population": ["checked_nets"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        # <TaskID> (item 3, wave 3): MEASURED on `<myDesign-A>.1/antenna.5` --
        # three causally distinct obligations (the antennacheck run itself,
        # a no-self-waiver guard, and a persisted-artifact completeness
        # guard), each recorded under its own `validation.checks.*` boolean.
        # `<myDesign-B>.1/antenna.2` has no `validation.checks` block at all and
        # relies on the shared `qor_metrics.unwaived_violations` count above.
        "obligation_unit": "violations",
        "obligation_families": {
            "magic_antennacheck": [
                {"kind": "count", "paths": [
                    "qor_metrics.unwaived_violations",
                    "qor_metrics.antenna_erc_violations"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.unwaived_violations_zero"]},
            ],
            "waivers": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.no_waivers"]},
            ],
            "persistence": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.raw_reports_nonempty",
                    "validation.checks.all_expected_checks_ran",
                    "validation.checks.per_check_counts_complete"]},
            ],
        },
    },
    "routing": {
        "metric_id": "routing_violations",
        "direct": ["shorts", "drc_violations", "open_nets", "unrouted_nets",
                   "violations"],
        "population": ["total_nets", "routed_nets"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        # <TaskID> (item 3, wave 2b): MEASURED on `<myDesign-A>.1/routing.16`
        # (the blessed pointer) -- its hand-authored `progress.families`
        # names 7 obligations, sourced from a `validation.checks.*` boolean
        # dialect (no plain `direct` numerics for most of them). Without a
        # real recipe, `--fix` cannot reproduce this basis and
        # `finalize_cde.py`'s <TaskID> guard correctly refuses to regenerate it
        # (reports an unrepairable "P basis-narrowed" defect) rather than
        # silently collapsing to `count`. Every name below is sourced from
        # the exact boolean the attempt's own `note` cites for that
        # obligation.
        "obligation_unit": "violations",
        "obligation_families": {
            "routing_drc": [
                {"kind": "count", "paths": ["results.drc_violations.value",
                                            "qor_metrics.drc_violations"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.terminal_drc_zero"]},
            ],
            "connectivity": [
                {"kind": "count", "paths": ["results.opens.value"]},
                {"kind": "count", "paths": ["results.shorts.value"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.opens_zero"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.shorts_zero"]},
            ],
            "pin_access": [
                {"kind": "count", "paths": [
                    "results.pin_access_errors.value"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.pin_access_coded_errors_zero"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.openroad_coded_errors_zero"]},
            ],
            "congestion": [
                {"kind": "count", "paths": [
                    "results.congestion_overflow.value"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.gcell_overflow_zero"]},
            ],
            "power": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.unconnected_power_ground_pins_zero"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.pdn_geometry_preserved"]},
            ],
            "handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.lef_handoff_pass"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.gds_handoff_pass"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.cdl_handoff_present"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.complete_terminal_handoff"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.three_corner_spefs_complete"]},
            ],
            "upstream_continuity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.canonical_cts_6_consumed"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.canonical_cts_self_hash_verified"]},
            ],
            # <TaskID> (item 3, wave 5): MEASURED on `<myDesign-B>.1/routing.4`, a
            # DISTINCT hand-authored dialect (source paths are LOG FILE
            # references, not JSON keys) whose family NAMES don't match the
            # <myDesign-A> dialect above at all (`routing_cleanliness` vs.
            # `connectivity`+`routing_drc`, `clock_handoff`/
            # `power_connectivity`/`interfaces` have no equivalent above).
            # Aliasing onto the SAME real recorded keys those log-derived
            # numbers summarize (results.opens/shorts/drc_violations,
            # results.unconnected_pg_pins, results.incomplete_boundary_
            # interfaces, and the matching validation.checks.* booleans).
            "routing_cleanliness": [
                {"kind": "count", "paths": [
                    "results.opens.value", "results.shorts.value",
                    "results.drc_violations.value"]},
            ],
            "clock_handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_clock_nets_routed",
                    "validation.checks.propagated_clock_present"]},
            ],
            "power_connectivity": [
                {"kind": "count", "paths": ["results.unconnected_pg_pins.value"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.power_grid_connected",
                    "validation.checks.unconnected_pg_pins_zero"]},
            ],
            "interfaces": [
                {"kind": "count", "paths": [
                    "results.incomplete_boundary_interfaces.value"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.boundary_interfaces_connected",
                    "validation.checks.boundary_pin_access_complete"]},
            ],
        },
    },
    "placement": {
        "metric_id": "placement_violations",
        "direct": ["overlapping_instances", "illegal_instances",
                   "unplaced_instances"],
        "population": ["total_instances"],
        "unit": "instances", "kind": "discrete", "iterating": True,
        # <TaskID> (item 3, wave 2b): MEASURED, three genuinely different
        # per-design dialects: `<myDesign-A>.1/placement.4` (6 named families
        # sourced from flat `validation.checks.*`), `<myTopDesign>.1/
        # placement.6` (3 named families, same nesting), and `<myDesign-B>.1/
        # placement.7` (single collapsed `count` family, unaffected -- no
        # named family exists to drop there). Every name below is sourced
        # from the exact real check each attempt's own dialect records.
        "obligation_unit": "instances",
        "obligation_families": {
            "legality": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.every_logic_instance_placed"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_site_misalignment"]},
            ],
            "overlap": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_overlaps"]},
            ],
            "core_containment": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.floorplan_boundary_preserved"]},
            ],
            "fixed_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_fixed_taps_endcaps_unchanged"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.fixed_taps_endcaps_site_legal"]},
            ],
            "connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.connectivity_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.netlist_unchanged"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.power_rails_preserved"]},
            ],
            "handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.opendb_roundtrip_identical"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.raw_def_validation_pass"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.raw_opendb_validation_pass"]},
            ],
            "placement_legality": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_unplaced_or_illegal"]},
            ],
            # `<myTopDesign>.1/placement.6`'s dialect carries no per-check
            # `validation.checks.*` breakdown at all (only a root
            # verdict/`literal_pass`/`gate_closed`) -- its 3 named families
            # are instead backed by the `qor_metrics`/`results` fields its own
            # note cites ("all fixed-pad transforms, placement legality,
            # population, connectivity, and pinned-LEF transformed geometry
            # checks pass").
            "connectivity_preservation": [
                {"kind": "count", "paths": [
                    "results.pad_transform.orientation_changes"]},
                {"kind": "count", "paths": [
                    "results.pad_transform.tangential_order_changes"]},
            ],
            "pad_control_pin_access": [
                {"kind": "count", "paths": [
                    "qor_metrics.movable_logic_obstruction_overlaps"]},
                {"kind": "count", "paths": [
                    "qor_metrics.gpiov2_source_rectangles_without_access"]},
            ],
            # <TaskID> (re-dispatch): sky130_fd_sc_hd standard cells declare
            # FOUR PG-sigtype MTerms, not two (VPWR+VPB power, VGND+VNB
            # ground). `connectivity` above only ever asked whether VPWR/VGND
            # reconnection survived placement -- it has no path that can see
            # a VPB/VNB body-tie gap, so a placement attempt that fixes the
            # body-tie connectivity had nowhere to record a REAL obligation
            # for it, and finalize_cde.py's basis-narrowing guard would
            # otherwise treat that new family as data loss on every future
            # attempt. ADDITIVE only: an attempt without this check simply
            # does not bind (`not_assessable`, never a false pass).
            "body_tie_connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_body_ties_connected"]},
            ],
        },
    },
    "cts": {
        # SKEW IS DIAGNOSTIC, NOT GATING.
        #
        # This entry previously declared `metric_id: clock_skew_ns`, which made
        # the raw skew measurement the closing metric. That was wrong on two
        # counts:
        #   * Every other metric_id in this registry names a DEFECT QUANTITY
        #     that converges to zero (unwaived_violations, failing_tests,
        #     lvs_mismatches). A raw measurement has no "closed" state, so the
        #     gate could never close -- a metric that cannot reach zero is
        #     indistinguishable from one that never converges.
        #   * Skew is a signed magnitude. Neither residual family fits it:
        #     `direct` would read -0.5 ns as "better than closed", and
        #     `neg_slack` would read +0.5 ns of skew as zero residual, even
        #     though positive skew is just as harmful as negative.
        # The gate is `skew_violations` -- skew judged AGAINST A BUDGET. Skew
        # itself stays reported as a diagnostic, useful whether or not the gate
        # passes, and never converted into a residual.
        # The gate is "every valid clock got buffers added or resized", counted
        # per clock from the TritonCTS log. `unbuffered_clocks` converges to 0
        # and is genuinely closable, unlike the raw skew measurement.
        "metric_id": "unbuffered_clocks",
        "direct": ["unbuffered_clocks", "skew_violations"],
        "neg_slack": ["clock_slack_ns"],
        "population": ["sinks", "clock_sinks"],
        # `clock_skew` / `clock_skew_ns` are deliberately absent from every
        # residual list above. That is the classification, not an oversight:
        # a null residual here means "the budgeted gate was not evaluated",
        # which must NOT be satisfied by substituting the raw measurement.
        # `clock_buffers` (a DEF-wide master count) is likewise NOT a gate: it
        # cannot tell an inserted buffer from a pre-existing one.
        "primary_family": "count", "unit_count": "violations",
        "unit": "violations", "kind": "discrete", "iterating": True,
        # <TaskID> (item 3, wave 2b): the top-level `skew_violations`/`direct`
        # family above stays the SCALAR primary. Three genuinely different
        # per-design dialects each also name several real obligations this
        # module previously collapsed on regeneration:
        # `<myDesign-B>.1/cts.7` (5 names, `validation.checks.*` booleans),
        # `<myDesign-A>.1/cts.6` (4 names, budget-vs-measured `gap` obligations
        # PLUS `results`/`qor_metrics` raw counts -- no `checks` breakdown
        # exists in this dialect), and `<myTopDesign>.1/cts.3` (10 names, mixed
        # `validation.checks.*` booleans and `qor_metrics` counts). `skew`'s
        # budget is read from the PRODUCER'S OWN recorded parameter
        # (`attempt_capture.parameters.clock_skew_limit_ns` / the sibling
        # `results.clock_skew.limit`) via the `gap` kind (residual =
        # max(0, measured-limit)) -- never a threshold this module invents.
        "obligation_unit": "violations",
        "obligation_families": {
            "clock_connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.every_sdc_clock_buffered"]},
            ],
            "clock_skew": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.clock_skew_within_limit",
                    "validation.checks.skew_within_0p25ns"]},
            ],
            "flop_count": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.flop_count_preserved_33"]},
            ],
            "physical_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_illegal_or_misaligned"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_overlaps"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.zero_out_of_core"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.fixed_taps_endcaps_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.rows_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.power_rails_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.nonclock_connectivity_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.macro_local_vccd_vssd_pdn_preserved"]},
            ],
            "insertion_delay": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.insertion_delay_numeric_not_gating"]},
                {"kind": "string_startswith_ok", "accept": ("not_gating",),
                 "paths": ["results.insertion_delay_disposition",
                           "qor_metrics.insertion_delay_classification",
                           "results.insertion_delay.classification"]},
            ],
            "skew": [
                {"kind": "gap", "unit": "ns",
                 "population_paths": ["results.setup_skew_ns",
                                       "qor_metrics.setup_clock_skew.value",
                                       "results.clock_skew.value",
                                       "qor_metrics.clock_skew_ns"],
                 "achieved_paths": [
                     "attempt_capture.parameters.clock_skew_limit_ns",
                     "results.clock_skew.limit",
                     "qor_metrics.clock_skew_limit_ns"]},
                {"kind": "gap", "unit": "ns",
                 "population_paths": ["results.hold_skew_ns",
                                       "qor_metrics.hold_clock_skew.value"],
                 "achieved_paths": [
                     "attempt_capture.parameters.clock_skew_limit_ns"]},
            ],
            "cell_policy": [
                {"kind": "count", "paths": [
                    "results.unapproved_inserted_count"]},
            ],
            "supply_intent": [
                {"kind": "count", "paths": [
                    "qor_metrics.functional_net_mismatches"]},
                {"kind": "count", "paths": [
                    "qor_metrics.special_net_mismatches"]},
            ],
            "handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.post_cts_def_nonempty"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.post_cts_odb_nonempty"]},
            ],
            "real_cts_work": [
                {"kind": "exclusive_floor", "floor": 0, "paths": [
                    "results.tritoncts_created_buffers",
                    "qor_metrics.tritoncts_created_buffers"]},
            ],
            "placement_legality": [
                {"kind": "count", "paths": [
                    "qor_metrics.placement_violations"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.post_cts_placement_legal"]},
            ],
            "functional_connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_nonclock_connectivity_preserved"]},
            ],
            "special_net_connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.special_net_connectivity_preserved"]},
            ],
            "pad_and_macro_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.gpiov2_pad_positions_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.macro_positions_preserved"]},
            ],
            "physical_clock_root_and_constraints": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.physical_clock_root"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.clock_period_20ns"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.clock_uncertainty_0p05ns"]},
            ],
            "propagated_clock_handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.propagated_clock_handoff"]},
            ],
            "approved_clock_cells": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.approved_clock_buffer_only"]},
            ],
        },
    },
    "power-ir": {
        "metric_id": "ir_drop_violations",
        "direct": ["ir_violations", "em_violations", "violations"],
        "population": ["analyzed_nodes"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        # <TaskID> (item 5, wave 5): the bare `count` family above collapsed
        # FIVE causally distinct obligations `chip-power-ir` genuinely
        # checks -- MEASURED on `<myDesign-A>.1/power.1`/`.2` and
        # `<myDesign-B>.1/power.2`: every attempt's own hand-authored on-disk
        # `progress.families` already carries `power`/`static_ir`/
        # `activity`/`connectivity`/`em`, none of which `direct`/`population`
        # above ever matched (its aliases -- `ir_violations`/
        # `analyzed_nodes` -- appear nowhere in this producer's real
        # `schema: chip-power-ir-aggregate/1` output). Each family below is
        # sourced from a real recorded key: the `SR-09x_*` gating booleans
        # this stage's own `validation.checks` block publishes for exactly
        # these obligations, backed by the matching `qor_metrics` counts.
        "obligation_families": {
            "power": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.SR-090_tt_core_power"]},
                {"kind": "count", "paths": ["qor_metrics.power_overage_w"]},
            ],
            "static_ir": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.SR-092_tt_static_ir_voltage_and_fraction"]},
                {"kind": "count", "paths": ["qor_metrics.ir_drop_violations"]},
            ],
            "activity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.nonzero_activity_annotation_all_corners"]},
            ],
            "connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.power_grid_connectivity_all_corners"]},
            ],
            "em": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.SR-093_zero_em_violations"]},
                {"kind": "count", "paths": [
                    "qor_metrics.em_violations",
                    "qor_metrics.em_unresolved_observed_layers"]},
            ],
        },
    },
    "pdn": {
        "metric_id": "pdn_connectivity_violations",
        # `floating_power_nets` is what the TOOL ACTUALLY EMITS. Measured on a
        # real sandbox run: the tool returned floating_power_nets /
        # specialnets_vias / pdn_stripe_layers / boundary_power_pins and NONE of
        # the three names previously declared here, so a clean PDN reported
        # residual=None -- unmeasurable rather than measured-and-closed. Same
        # false-absence class as the synthesis and assertions alias gaps.
        # The old names are KEPT so another producer still resolves.
        "direct": ["violations", "disconnected_nets", "psm_errors",
                   "floating_power_nets",
                   # <TaskID>: MEASURED on `<myDesign-A>.1/pdn.5` -- the tool's
                   # own top-level `results.open_power_nets` /
                   # `results.power_ground_shorts` counts (present on every
                   # current pdn attempt) are the SAME connectivity-defect
                   # quantity `floating_power_nets`/`violations` name, just
                   # under the name this image actually emits.
                   "open_power_nets", "power_ground_shorts"],
        # Deliberately NOT residuals, each checked for direction before exclusion:
        #   specialnets_vias   -- a COUNT OF VIAS BUILT; PSM is the authoritative
        #                         connectivity check (a via_gap heuristic already
        #                         produced a false positive here once, overriding a
        #                         real PSM pass).
        #   pdn_stripe_layers  -- metal-stack CONFIG, constant by construction.
        #   boundary_power_pins-- HIGHER-IS-BETTER; declaring it would invert
        #                         progress (more pins = further from closure).
        #
        # `pdn_stripe_layers` is ALSO excluded from `population`. It was previously
        # listed there, and `_find` takes the FIRST name present, so an attempt with
        # no `power_nets` field closed its gate reporting
        # `denominator_source: results.pdn_stripe_layers` -- a metal-stack constant
        # (5 for this node on every attempt, connected or not) standing in as the
        # denominator of a PG-CONNECTIVITY gate, while `power_connectivity`,
        # `pg_pin_reach` and `macro_boundary` all sat `not_assessable`. A denominator
        # that cannot move in the failure direction the obligation cares about is a
        # reusable false-green template, and the comment above already said this
        # value was config rather than measurement; `population` simply did not
        # honour it.
        "population": ["power_nets", "boundary_power_pins"],
        "unit": "violations", "kind": "discrete", "iterating": True,
        # <TaskID>: MEASURED on `<myDesign-B>.1/pdn.5` -- its `signoff_evidence`
        # carries a `diagnostic_methodology_note` that the producer's OWN
        # documented derivation path for exactly the "zero open power nets /
        # zero failed vias" claim relies on `results.floating_power_nets`,
        # which this attempt does NOT actually publish anywhere (verified: no
        # such key exists in its envelope). That is a self-contradictory
        # evidentiary trail -- the producer's own disclosed methodology gap
        # for its primary check, not a naming near-miss -- so the newly added
        # `open_power_nets`/`power_ground_shorts` aliases above must NOT be
        # read as gating evidence for an attempt that discloses this gap.
        # `<myDesign-A>.1/pdn.5` carries no such note and binds normally.
        "suppress_evidence_if_present": ["diagnostic_methodology_note"],
        # <TaskID>: the shared `count` family above collapsed THREE causally
        # distinct obligations `chip-pdn` genuinely checks -- MEASURED on
        # `<myDesign-B>.1/pdn.5` / `<myDesign-A>.1/pdn.5`, both of which record all
        # three inline in `results`/`validation.checks`. Deliberately excludes
        # BOTH the open-power-net pair (`open_power_nets`/`floating_power_nets`)
        # AND `power_ground_shorts`/`zero_power_ground_shorts` -- the
        # `suppress_evidence_if_present` note above withholds the whole
        # `violations`-unit `direct`/`population` family (both aliased source
        # names together) for an attempt that discloses the methodology gap,
        # and a family sourced from either of those same keys would silently
        # re-admit the disputed evidence through an unguarded second path.
        # The three families below are backed by PG-pin/row reach counts and
        # the macro-boundary-exposure check the note never disputes.
        #
        # <TaskID> (REOPENED, item 2, THE PDN.5 DECISION): `suppress_evidence_
        # if_present_obligations` is declared here as the EMPTY set --
        # meaning none of `power_connectivity`/`pg_pin_reach`/
        # `macro_boundary` is covered by the disclosed gap, and all three
        # bind normally even on an attempt that discloses it. Decision and
        # evidence trail (do not re-derive this by assertion later):
        #   - `<myDesign-B>.1/pdn.5`'s own `assumptions[]` attributes the gap to
        #     ONE PINNED chip-pdn IMAGE BUILD used for THIS attempt whose
        #     `pdn_utils.py` no longer runs the legacy `-check_only`/
        #     `-report_only`/`-failed_via_report` sequence -- it is a
        #     property of which build got pinned for this run, NOT a
        #     permanent property of the `pdn` stage/obligation model: the
        #     sibling `<myDesign-A>.1/pdn.5`, pinned to a build that still
        #     emits the legacy keys, carries no such note at all. ATTEMPT-
        #     SCOPED, not obligation-model-scoped.
        #   - The disclosure text itself names EXACTLY two derived claims as
        #     affected (`zero_open_power_nets`, `zero_failed_vias`), both
        #     already withheld unconditionally by `suppress_evidence_if_
        #     present` acting on the `direct`/`population` family above. It
        #     never mentions `standard_cell_pg_iterms_*`, `rows_*`, or
        #     `macro_power_boundary_exposed` -- separate fields, present and
        #     identical in shape/origin on BOTH the old and new image
        #     dialects (verified: `<myDesign-B>.1/pdn.4`, built on the OLDER
        #     image, and `<myDesign-A>.1/pdn.5` both carry them the same way
        #     `<myDesign-B>.1/pdn.5` does).
        # Continuing to blanket-suppress all three would be the identical
        # silent-narrowing defect this task exists to fix, just enacted via
        # an over-wide guard instead of an under-wide recipe: a disclosure
        # about one specific, already-withheld claim would otherwise also
        # discard three fully-evidenced, undisputed obligations.
        "suppress_evidence_if_present_obligations": [],
        "obligation_families": {
            "power_connectivity": [
                {"kind": "gap",
                 "population_paths": ["results.standard_cell_pg_iterms_expected"],
                 "achieved_paths": ["results.standard_cell_pg_iterms_connected"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_standard_cell_pg_pins_reached"]},
            ],
            "pg_pin_reach": [
                {"kind": "gap", "population_paths": ["results.rows_total"],
                 "achieved_paths": ["results.rows_reached"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_standard_cell_rows_reached"]},
            ],
            "macro_boundary": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.macro_power_boundary_exposed"]},
            ],
            # <TaskID> (ADDITIVE): a genuinely distinct obligation from
            # `power_connectivity` above. `power_connectivity`/`pg_pin_reach`
            # both require PLACED x/y coordinates (physical reach-to-rail);
            # this family requires none -- it is pure NETLIST connectivity
            # (does every instance's VPWR/VGND ITerm resolve to the design's
            # single VPWR/VGND net?), which is checkable the moment a
            # `global_connect`/pdngen pass has run, before placement.
            #
            # WHY THIS FAMILY EXISTS: in this campaign `pdn` runs BEFORE
            # `tapcell` (reverse of the ORFS reference order). OpenROAD
            # resolves a DEF SPECIALNETS `( * NET )` wildcard against the
            # netlist's instance set AT READ TIME and serializes an explicit
            # (or, once uniform again, a re-collapsed wildcard) iterm list
            # on write -- so a `pdn` attempt's own wildcard-based global
            # connect can only ever bind the instances that already exist in
            # ITS OWN input DEF. The `tapcell` stage's own `pg_preservation`
            # family (see `"tapcell"` below) checks only whether the
            # PRE-EXISTING PDN was destroyed, with the ORIGINAL (pre-tapcell)
            # instance set as its denominator -- cells a LATER stage inserts
            # are structurally invisible to it. Population/achieved MUST be
            # sourced against the FULL, current post-tapcell/post-fill
            # instance count this specific pdn attempt actually read as
            # input (`results.pg_reconcile_total_instances`), never the
            # count the ORIGINAL pdn attempt in the chain started from --
            # otherwise this family would silently reproduce the exact
            # blind spot it exists to close.
            "pg_global_connect_reconciliation": [
                {"kind": "gap",
                 "population_paths": ["results.pg_reconcile_iterms_expected"],
                 "achieved_paths": ["results.pg_reconcile_iterms_connected"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_post_tapcell_instances_pg_connected"]},
            ],
            # PSM CONNECTIVITY -- OpenROAD's own solver result, not a derived proxy.
            #
            # Every family above is an ITerm/row-reach COUNT or a netlist-level
            # boolean. None of them is sourced from `check_power_grid`, even though
            # that is the most direct electrical evidence a PDN closes and `chip-pdn`
            # has published it since its earliest attempts. Measured: an attempt that
            # wanted to residual-track PSM had to hand-invent a family name (which
            # `gen_campaign_versions.py` correctly rejected as `basis_narrowed`) or
            # drop the obligation from progress entirely -- a silent narrowing of the
            # real electrical obligation with no rejection to catch it.
            #
            # `bools_by_shape` is used rather than a path list because the per-net
            # flag is named for the DESIGN'S SUPPLY NET (`psm_vccd_connected` on one
            # design, `psm_vpwr_connected` on another). Enumerating net names in this
            # registry would reintroduce exactly the "only the names someone typed"
            # defect that left VPB/VNB floating. The net-agnostic `psm_verified` /
            # `psm_all_supply_nets_connected` booleans bind first when present.
            # ADDITIVE: an attempt publishing no PSM evidence stays `not_assessable`,
            # never a false pass.
            "psm_connectivity": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.psm_all_supply_nets_connected",
                    "signoff_evidence.psm_verified",
                    "qor_metrics.psm_verified"]},
                {"kind": "bools_by_shape",
                 "blocks": ["validation.checks", "qor_metrics", "signoff_evidence"],
                 "prefix": "psm_", "suffix": "_connected"},
            ],
            # Every PG-sigtype instance terminal resolves to a net after
            # `global_connect`. PSM cannot see this: it checks the geometry of the
            # nets that EXIST, so a terminal never bound to a net is simply absent
            # from its model -- measured, PSM reported both nets fully connected
            # while every standard cell's body/well tie floated, for four stages.
            "pg_terminal_binding": [
                {"kind": "count", "paths": [
                    "results.pg_terminals_unconnected.value",
                    "results.pg_terminals_unconnected",
                    "qor_metrics.unconnected_pg_terminals"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_pg_terminals_connected"]},
            ],
        },
    },
    "dft": {
        "metric_id": "dft_gate_defects",
        # <TaskID> REWORK: `chip-dft` checks roughly TEN distinct obligations
        # (input provenance, scannability, hazard freedom, insertion
        # correctness, structural re-elaboration, scan-disabled equivalence,
        # chain integrity, emitted-netlist shift simulation, frozen scan
        # ports, reset preservation) -- MEASURED from the two real dialects
        # this tool has produced (`<myDesign-A>.1/dft.5`'s
        # `signoff_evidence.*` sub-blocks, `<myDesign-B>.1/dft.3`'s
        # `signoff_evidence.*` + flat `validation.*_exact`/`*_zero`/`*_pass`
        # booleans). A single `direct: [broken_chains, orphan_flops,
        # shared_flops, ...]` list collapsed all ten into one `count` family
        # built from chain-integrity counters alone -- residual/gate_closed
        # stayed 0/true while every other obligation silently left the basis
        # (the <TaskID> regression this rework fixes; a hand-authored 10-family
        # block existed for `<myDesign-A>.1/dft.5` before <TaskID> replaced it).
        #
        # `obligation_families` derives ONE family per obligation from EXACT
        # dotted fact paths (never a bare leaf-name search -- `match` and
        # `verdict` each recur under multiple unrelated sub-blocks in this
        # tool's own envelopes, so a leaf-name search would silently bind the
        # wrong one). Each family lists every alias path BOTH measured
        # dialects actually emit; a family with no bound path is recorded
        # `not_assessable` (see the merge in `compute_progress`), never
        # dropped -- e.g. `<myDesign-B>.1/dft.3` never ran a reset-preservation
        # check at all, so that family reports not_assessable there while it
        # is genuinely closed (verdict pass) on `<myDesign-A>.1/dft.5`.
        "obligation_families": {
            "input_provenance": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.input_provenance.match",
                    "validation.mapped_netlist_content_hash_verified",
                ]},
            ],
            "scannability": [
                {"kind": "gap",
                 "population_paths": ["results.sequential_elements",
                                       "results.total_sequential"],
                 "achieved_paths": ["results.eligible_scan_flops",
                                     "results.eligible_flops"]},
            ],
            "hazards": [
                {"kind": "count", "paths": [
                    "results.latches", "results.async_hazards",
                    "results.other_hazards", "results.async_set_reset_hazards",
                    "signoff_evidence.hazards.latch",
                    "signoff_evidence.hazards.async_set_reset",
                    "signoff_evidence.hazards.gated_or_other",
                ]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_hazards_zero",
                ]},
            ],
            "insertion": [
                {"kind": "gap",
                 "population_paths": ["results.eligible_scan_flops",
                                       "results.eligible_flops"],
                 "achieved_paths": ["results.emitted_scan_flops",
                                     "results.scan_cells_emitted"]},
                {"kind": "target_delta", "target": 1.0, "paths": [
                    "results.scan_insertions",
                    "signoff_evidence.insertion.count",
                    "signoff_evidence.insertion.invocation_count",
                ]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.exactly_one_insertion",
                    "signoff_evidence.frozen_scan_ports.exact_match",
                ]},
            ],
            "structural": [
                {"kind": "count", "paths": [
                    "signoff_evidence.structural_re_elaboration.multiple_drivers",
                    "signoff_evidence.structural_re_elaboration.undriven_nets",
                    "signoff_evidence.structural_re_elaboration.unresolved_cells",
                    "signoff_evidence.structural_re_elaboration.unintended_blackboxes",
                    "signoff_evidence.structural_reelaboration.multiple_drivers",
                    "signoff_evidence.structural_reelaboration.undriven_nets",
                    "signoff_evidence.structural_reelaboration.unresolved_cells",
                    "signoff_evidence.structural_reelaboration.unintended_blackboxes",
                ]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.structural_reelaboration_pass",
                ]},
            ],
            "equivalence": [
                {"kind": "count", "paths": [
                    "results.equivalence_unproven_points",
                    "results.unproven_equivalence_points",
                    "signoff_evidence.scan_disabled_equivalence.unproven_points",
                ]},
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.scan_disabled_equivalence.proven",
                    "signoff_evidence.functional_equivalence.proven",
                    "validation.scan_disabled_equivalence_pass",
                ]},
            ],
            "chain_integrity": [
                # NOTE: `qor_metrics.broken_chains/orphan_flops/shared_flops` is
                # a THIRD dialect (the `scan-integrity` stage aliases into this
                # same registry key, per _STAGE_ALIASES, and reports chain
                # counters flat under qor_metrics rather than under
                # results/signoff_evidence). It must stay listed or every
                # scan-integrity attempt regresses from alignment "ok" to a
                # blocking metric_defect the moment this registry entry is
                # regenerated against it (<TaskID> follow-on discovery).
                {"kind": "count", "paths": [
                    "results.broken_chains", "results.orphan_flops",
                    "results.shared_flops",
                    "signoff_evidence.chain_integrity.broken",
                    "signoff_evidence.chain_integrity.orphan",
                    "signoff_evidence.chain_integrity.shared",
                    "qor_metrics.broken_chains", "qor_metrics.orphan_flops",
                    "qor_metrics.shared_flops",
                ]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.broken_orphan_shared_zero",
                    "validation.zero_breaks",
                ]},
            ],
            "shift_simulation": [
                {"kind": "count", "paths": ["results.netlist_shift_failures"]},
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.actual_emitted_netlist_shift_simulation.bit_exact",
                    "validation.actual_emitted_netlist_shift_simulation_pass",
                ]},
                {"kind": "string_pass_ok", "paths": [
                    "qor_metrics.netlist_shift_simulation",
                ]},
            ],
            "frozen_ports": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.scan_ports.exact_match",
                    "signoff_evidence.frozen_scan_ports.exact_match",
                    "validation.frozen_scan_ports_exact",
                ]},
            ],
            "reset_preservation": [
                # `chip-dft` only runs a reset-preservation gate-level sim when
                # the attempt actually reconciles a reset value (measured:
                # present on `<myDesign-A>.1/dft.5`, absent from
                # `<myDesign-B>.1/dft.3`, which never checked it). Genuinely
                # not_assessable when absent -- never fabricated as clean.
                {"kind": "string_pass_ok", "paths": [
                    "signoff_evidence.reset_preservation.verdict",
                ]},
            ],
        },
        # TEST coverage (detected / TESTABLE, untestables credited) is the ATPG
        # signoff gate. fault_coverage (detected / ALL faults) is deliberately
        # NOT gate-driving: at 100% test coverage with enumerated redundant
        # faults, fault_coverage sits below 100% by exactly the untestable
        # fraction, so listing it here made the percent_gap family disagree with a
        # legitimately-closed gate (a blocking metric-defect on a clean run --
        # observed on <TaskID>). It is reported in the CDE as advisory, never here.
        "pct_to_100": ["test_coverage", "test_coverage_pct"],
        # <TaskID>: the meaningful basis is the ELIGIBLE-FLOP population these
        # obligation families are actually checked against, not an ATPG-only
        # fault count neither measured dialect emits under this stage (that
        # left `denominator: null` on every real dft attempt). `faults_tested`
        # / `scan_flops` are kept as a trailing fallback for a future
        # ATPG-merged dft dialect.
        "population": ["eligible_scan_flops", "eligible_flops",
                        "scannable_ff", "scannable_flops",
                        "sequential_elements", "total_sequential",
                        "faults_tested", "scan_flops"],
        "primary_family": "chain_integrity", "obligation_unit": "defects",
        "unit": "defects", "kind": "continuous", "iterating": True,
    },
    "assertions": {
        "metric_id": "unusable_assertions",
        "direct": ["vacuous_properties", "vacuous_or_trivial", "vacuous",
                   "formal_checkability_fail", "missing_vplan_linkage",
                   # <TaskID> REWORK: near-miss producer field names (MEASURED
                   # on assertions.1 <myDesign-B>.2/<myDesign-A>.1) -- same
                   # "count of assertions that are not usable evidence"
                   # semantics, just spelled differently by this producer.
                   "structurally_vacuous", "vacuous_count",
                   "trivial_property_count", "formally_uncheckable_count",
                   "unlinked_property_count"],
        # MEASURED 2026-09-02: 2 of 4 completed attempts had residual=null. The
        # count aliases above match NOTHING chip-assertion-generation emits -- it
        # reports its gate as PERCENTAGES (compile / elaboration / measured
        # reachability), and this entry declared no `pct_to_100` list at all, so
        # there was nothing for the extractor to find.
        #
        # *** DIRECTION CHECK. *** The tool's counts -- authored_assertions,
        # compiled_assert_cells, integrated_assert_cells, antecedents_reached --
        # are all HIGHER-IS-BETTER and are deliberately NOT declared as
        # residuals: reading one as a residual inverts progress, so "more
        # properties integrated" would register as "further from closure".
        "pct_to_100": ["syntax_compile_pct",
                       "integrated_property_elaboration_pct",
                       "measured_antecedent_reachability_pct",
                       "measured_cover_reachability_pct",
                       "cover_reachability_pct", "bmc_pass_pct"],
        "population": ["assertions_authored", "authored", "properties_screened",
                       "authored_assertions"],
        # The count family stays PRIMARY: a vacuity count states unusable
        # properties directly, whereas a percentage is a ratio whose denominator
        # can move. When the tool emits no counts, percent_gap carries it.
        "primary_family": "count", "unit_count": "assertions",
        "unit": "assertions", "kind": "discrete", "iterating": True,
        # A vacuous property, an unlinked property and a formally-uncheckable one
        # are three different authoring defects.
        "named_families": {
            "vacuous_properties": ["vacuous_properties", "vacuous_or_trivial",
                                   "vacuous"],
            "formal_checkability": ["formal_checkability_fail"],
            "vplan_linkage": ["missing_vplan_linkage"],
        },
        # <TaskID> (WAVE 1, item 1): ADDITIVE to the `named_families` above --
        # <myTopDesign>.1/assertions.14's hand-authored `progress` block already
        # carries four families (intent_coverage, vacuity, formal_soundness,
        # reachability) that group the SAME per-VR obligations
        # chip-assertion-generation actually checks (intent-point traceability,
        # non-vacuity, formal BMC soundness, cover reachability) one level
        # coarser than the three `named_families` above. `finalize_cde --fix`
        # refused to regenerate it because the machine-derived set (`count` +
        # `vacuous_properties` + `vplan_linkage`, MEASURED) does not contain
        # any of those four names, so re-stamping the CDE (needed only to
        # refresh its dangling `inputs_ref.upstream_simulation_self_hash`)
        # would have silently dropped them. These recipes are declared
        # alongside -- never replacing -- `named_families` so BOTH sets of
        # names keep binding; nothing above is removed.
        "obligation_families": {
            # Every VR row the tool touched must land >=1 assert + >=1 cover;
            # a missing point is a named, unwaived hole (MEASURED:
            # `results.intent_points_missing`, class=gating, closes_at="== 0",
            # on <myTopDesign>.1/assertions.14). `applicable_intent_groups` /
            # `covered_intent_groups` is the <myDesign-A> dialect's own
            # intent-group tracking (MEASURED on <myDesign-A>.1/assertions.1);
            # `intent_points_enumerated` / `intent_points_authored` is the
            # <myTopDesign> dialect's OWN denominator/numerator pair, kept as a
            # `gap` fallback for a future attempt that stops emitting the
            # already-summarized `intent_points_missing` directly.
            "intent_coverage": [
                {"kind": "count", "paths": ["results.intent_points_missing"]},
                {"kind": "gap",
                 "population_paths": ["results.applicable_intent_groups",
                                       "results.intent_points_enumerated"],
                 "achieved_paths": ["results.covered_intent_groups",
                                     "results.intent_points_authored"]},
            ],
            # Same underlying facts as the `vacuous_properties`/
            # `vplan_linkage` named_families above, folded into ONE coarser
            # family so a consumer reading `progress.families.vacuity` (the
            # name <myTopDesign>.1/assertions.14 already publishes) keeps
            # resolving after a re-derive.
            "vacuity": [
                {"kind": "count", "paths": [
                    "results.vacuous", "results.vacuous_properties",
                    "results.vacuous_or_trivial", "results.vacuous_count",
                    "results.trivial_property_count",
                    "results.missing_vplan_linkage",
                    "results.unlinked_property_count"]},
            ],
            # DELIBERATELY EXCLUDED: `results.bmc_assert_failures` /
            # `results.bmc_failures`. MEASURED on <myTopDesign>.1/assertions.14,
            # `bmc_assert_failures` is 1 (VR-205's DESIGNED, ACCEPTED
            # non-vacuity proof -- an assert built to fail so the harness is
            # provably not vacuous) and is tagged `class: diagnostic` by the
            # producer for exactly that reason: reading it as a residual
            # here would count an intentional, accepted proof-of-non-vacuity
            # as an unsound property and flip this attempt's gate from
            # closed to open on the strength of a check working as designed.
            # `formal_checkability_fail` / `formally_uncheckable_count` (both
            # `class: gating`, `closes_at: "== 0"`) and the isolated-BMC/
            # prove-status dispositions below are the safe, already-isolated
            # substitutes.
            "formal_soundness": [
                {"kind": "count", "paths": [
                    "results.formal_checkability_fail",
                    "results.formally_uncheckable_count"]},
                {"kind": "string_pass_ok", "paths": ["results.prove_status"]},
                {"kind": "string_startswith_ok",
                 "paths": ["signoff_evidence.bmc_isolated.result"]},
            ],
            "reachability": [
                {"kind": "string_pass_ok", "paths": ["results.cover_status"]},
                {"kind": "string_startswith_ok",
                 "paths": ["signoff_evidence.cover.result"]},
            ],
            # <TaskID> (item 3, wave 5): MEASURED on `<myTopDesign>.1/assertions.11`
            # -- a THIRD assertions dialect (distinct from both the
            # `named_families` numerics above and assertions.14's
            # `intent_coverage`/`vacuity`/`formal_soundness`/`reachability`
            # grouping): `native_vacuous`/`traced_assertions`/
            # `nonconstant_antecedents`/`companion_cover_targets`/
            # `reached_cover_targets`/`unhit_cover_targets`/
            # `unapproved_waivers`, none of which the `direct`/`pct_to_100`
            # lists above match. Its on-disk hand-authored `progress` already
            # names 7 obligations this way; none of them bound to a fresh
            # recompute before this fix (metric_id=unusable_assertions found
            # NO source key at all, so the gate force-closed False on total
            # non-binding, not because of a real defect).
            "compile_failures": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_properties_compile"]},
            ],
            "untraced_assertions": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_assertions_traced"]},
                {"kind": "gap",
                 "population_paths": ["results.native_authored_assertions",
                                       "results.source_assertions"],
                 "achieved_paths": ["results.traced_assertions"]},
            ],
            "constant_antecedents": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_antecedents_nonconstant"]},
                # <TaskID> REWORK. The population here is the count of
                # ANTECEDENT-GATED assertions, which is NOT
                # `results.traced_assertions` -- that key is a VPLAN-TRACEABILITY
                # count ("how many authored asserts trace to a requirement") and
                # is already the ACHIEVED value of `untraced_assertions` above.
                # Reusing it as this family's denominator made the two families
                # share one key under two incompatible semantics, and was only
                # ever correct for a dialect in which every traced assertion
                # happened to be an implication.
                #
                # MEASURED, both error directions:
                #   <myDesign-A>.1/assertions.1 authors 8 implications AND 2 plain
                #   unconditional invariants (AST-101, AST-112), so the old gap
                #   read 10-8=2 and reported the ONLY open family on an attempt
                #   with BMC PASS, cover PASS and 3/3 red-then-green mutation
                #   probes -- a false `blocking` on clean evidence.
                #   <myTopDesign>.1/assertions.1 runs it the other way: traced (7)
                #   is SMALLER than nonconstant_antecedents (8), so the gap went
                #   negative and was clamped to 0 -- the family "closed" on an
                #   arithmetically meaningless comparison rather than evidence.
                #
                # A plain invariant has no antecedent, so it can never contribute
                # a constant one; only implications belong in this denominator.
                # A dialect that emits no implication count leaves this gap
                # UNBOUND -- the `bool_true_ok` above still assesses the family,
                # and if that is absent too the family goes not-assessable rather
                # than closing on an invented population.
                {"kind": "gap",
                 "population_paths": ["results.temporal_implications",
                                       "results.implication_assertions",
                                       "results.antecedent_gated_assertions"],
                 "achieved_paths": ["results.nonconstant_antecedents"]},
            ],
            "missing_cover_targets": [
                {"kind": "gap",
                 "population_paths": ["results.companion_cover_targets"],
                 "achieved_paths": ["results.reached_cover_targets"]},
            ],
            "unhit_cover_targets": [
                {"kind": "count", "paths": ["results.unhit_cover_targets"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_cover_targets_reached"]},
            ],
            "missing_behavior_categories": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.all_required_behaviors_have_cover_targets"]},
            ],
            "unapproved_waivers": [
                {"kind": "count", "paths": ["results.unapproved_waivers"]},
            ],
        },
    },
    "testbench": {
        "metric_id": "testbench_smoke_failures",
        # `missing_vplan_linkage` is load-bearing here, not decorative. The tool
        # declares it GATING, but it was absent from this list, so the extractor
        # never saw it and settled on the clean sibling `smoke_failures` -- a
        # scaffold with an unlinked component reported residual 0.0 while
        # FAILING. That is the inverse-laundering shape: residual 0 reads as a
        # CLOSED gate to a scalar consumer and as a CONVERGED metric to the
        # stall machinery. A gating label the extractor cannot reach is
        # decorative.
        "direct": ["mismatches", "failures", "compile_errors", "smoke_failures",
                   "missing_vplan_linkage"],
        "population": ["executed_comparisons", "smoke_tests_passed", "tests",
                       "tests_executed", "total_checks"],
        # NOTE: a named-family split (smoke_failures vs vplan_linkage) would let
        # reopen-repertoire route a compile failure and an untraced component to
        # DIFFERENT causal owners, which is worth doing. It is deliberately NOT
        # done here: adding a family is a THREE-FILE change (cde_progress emit ->
        # reopen-repertoire route -> vocabulary retrieve) and `smoke_failures` is
        # not yet in residual_class_map, so declaring it would make the family
        # unreachable to causal selection. The reachability defect this entry
        # fixes does not require the split.
        "unit": "failures", "kind": "discrete", "iterating": True,
    },
    "streamout-xor": {
        # Geometric XOR between two independent streamouts. ANY differing shape
        # is a fail, so the count IS the residual.
        #
        # `difference_area_um2` is deliberately NOT listed here: area is a
        # different unit, and putting it in the same family as a count is the
        # exact unit-mixing defect that once let a 5x timing regression read as
        # an improvement. Zero differing shapes implies zero differing area, so
        # the count alone closes the gate.
        "metric_id": "layout_xor_differences",
        "direct": ["difference_count", "differences", "xor_differences"],
        "population": ["layers_compared", "compared_cells"],
        "unit": "differences", "kind": "discrete", "iterating": True,
    },
    "integrity": {
        "metric_id": "critical_integrity_violations",
        "direct": ["total_critical_violations", "critical_violations"],
        "population": ["checks_assessed"],
        "unit": "violations", "kind": "discrete", "iterating": True,
    },
    # Non-iterating / declarative stages: re-running does not move a metric.
    "opendb": {"metric_id": None, "kind": "unavailable", "iterating": False},
    # `partition` (catalog/policy/stage-roles.json role_id "partition") is a
    # campaign-level, dir_token-null authoring stage: it produces a
    # specification-traced macro/physical-build mapping document, not a scalar
    # metric or a family of obligations, and stage-roles.json declares its
    # `progress_key` as null -- a DECLARED absence, same class as `opendb`/`pdk`
    # below. Without this entry, `normalize_stage("partition")` returned None
    # entirely (no registry match at all), which finalize_cde.py correctly
    # flags as an "absent basis" DEFECT distinct from a declared one: a
    # dependency-gate consumer cannot tell "no metric exists for this stage
    # type" from "this stage type was never taught to the registry".
    "partition": {"metric_id": None, "kind": "unavailable", "iterating": False},
    # Directory + CDE scaffolding is a one-shot structural backbone stage, exactly
    # like `partition`/`pdk`/`gds`/`opendb` above: its gate closes on the finalized
    # root verdict, not on an iterable defect residual (the campaign tree is either
    # scaffolded to contract or it is not; re-running cannot "improve" a metric).
    # Was MISSING entirely, so `normalize_stage("scaffold")` returned None and every
    # scaffold CDE degraded to the unrepairable `P absent-basis` defect, which a
    # dependency-gate consumer (dispatch_control.py) correctly refuses -- stranding
    # every RTL head that depends on the Scaffolding leaf. Added as `unavailable`
    # to mirror the sibling backbone stages; purely additive.
    "scaffold": {"metric_id": None, "kind": "unavailable", "iterating": False},
    "spec": {
        # WAS `metric_id: None` (deliberately unmeasurable). MEASURED 2026-09-02:
        # all 4 COMPLETED spec attempts carried residual=null even though every
        # envelope reports `non_measurable`, `duplicates` and `untraced` -- three
        # counts that must reach ZERO for the specification to be usable, plus
        # three closure percentages. Spec IS measurable; nobody had declared it.
        #
        # *** DIRECTION IS THE TRAP HERE. *** `requirements` (142) is the
        # POPULATION, not a residual -- declaring it would peg the residual at
        # 142 forever and the gate could never close. Likewise
        # `frozen_contracts`/`signal_pads`/`golden_vectors` are inventory that
        # SHOULD grow. Only the must-reach-zero defect counts are residuals.
        "metric_id": "unusable_requirements",
        "direct": ["non_measurable", "duplicates", "untraced"],
        "pct_to_100": ["requirement_coverage_pct", "traceability_pct",
                       "contract_completion_pct"],
        "population": ["requirements"],
        "primary_family": "count", "unit_count": "records",
        "unit": "records", "kind": "discrete", "iterating": True,
        # A non-measurable requirement, a duplicate and an untraced one are
        # repaired by different edits, so they do not share one family.
        "named_families": {
            "non_measurable_requirements": ["non_measurable"],
            "duplicate_requirements": ["duplicates"],
            "untraced_requirements": ["untraced"],
        },
        # <TaskID> (item 3, wave 5): MEASURED on the blessed `spec.11` pointer
        # for all 3 designs -- a NEWER spec dialect (requirements_total /
        # requirements_in_scope / duplicate_ids / unqualified_ids /
        # missing_owner / missing_target / missing_evidence_producer /
        # unresolved_ambiguities / missing_handoffs / unapproved_waivers /
        # silent_defaults) that the `direct`/`named_families` lists above
        # never matched (they look for `duplicates`/`untraced`, not
        # `duplicate_ids`/the split ownership+target+evidence-producer
        # obligations). The on-disk hand-authored `progress` block already
        # named `ambiguity`/`traceability`/`handoff_completeness`; a fresh
        # recompute previously produced a DIFFERENT, narrower family set
        # (bare `count`/`non_measurable_requirements`), which is exactly
        # the silent-narrowing `finalize_cde --fix` basis-narrowing guard
        # exists to catch -- it was refusing to write, not succeeding.
        # <TaskID> iteration 3 (<campaign-slug>/spec.1, MEASURED): `missing_target`
        # (a requirement with no section-11.2 NUMERIC metric) is an over-broad
        # GATING population -- the spec never mandates every requirement carry
        # one, and most of the 70 flagged that way are verified by a spec-
        # stated NON-numeric route instead (a 4-column table's own
        # "Verification method" column, or a section-10.3 "Required
        # assertions" entry). `results.unusable_requirements` is the PROVEN,
        # narrower population -- a requirement with NO verification route of
        # ANY kind -- and is what should drive `traceability`'s residual/
        # source. `missing_target`/`missing_evidence_producer` remain real,
        # reported measurements (a stage that regresses on them is still
        # visible), just moved to their own `diagnostic_only_families` entry
        # so a coverage-completeness reading never masks nor dominates the
        # actual gating obligation the way a bare max() over one family would
        # (a family's residual/source is the WORST single component, and 70
        # would otherwise always beat a real, smaller, still-open 5).
        "obligation_unit": "records",
        "diagnostic_only_families": ["numeric_metric_coverage"],
        "obligation_families": {
            "ambiguity": [
                {"kind": "count", "paths": ["results.unresolved_ambiguities"]},
            ],
            "traceability": [
                {"kind": "count", "paths": [
                    "results.duplicate_ids", "results.unqualified_ids",
                    "results.missing_owner", "results.unusable_requirements"]},
            ],
            "numeric_metric_coverage": [
                {"kind": "count", "paths": [
                    "results.missing_target", "results.missing_evidence_producer"]},
            ],
            "handoff_completeness": [
                {"kind": "count", "paths": ["results.missing_handoffs"]},
            ],
            "waiver_hygiene": [
                {"kind": "count", "paths": ["results.unapproved_waivers"]},
            ],
            "silent_defaults": [
                {"kind": "count", "paths": ["results.silent_defaults"]},
            ],
        },
    },
    # <TaskID> (PRIORITY 0): `vplan` had NO STAGE_RESIDUALS entry or alias at
    # all -- `normalize_stage("vplan")` returned None, so `finalize_cde`
    # skipped progress derivation ENTIRELY and a `progress: null` block was
    # invisible to the closure check, while `dispatch_control.py` (correctly)
    # refused every downstream consumer with "dependency gate is not closed".
    # MEASURED on `<myTopDesign>.1/vplan.3` and `<myDesign-A>.1/vplan.3` -- both
    # carry all four obligations inline in `results` (vplan.1/vplan.2's
    # `progress` blocks were themselves HAND-AUTHORED against a single ad hoc
    # `count` family; this recipe derives what the CDE actually records
    # instead of copying that shape).
    "vplan": {
        "metric_id": "vplan_gate_defects",
        "obligation_families": {
            # Compatibility name used by vplan.1/vplan.2. It is the same real
            # missing-owner obligation as `owner_coverage`, retained so the
            # richer recipe is additive rather than basis-narrowing.
            "count": [
                {"kind": "list_len", "paths": [
                    "results.missing_required_owners"]},
            ],
            # Every requirement row the plan touched must resolve to a named
            # owner; an unresolved question blocks downstream planning.
            "open_questions": [
                {"kind": "count", "paths": ["results.unresolved_questions"]},
            ],
            "owner_coverage": [
                {"kind": "list_len", "paths": [
                    "results.missing_required_owners"]},
            ],
            "role_published": [
                {"kind": "bool_true_ok", "paths": ["results.role_published"]},
            ],
            "semantic_review": [
                {"kind": "string_pass_ok", "paths": [
                    "results.semantic_review"]},
            ],
            # A vplan revision that changed a plan_item's criterion,
            # applicability or owner must re-bless every downstream gate that
            # was adjudicated against the superseded vplan; a non-empty list
            # here means that reconciliation has not happened yet.
            "downstream_reblessing": [
                {"kind": "list_len", "paths": [
                    "results.downstream_reblessing_required"]},
            ],
        },
        "population": ["plan_items_total"],
        "primary_family": "open_questions", "obligation_unit": "defects",
        "unit": "defects", "kind": "discrete", "iterating": True,
    },
    "domain-map": {
        "metric_id": "domain_map_defects",
        "direct": [
            "unresolved_questions",
            "schema_semantic_defects",
            "provenance_defects",
            "publication_defects",
        ],
        "primary_family": "count",
        "unit": "defects",
        "kind": "discrete",
        "iterating": True,
        "named_families": {
            "domain_map_intent": ["unresolved_questions"],
            "domain_map_schema": ["schema_semantic_defects"],
            "domain_map_provenance": ["provenance_defects"],
            "domain_map_publication": ["publication_defects"],
        },
    },
    "pdk": {"metric_id": None, "kind": "unavailable", "iterating": False},
    "gds": {"metric_id": None, "kind": "unavailable", "iterating": False,
             # <TaskID> (item 3, wave 3): MEASURED on `<myDesign-A>.1/gds.4` --
             # a rich final-assembly dialect names EIGHT causally distinct
             # signoff families under `validation.families_closed.*`
             # (streamout, stream_xor, inventory, drc, lvs, antenna, power,
             # handoff), each an independent boolean recording whether that
             # signoff domain closed as part of THIS assembly attempt.
             # `<myDesign-B>.1/gds.4` has no `families_closed` block; its only
             # inline, genuinely-checked obligation is a positive named-port
             # count (a `class: gating` leaf under `results.pin_labels`,
             # already read generically by `_find_gating_leaf` elsewhere --
             # named here explicitly so it survives as its own family rather
             # than needing that fallback).
             "obligation_unit": "closed",
             "obligation_families": {
                 "streamout": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.streamout",
                         "validation.checks.native_tool_completed"]},
                 ],
                 "stream_xor": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.stream_xor",
                         "validation.checks.independent_xor_clean"]},
                 ],
                 "inventory": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.inventory",
                         "validation.checks.gds_def_inventory_exact"]},
                 ],
                 "drc": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.drc",
                         "validation.checks.drc_closed"]},
                 ],
                 "lvs": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.lvs",
                         "validation.checks.lvs_closed"]},
                 ],
                 "antenna": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.antenna",
                         "validation.checks.antenna_closed"]},
                 ],
                 "power": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.power",
                         "validation.checks.power_closed"]},
                 ],
                 "handoff": [
                     {"kind": "bool_true_ok", "paths": [
                         "validation.families_closed.handoff",
                         "validation.checks.handoff_complete"]},
                 ],
                 "named_ports": [
                     {"kind": "count", "unit": "unlabelled_ports", "paths": [
                         "qor_metrics.ports_unlabelled"]},
                 ],
             }},
    # Extraction's gate is CORNER COVERAGE, not a raw measurement.
    # `nets_extracted` is deliberately NOT a residual: it is a MEASUREMENT that
    # scales with design size and has no closed state (a bigger design simply
    # has more nets), so declaring it would peg the residual forever. The
    # closable defect quantity is "how many corners the node declares are still
    # unextracted", which converges to 0 -- a partial SPEF set cannot support
    # multi-corner STA or power, and that shortfall must be measurable rather
    # than inferred from the absence of a complaint.
    "extraction": {
        "metric_id": "unextracted_corners",
        "direct": ["unextracted_corners"],
        "population": ["corners_extracted", "nets_extracted"],
        "unit": "corners", "kind": "discrete", "iterating": True,
        # <TaskID> (item 5, wave 5): the bare `count` family above collapsed
        # THREE causally distinct obligations `chip-parasitic-extraction`
        # genuinely checks -- MEASURED on `<myDesign-A>.1/extraction.8`,
        # whose own hand-authored on-disk `progress` already carries
        # `corner_coverage`/`native_execution`/`handoff`, none of which a
        # fresh recompute reproduced (a raw `compute_progress()` call
        # confirmed it collapses to `['count']` alone), so `finalize_cde
        # --fix` was silently REFUSING to write this attempt at all. Each
        # family below is sourced from a real recorded key: the
        # corner-completion pair (`corners_extracted`/`corners_required`
        # or `unextracted_corners`), the container/log positive-work
        # checks this stage's own `validation.checks` block records, and
        # the terminal/macro handoff-preservation booleans.
        "obligation_families": {
            "corner_coverage": [
                {"kind": "count", "paths": ["results.unextracted_corners"]},
                {"kind": "gap",
                 "population_paths": ["results.corners_required"],
                 "achieved_paths": ["results.corners_extracted"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_corners_completed"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_corners_pass"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.three_binding_corners"]},
            ],
            # <TaskID> note: each boolean below is a SEPARATE recipe entry
            # (not a single multi-path entry) deliberately -- `bool_true_ok`
            # resolves its `paths` list first-match-wins (they are meant as
            # aliases for ONE fact), and these six are six INDEPENDENT
            # container/log checks that must each individually hold, not
            # alternate spellings of a single check. One entry per path
            # means all six are actually examined and their residuals sum.
            "native_execution": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_container_exit_codes_zero"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_containers_not_oom_killed"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_native_logs_positive"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_spefs_nonempty"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_net_counts_positive"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.native_extraction_work_count_positive"]},
            ],
            "handoff": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.terminal_handoff_complete"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.filled_physical_database_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.macro_handoff_inventory_preserved"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.flop_count_preserved_33"]},
            ],
        },
    },
    # atpg has THREE independently-authored dialects on disk, none of which were
    # ever machine-derived by this module ("atpg" was absent from
    # _STAGE_ALIASES/STAGE_RESIDUALS -- normalize_stage("atpg") returned None --
    # so every existing atpg progress block, including the hand-authored
    # count/percent_gap one that mislabels stage_key as "dft", was authored
    # outside this pipeline). Every family below is sourced from a real
    # qor_metrics count or a real validation.* boolean; nothing is fabricated.
    "atpg": {
        "metric_id": "atpg_gate_defects",
        "direct": ["undetected_testable", "undetected_testable_faults", "aborted"],
        "unit": "faults",
        "kind": "discrete",
        "iterating": True,
        "obligation_families": {
            # <myDesign-B>.4 dialect name -- population coverage + untestable disposition.
            "completeness": [
                {"kind": "count", "unit": "faults", "paths": ["qor_metrics.aborted"]},
                {"kind": "bool_true_ok", "paths": ["validation.full_fault_population_covered_by_shards"]},
                {"kind": "bool_true_ok", "paths": ["validation.all_shards_present"]},
                {"kind": "bool_true_ok", "paths": ["validation.every_untestable_fault_dispositioned"]},
            ],
            # <myDesign-A>.4 dialect name -- tested vs declared total population.
            "population": [
                {"kind": "gap", "unit": "faults",
                 "population": ["qor_metrics.faults_total_population", "qor_metrics.fault_population"],
                 "achieved": ["qor_metrics.faults_tested"]},
                {"kind": "bool_true_ok", "paths": ["validation.full_population_tested"]},
                {"kind": "bool_true_ok", "paths": ["validation.population_reconciled"]},
            ],
            # shared by both real dialects -- undetected testable faults / coverage goal.
            "coverage": [
                {"kind": "count", "unit": "faults",
                 "paths": ["qor_metrics.undetected_testable", "qor_metrics.undetected_testable_faults"]},
                {"kind": "gap", "unit": "faults",
                 "population": ["qor_metrics.testable", "qor_metrics.detectable"],
                 "achieved": ["qor_metrics.detected"]},
                {"kind": "bool_true_ok", "paths": ["validation.coverage_goal_met"]},
                {"kind": "bool_true_ok", "paths": ["validation.undetected_testable_zero"]},
                {"kind": "bool_true_ok", "paths": ["validation.detected_testable_coverage_at_least_99_pct"]},
            ],
            "aborted": [
                {"kind": "count", "unit": "faults", "paths": ["qor_metrics.aborted"]},
                {"kind": "bool_true_ok", "paths": ["validation.aborted_faults_zero"]},
                {"kind": "bool_true_ok", "paths": ["validation.aborted_zero"]},
            ],
            "untestable_dispositions": [
                {"kind": "bool_true_ok", "paths": ["validation.every_untestable_fault_dispositioned"]},
                {"kind": "bool_true_ok", "paths": ["validation.every_untestable_fault_enumerated"]},
                {"kind": "bool_true_ok", "paths": ["validation.all_untestable_faults_enumerated_and_dispositioned"]},
                {"kind": "bool_true_ok", "paths": ["validation.all_untestable_sat_unsat_dispositioned"]},
            ],
            "patterns": [
                {"kind": "bool_true_ok", "paths": ["validation.real_stuck_at_patterns_generated"]},
                {"kind": "bool_true_ok", "paths": ["validation.real_nonempty_patterns"]},
                {"kind": "bool_true_ok", "paths": ["validation.real_vcd_witnesses_complete"]},
                {"kind": "bool_true_ok", "paths": ["validation.all_detected_faults_have_patterns"]},
            ],
            "grading": [
                {"kind": "gap", "unit": "shards",
                 "population": ["qor_metrics.shards_required"],
                 "achieved": ["qor_metrics.shards_completed"]},
                {"kind": "bool_true_ok", "paths": ["validation.all_native_pattern_grading_complete"]},
            ],
            # <myDesign-B>.4 dialect name -- agent-minted-waiver and generated-liberty policy.
            "policy": [
                {"kind": "bool_true_ok", "paths": ["validation.no_agent_minted_waivers"]},
                {"kind": "bool_true_ok", "paths": ["validation.no_waiver"]},
                {"kind": "bool_true_ok", "paths": ["validation.generated_liberty_files_zero"]},
                {"kind": "count", "unit": "files", "paths": ["qor_metrics.generated_liberty_files"]},
            ],
            # <myTopDesign> top-level-scope-only obligation, genuinely absent for
            # <myDesign-A> block-scope attempts -- surfaces not_assessable there.
            "scan_assumptions": [
                {"kind": "bool_true_ok", "paths": ["validation.full_scan_assumptions_verified"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.macro_segment_controllability_observability_verified"]},
            ],
            # legacy hand-authored dialect name (<myTopDesign>.8): the on-disk
            # component key ("signoff_evidence.test_coverage_pct(gap_to_goal)")
            # is an arithmetic expression over a field that DOES NOT EXIST in
            # this CDE (there is no `signoff_evidence` block at all), so the
            # original value is not reproducible. This real substitute traces
            # the same "tested faults vs testable population" gap the coverage
            # family already covers, under the legacy name so a fresh recompute
            # does not drop it.
            "percent_gap": [
                {"kind": "gap", "unit": "faults",
                 "population": ["qor_metrics.testable_faults", "qor_metrics.testable",
                                "qor_metrics.detectable"],
                 "achieved": ["qor_metrics.detected"]},
                {"kind": "bool_true_ok", "paths": ["validation.coverage_goal_met"]},
            ],
        },
    },
    # gls (gate-level simulation) has THREE dialects: <myDesign-A>'s binds a rich
    # set of class:gating results fields but never named its families; <myDesign-B>'s
    # hand-authored dialect mislabels stage_key as "funcverif" and names its
    # lone family "count"; <myTopDesign>'s names families "mission"/"scan". All
    # three are preserved below, plus additional per-obligation families sourced
    # from real results.* fields for <myDesign-A>'s richer dialect.
    "gls": {
        "metric_id": "gls_gate_failures",
        "direct": ["failures", "mismatches", "x_failures", "error_lines",
                   "scoreboard_mismatches", "total_mismatches", "tests_failed"],
        "bool_ok": ["sim_passed"],
        "unit": "failures",
        "kind": "discrete",
        "iterating": True,
        "obligation_families": {
            # <myTopDesign>.2 dialect names.
            "mission": [
                {"kind": "count", "unit": "failures",
                 "paths": ["results.mission_mismatches"]},
                {"kind": "count", "unit": "failures",
                 "paths": ["results.post_reset_functional_x_failures"]},
            ],
            "scan": [
                {"kind": "count", "unit": "failures", "paths": ["results.scan_mismatches"]},
                {"kind": "count", "unit": "failures", "paths": ["results.scan_x_failures"]},
            ],
            "x_propagation": [
                {"kind": "count", "unit": "detections", "paths": ["results.x_failures"]},
                {"kind": "count", "unit": "detections",
                 "paths": ["results.functional_output_xz_detections_after_reset"]},
            ],
            "golden_vectors": [
                {"kind": "declared_threshold", "unit": "vectors",
                 "paths": ["results.functional_vectors_passed"]},
            ],
            "scan_sim_integrity": [
                {"kind": "declared_threshold", "unit": "chains",
                 "paths": ["results.scan_chains_passed"]},
                {"kind": "declared_threshold", "unit": "flops",
                 "paths": ["results.scan_chain_length"]},
            ],
            "timebase_fidelity": [
                {"kind": "declared_threshold", "unit": "ps ticks",
                 "paths": ["results.timebase_observed"]},
            ],
            "liberty_hygiene": [
                {"kind": "count", "unit": "files", "paths": ["results.generated_liberty_files"]},
            ],
        },
    },
    # decap-fill has THREE dialects: <myDesign-B>'s blessed pointer carries no
    # families at all (bare gate_closed), crc16.6's names five families
    # (binding/connectivity/legality/row_closure/upstream_continuity), and
    # crc16.1's older attempt named three (legality/preservation/row_fill).
    # All named families across every dialect are preserved below, each
    # sourced from a real validation.checks.* boolean or qor_metrics count.
    "decap-fill": {
        "metric_id": "decap_fill_violations",
        "direct": ["overlap_pairs", "legal_row_gaps", "unplaced_instances"],
        "unit": "violations",
        "kind": "discrete",
        "iterating": True,
        "obligation_families": {
            "legality": [
                {"kind": "count", "unit": "violations",
                 "paths": ["qor_metrics.overlap_pairs"]},
                {"kind": "count", "unit": "violations",
                 "paths": ["qor_metrics.legal_row_gaps"]},
                {"kind": "count", "unit": "violations",
                 "paths": ["qor_metrics.unplaced_instances"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.zero_overlap_pairs"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.zero_legal_row_gaps"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.zero_unplaced_instances"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.zero_site_misaligned_fillers"]},
            ],
            "connectivity": [
                {"kind": "bool_true_ok", "paths": ["validation.checks.normal_net_connectivity_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.special_net_connectivity_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.wildcard_pg_connectivity_preserved"]},
            ],
            "binding": [
                {"kind": "bool_true_ok", "paths": ["validation.checks.only_binding_fill_masters_inserted"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.openroad_fill_count_matches"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.pdk_binding_hash_exact"]},
            ],
            "row_closure": [
                {"kind": "count", "unit": "gaps", "paths": ["qor_metrics.legal_row_gaps"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.zero_legal_row_gaps"]},
            ],
            "upstream_continuity": [
                {"kind": "bool_true_ok", "paths": ["validation.checks.all_original_instances_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.routing_def_hash_exact"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.routing_netlist_hash_exact"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.constraints_lineage_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.cts_lineage_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.placement_lineage_preserved"]},
            ],
            # older <myDesign-A>.1 dialect name -- required endcaps/tapcells preserved.
            "preservation": [
                {"kind": "bool_true_ok", "paths": ["validation.checks.required_row_endcaps_present"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.required_endcaps_preserved"]},
                {"kind": "bool_true_ok", "paths": ["validation.checks.required_taps_preserved"]},
            ],
            # older <myDesign-A>.1 dialect name -- gap-fill obligation, distinct
            # spelling from row_closure so both names survive.
            "row_fill": [
                {"kind": "count", "unit": "gaps", "paths": ["qor_metrics.legal_row_gaps"]},
            ],
        },
    },
    # metal-fill gates on DENSITY-WINDOW violations, NOT on a fill-shape count.
    # A fill COUNT is a measurement with no closed state (more fill is not "closer
    # to done"), and it scales with die size -- declaring it would peg the residual
    # forever. The defect quantity is a layer whose density is OUTSIDE its window.
    # `density_hard_violations` is computed by the tool from the PDK's own density
    # rules and is already the thing its verdict turns on: on sky130A a MAXIMUM
    # density overage is a hard DRC error, while a MINIMUM shortfall is a
    # recommended rule and is classified ADVISORY (upper-metal density closes at
    # chip integration). `min_density_shortfalls` is therefore DIAGNOSTIC, never
    # gating -- gating on it would make the stage unclosable by construction on a
    # sparse block, the same defect class as the constraints banner bug.
    "metal-fill": {"metric_id": "density_window_violations",
                   "direct": ["density_hard_violations", "max_density_violations"],
                   "diagnostic": ["min_density_shortfalls"],
                   "unit": "layers", "kind": "discrete", "iterating": True,
                   "named_families": {"density": ["density_hard_violations",
                                                  "max_density_violations"]},
                   # <TaskID> (item 3, wave 3): MEASURED on `<myDesign-A>.1/
                   # metal-fill-post-eco.1` and `<myDesign-B>.1/metal-fill-post-
                   # eco.1` -- five causally distinct obligations (a MAXIMUM-
                   # density hard-DRC check, two fill-induced short-defect
                   # classes, a connectivity-regression check, and a
                   # terminal-handoff completeness check), each independently
                   # recorded under `qor_metrics.*`/`validation.checks.*`.
                   # Plain `metal-fill` attempts (`<myDesign-B>.1/metal-fill.8`,
                   # `<myDesign-A>.1/metal-fill.5`) have NO inline `progress`
                   # block at all today; these recipes give them one for the
                   # first time, sourced from the same real keys.
                   "obligation_unit": "violations",
                   "obligation_families": {
                       "maximum_density": [
                           {"kind": "count", "paths": [
                               "qor_metrics.maximum_density_violations",
                               "qor_metrics.density_hard_violations",
                               "density_hard_violations",
                               "max_density_violations"]},
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.maximum_density_violations_zero",
                               "validation.checks.all_maximum_density_windows_pass",
                               "validation.checks.density_hard_violations_zero"]},
                       ],
                       "fill_induced_opens": [
                           {"kind": "count", "paths": [
                               "qor_metrics.fill_induced_opens"]},
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.fill_induced_opens_zero",
                               "validation.checks.zero_fill_induced_opens"]},
                       ],
                       "fill_induced_shorts": [
                           {"kind": "count", "paths": [
                               "qor_metrics.fill_induced_shorts"]},
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.fill_induced_shorts_zero",
                               "validation.checks.zero_fill_induced_shorts"]},
                       ],
                       "fill_induced_drc": [
                           {"kind": "count", "paths": [
                               "qor_metrics.fill_induced_drc_violations"]},
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.fill_induced_drc_violations_zero",
                               "validation.checks.zero_fill_induced_drc_violations",
                               # TRUE-SCOPE SPELLING. The two names above read as
                               # full rule-deck legality; what the stage actually
                               # measures is fill-to-non-fill keep-out spacing
                               # against the fill config's own `space_to_non_fill`.
                               # Renaming the check to say so must not un-bind the
                               # family, or the honest name costs the producer its
                               # evidence and the dishonest one is the cheaper
                               # choice. Full BEOL rule-legality stays a DOWNSTREAM
                               # drc/antenna obligation (see the stage's own
                               # `beol_scope_obligation`).
                               "validation.checks."
                               "fill_to_nonfill_spacing_keepout_violations_zero"]},
                       ],
                       "connectivity": [
                           {"kind": "count", "paths": [
                               "qor_metrics.connectivity_regressions"]},
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.connectivity_regressions_zero"]},
                       ],
                       "handoff": [
                           {"kind": "bool_true_ok", "paths": [
                               "validation.checks.complete_terminal_handoff",
                               "validation.checks.streamable_gds_preserved"]},
                       ],
                   }},
    # <TaskID>: `tapcell` had NO STAGE_RESIDUALS entry at all -- its own
    # `results` block is file-pointer-only (`tapped_def`/`tapped_odb`/
    # `validation_report` paths+hashes, no inline facts), but MEASURED on
    # `<myDesign-B>.1/tapcell.5` every genuine obligation the stage checks IS
    # recorded inline under `signoff_evidence`/`validation.checks`: original
    # flops and instances survive tap/endcap insertion, the PDN SPECIALNETS
    # geometry the upstream `pdn` stage built is untouched, every inserted
    # tap/endcap cell is FIXED (not movable), and floorplan->pdn->tapcell
    # dependency order was honoured.
    "tapcell": {
        "metric_id": "tapcell_gate_defects",
        "obligation_families": {
            # A key name must describe the INVARIANT, never a specific expected
            # value. `all_33_flops_preserved` was authored against a design
            # revision that had 33 flops; the design it is measured on today has
            # 32, so a reviewer reading `all_33_flops_preserved: true` on a
            # 32-flop design cannot tell real evidence from a copy-paste. The
            # design-agnostic spelling is preferred and is what the tool emits;
            # the numbered one is kept ONLY so already-blessed attempts that
            # bound it keep binding (dropping it would narrow their basis).
            "flop_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.all_flops_preserved",
                    "validation.checks.all_flops_preserved",
                    "signoff_evidence.all_33_flops_preserved",
                    "validation.checks.all_33_flops_preserved"]},
            ],
            "instance_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.all_original_instances_preserved",
                    "validation.checks.original_instances_preserved"]},
            ],
            "pg_preservation": [
                {"kind": "bool_true_ok", "paths": [
                    "signoff_evidence.pdn_specialnets_preserved",
                    "validation.checks.pdn_specialnets_preserved"]},
            ],
            "fixed_placement": [
                {"kind": "count", "paths": [
                    "signoff_evidence.non_fixed_instances"]},
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks.all_inserted_fixed"]},
            ],
            "dependency_order": [
                {"kind": "bool_true_ok", "paths": [
                    "validation.checks."
                    "correct_dependency_order_floorplan_then_pdn_then_tapcell"]},
            ],
        },
        "population": ["inserted_total", "tapcells_inserted",
                        "endcaps_inserted"],
        "primary_family": "flop_preservation", "obligation_unit": "defects",
        "unit": "defects", "kind": "discrete", "iterating": True,
    },
    # floorplan emits NO defect count -- design_area and utilization are
    # MEASUREMENTS (no closed state; a signed target, not a quantity that reaches
    # zero), so neither may be a residual. What it DOES compute is a boolean gate:
    # `utilization_routable`, which the tool derives from achieved utilization and
    # which fails CLOSED (None, never True) when utilization cannot be parsed.
    # Boolean gate = 0 closed / 1 open, the same shape already used by funcverif
    # (sim_passed) and rtl (synthesizable).
    #
    # <TaskID>: MEASURED on `<myDesign-B>.1/floorplan.4` and `<myTopDesign>.1/floorplan.1`
    # (both current attempts): neither publishes `utilization_routable` at all
    # -- the per-macro dialect states its band check as a flat
    # `signoff_evidence.utilization_within_sr_072` boolean instead, and the
    # flat-chip-top dialect states no utilization gate at all ("top-level
    # utilization is reported, not gated" -- out of scope for a per-macro
    # floorplan re-run). Both dialects DO publish the same physical-legality
    # booleans (`rows_legal`, `tracks_legal`, `pins_legal`) that
    # `initialize_floorplan` itself computes and gates on, so these are added
    # as additional `bool_ok` names rather than inventing a synonym for
    # `utilization_routable` that only one dialect could ever satisfy.
    "floorplan": {"metric_id": "floorplan_open_gate_items",
                  "bool_ok": ["utilization_routable",
                              "utilization_within_sr_072",
                              "rows_legal", "tracks_legal", "pins_legal"],
                  "unit": "items", "kind": "discrete", "iterating": True,
                  # <TaskID> (item 3, wave 2a): MEASURED, three genuinely
                  # different per-design dialects, none of which overlaps the
                  # bare `bool_ok` names above -- `<myDesign-B>.1/floorplan.4`
                  # nests its own booleans under `validation.checks.*` and
                  # names three families (`legality`, `utilization`,
                  # `flop_census`); `<myDesign-A>.1/floorplan.2` states its
                  # equivalents as FLAT `validation.*` keys (no `checks`
                  # nesting) under ONE family (`legality_and_utilization`);
                  # `<myTopDesign>.1/floorplan.1` nests under `validation.checks.*`
                  # again but names three DIFFERENT families (`geometry`,
                  # `macro_integration`, `padframe_and_pins`). Every name is
                  # declared here, sourced from the exact real booleans each
                  # attempt's own dialect records -- reopen-repertoire risk
                  # noted above still applies to any NEW name, not to
                  # reproducing what each attempt already asserts.
                  "obligation_unit": "violations",
                  "obligation_families": {
                      "legality": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.rows_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.tracks_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.pins_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.pin_geometry_labels_explicit"]},
                      ],
                      "utilization": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.utilization_within_sr_072_band"]},
                      ],
                      "flop_census": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.flop_census_is_33_not_32"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.no_pin_net_aliasing"]},
                      ],
                      "legality_and_utilization": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.rows_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.tracks_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.pins_legal"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.utilization_in_sr_072_range"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.top_level_only_requirements_excluded"]},
                      ],
                      "geometry": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.all_physical_instances_inside_die"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.physical_instances_nonoverlapping"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.pin_net_labels_explicit"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.die_exact"]},
                      ],
                      "macro_integration": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.hard_macro_instances_exact"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.hard_macro_halos_clear"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.hard_macro_pin_contracts_match"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.hard_macro_channel_meets_20um_plan"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.rows_cut_around_macro_halos"]},
                      ],
                      "padframe_and_pins": [
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.padframe_exact_count_and_types"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.padframe_nine_per_side"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.all_top_pins_boundary_touching"]},
                          {"kind": "bool_true_ok", "paths": [
                              "validation.checks.all_top_pins_placed_on_track"]},
                      ],
                  }},
    # NOTE: floorplan deliberately declares NO EXTRA named_families beyond the
    # per-attempt obligation_families above. A family name is only reachable
    # if reopen-repertoire.json maps it to an owner, and there is no
    # calibrated `routability` owner -- inventing one would silently route
    # reopens to a stage that cannot fix the residual (the "falsely-principled"
    # failure this repo has already been burned by). Add the family when reopen
    # OUTCOMES justify an owner, not before.
}


def normalize_stage(stage):
    """Map a CDE `stage` value, stage-dir name, or TOOL name onto a registry key.

    Separator-insensitive by construction. The alias table is written with
    underscores while tool `TOOL` constants are hyphenated, and matching only one
    spelling silently returned None for a stage that IS in the registry -- which
    degrades it to `metric_kind: unavailable` with no error, making the stage
    invisible to the effort framework.
    """
    if not stage:
        return None
    s = str(stage).strip().lower().replace(" ", "_")
    s = s.split("/")[-1]
    s = s.split(".")[0]           # "codecov.3" -> "codecov"
    if s == "domain_map":
        return None

    # Candidates are tried MOST-SPECIFIC FIRST. Each fallback below discards
    # information, so an exact hit must always win over a truncated one.
    cands = []
    for base in (s, s.replace("_", "-"), s.replace("-", "_")):
        if base not in cands:
            cands.append(base)

    # Agent-name prefix. Tools identify themselves as either `sta` or `chip-sta`
    # depending on which constant reached the envelope, and the unprefixed form
    # is the registry spelling. Without this an entire agent's output resolves to
    # None and reports no metric -- silence that reads as "no violation".
    for base in list(cands):
        for pfx in ("chip-", "chip_"):
            if base.startswith(pfx) and len(base) > len(pfx):
                for v in (base[len(pfx):],
                          base[len(pfx):].replace("_", "-"),
                          base[len(pfx):].replace("-", "_")):
                    if v not in cands:
                        cands.append(v)

    for candidate in cands:
        if candidate in STAGE_RESIDUALS:
            return candidate
        if candidate in _STAGE_ALIASES:
            return _STAGE_ALIASES[candidate]

    # Flow-position suffix: `sta-pre-synth`, `sta-prelayout`, `lec-post-synth`
    # name WHERE in the flow the stage ran, not a different stage. The gate is
    # the same one, so it must route to the same registry key. Longest prefix
    # wins so `lec-post-synth` cannot be captured by a shorter unrelated key.
    for candidate in cands:
        for cut in range(len(candidate) - 1, 1, -1):
            if candidate[cut] not in "-_":
                continue
            head = candidate[:cut]
            if head in STAGE_RESIDUALS:
                return head
            if head in _STAGE_ALIASES:
                return _STAGE_ALIASES[head]
    return None


def normalize_verdict(raw_verdict, status=None):
    """Map any verdict spelling onto the controlled enum. Always returns a value.

    Free-text verdicts (the audit found a whole sentence in the enum field) are
    matched by keyword, then fall back to `status`, then to not_assessable --
    never silently to `pass`.
    """
    if raw_verdict is not None:
        v = str(raw_verdict).strip().lower()
        if v in _VERDICT_MAP:
            return _VERDICT_MAP[v]
        # free-text: match the most severe keyword present, fail-safe ordering
        for token in ("invalid", "error", "not_assessable", "not assessable",
                      "fail", "pass"):
            if token in v:
                return _VERDICT_MAP.get(token.replace(" ", "_"),
                                        VERDICT_NOT_ASSESSABLE)
    if status is not None:
        st = str(status).strip().lower()
        if st in ("failed", "error"):
            return VERDICT_FAIL if st == "failed" else VERDICT_ERROR
        if st == "completed":
            # `completed` describes the RUN, not the GATE. Without an explicit
            # verdict the gate state is unknown -- never upgrade it to pass.
            return VERDICT_NOT_ASSESSABLE
    return VERDICT_NOT_ASSESSABLE


def _locate_verdict(results):
    """Find the gate verdict wherever this tool chose to put it.

    Measured over 130 real envelopes, ``validation.verdict`` is the DOMINANT
    location (115) and is the ONLY location in 74 of them, while a top-level
    ``verdict`` appears in just 49. Reading only the top level therefore
    normalised well over half of all real envelopes to `not_assessable` even
    though they carried a perfectly good verdict -- which silently disabled the
    closure-alignment audit and made passing gates look unassessable.
    """
    if not isinstance(results, dict):
        return None
    if results.get("verdict") is not None:
        return results["verdict"]
    for block in ("validation", "results", "signoff_evidence"):
        sub = results.get(block)
        if isinstance(sub, dict) and sub.get("verdict") is not None:
            return sub["verdict"]
    return None


def _as_number(value):
    """Coerce a CDE field to a number.

    Tools commonly wrap a scalar as ``{"value": N, "basis": "..."}``. That single
    convention accounted for most unrecoverable residuals in the 2026-08-21 audit
    (it made the whole `rtl` stage unreadable), so it is unwrapped here.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except (ValueError, AttributeError):
            return None
    if isinstance(value, dict):
        # *** `total` IS A DENOMINATOR, NOT A MEASUREMENT. *** Reading it as the
        # scalar produced a SILENT WRONG NUMBER (not a null), which is the worst
        # failure mode this module has. MEASURED 2026-09-02 on codecov: a
        # per-type record {"hit": 4, "total": 4, "percent": 100.0} resolved to
        # 4 via the `total` wrapper, so the percent_gap family computed
        # 100 - 4 = 96.0 and reported a FULLY-COVERED branch metric as 96% short.
        # It survived review because 4 passes the 0..100 range guard and because
        # the same 96.0 appears whether coverage is 0% or 100% -- the residual
        # was tracking the POPULATION SIZE, which is constant, so it looked
        # stable rather than broken. code-coverage.4 shipped verdict=pass with
        # residual=96.0 on that basis.
        #
        # So: a dict carrying `percent`, or carrying both `hit` and `total`, is a
        # RATIO RECORD. Its measurement is `percent`; its `total` is the
        # denominator and must never be returned as the value. `total` stays a
        # legal wrapper only for the plain {"total": N} count shape, where it IS
        # the quantity.
        ratio_record = ("percent" in value) or ("hit" in value and "total" in value)
        wrappers = (("value", "percent", "count", "measured") if ratio_record
                    else ("value", "count", "total", "measured", "residual"))
        for wrapper in wrappers:
            if wrapper in value:
                inner = value[wrapper]
                if not isinstance(inner, dict):
                    return _as_number(inner)
    return None


# Sub-blocks the residual search must NEVER enter, because they hold ADVISORY
# model-authored readings rather than measurements.
#
# *** THIS GUARD EXISTS BECAUSE THE LEAK WAS REAL AND MEASURED. *** With a
# testbench envelope whose MEASURED gate was 1, a planted model claim of 99 in
# `signoff_evidence.interpretation` was returned as the residual (source:
# signoff_evidence.interpretation.failures). Mechanism: `_find` walks the alias
# list in ORDER and takes the FIRST hit anywhere, so when a model-authored key
# name sorts earlier in `direct` than the measured one, the model's number wins.
# Stages whose measured name happened to sort first escaped BY LUCK OF NAMING,
# not by design.
#
# The metric-class contract promises a model claim can never move a gate. That
# promise is enforced at the CLASS layer, but the residual extractor predates it
# and knows nothing about classes -- so the promise was false at exactly the
# layer that feeds the effort framework and the stall machinery.
#
# `negative_control` is excluded for the SAME reason under a DIFFERENT shape
# (<TaskID>): it is a mutation-testing sanity block that PROVES the checker is
# not vacuous by deliberately corrupting one expected value and confirming the
# scoreboard/monitor caught it -- so its own `mismatches`/`result` fields are
# the mutation-test OUTCOME (an intentional, expected non-zero), not the
# functional gate. MEASURED on <myDesign-B>.1/simulation.1: `_find`'s generic
# `mismatches` alias matched `signoff_evidence.negative_control.mismatches: 1`
# (the deliberately-planted fault count) ahead of the real, zero
# `results.scoreboard_mismatches`, manufacturing a blocking metric_defect on a
# gate that had actually closed clean. The real gating verdict for whether the
# negative control itself passed lives under its own uniquely-named field
# (`negative_control_missed`), which is unaffected by this exclusion.
_ADVISORY_KEYS = ("interpretation", "interpretation_crosscheck",
                   "negative_control")


def _is_advisory(key, node):
    """True when a sub-block is model-authored/advisory and must not be searched.

    Matched two ways deliberately: by KEY (the conventional block names) and by
    a self-declared `class: model_authored`, so a tool that names its block
    something else is still excluded.
    """
    if key in _ADVISORY_KEYS:
        return True
    if isinstance(node, dict) and node.get("class") == "model_authored":
        return True
    return False


def _find(blocks, names, _max_depth=3):
    """First numeric hit for any alias name, searched depth-first in priority order.

    Returns (dotted_source_path, value) or (None, None).
    """
    for name in names:
        for label, block in blocks:
            hit = _descend(block, name, label, _max_depth)
            if hit is not None:
                return hit
    return None, None


def _descend(node, key, path, depth):
    if depth < 0 or not isinstance(node, dict):
        return None
    if key in node and not _is_advisory(key, node.get(key)):
        num = _as_number(node[key])
        if num is not None:
            return path + "." + key, num
    for sub_key, sub in node.items():
        if isinstance(sub, dict) and not _is_advisory(sub_key, sub):
            hit = _descend(sub, key, path + "." + sub_key, depth - 1)
            if hit is not None:
                return hit
    return None


def _find_bool(blocks, name, _max_depth=3):
    """Find a declared boolean gate flag, unwrapping the ``{"value": ...}`` form.

    Kept separate from `_find` because `_as_number` deliberately rejects bools --
    a stray True must never be read as the number 1 by the numeric path.
    """
    for label, block in blocks:
        hit = _descend_bool(block, name, label, _max_depth)
        if hit is not None:
            return hit
    return None, None


def _descend_bool(node, key, path, depth):
    if depth < 0 or not isinstance(node, dict):
        return None
    if key in node and not _is_advisory(key, node.get(key)):
        raw = node[key]
        if isinstance(raw, dict) and "value" in raw:
            raw = raw["value"]
        if isinstance(raw, bool):
            return path + "." + key, raw
    for sub_key, sub in node.items():
        if isinstance(sub, dict) and not _is_advisory(sub_key, sub):
            hit = _descend_bool(sub, key, path + "." + sub_key, depth - 1)
            if hit is not None:
                return hit
    return None


def _coerce_number(value):
    return _as_number(value)


def _coerce_bool(value):
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    return value if isinstance(value, bool) else None


def _coerce_string(value):
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    return value if isinstance(value, str) else None


def _coerce_list_len(value):
    """Obligation-family coercion for a POPULATION LIST rather than a scalar
    (<TaskID>): several stages record an obligation as a list of the offending
    items (e.g. vplan's `missing_required_owners`, `downstream_reblessing_
    required`) rather than a pre-counted number. `[]` is the closed state
    (residual 0); a non-empty list is the count of open items. A dict-wrapped
    list (`{"value": [...]}`) is unwrapped the same way `_coerce_number` and
    `_coerce_bool` already do."""
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if isinstance(value, list):
        return float(len(value))
    return None


def _coerce_raw_gating_node(value):
    """Obligation-family coercion that returns the WHOLE `{"value":...,
    "class": "gating", "closes_at": "..."}` record unchanged, for the
    `declared_threshold` obligation kind (<TaskID>). Reading only `value` would
    require the recipe author to already know and hard-code the producer's
    threshold (e.g. guessing `synthesis_fused_scan_enabled`'s gate is
    `== false` rather than `== true`); this coercion instead lets
    `_eval_closes_at` read the threshold the PRODUCER itself declared, the
    same "prefer the producer's own contract over alias guessing" preference
    already used by `_find_declared_gating`. Non-gating records (no `class:
    gating` or no `closes_at`) are rejected here so a diagnostic field can
    never silently become a gate."""
    if (isinstance(value, dict) and "value" in value
            and value.get("class") == "gating"
            and isinstance(value.get("closes_at"), (str,))):
        return value
    return None


def _find_dotted(blocks, paths, coerce):
    """Resolve the first FULLY QUALIFIED dotted path that exists and coerces.

    Unlike `_find`/`_find_bool` (which match a bare leaf key name anywhere
    nested, ambiguous when the same leaf name recurs under unrelated parents --
    e.g. a `match` or `verdict` key present under several independent
    sub-blocks), every entry in ``paths`` names ONE specific recorded fact
    end-to-end: ``"<block label>.<key>[.<key>...]"``, where ``<block label>``
    is the label a `blocks` tuple carries (``results``, ``signoff_evidence``,
    ``qor_metrics``, ``validation``, ...) and the remaining dotted segments are
    walked literally from that block's own dict -- never matched against an
    unrelated block. This is used for obligation-family derivation (see
    `obligation_families` in the spec header) where it matters WHICH exact
    sub-block backs a family, not merely whether some field with that name
    exists anywhere in the envelope. Multiple dotted paths in one list are
    dialect ALIASES for the same real fact -- first one present wins.
    """
    for path in paths:
        parts = path.split(".")
        if len(parts) < 2:
            continue
        block_label, rest = parts[0], parts[1:]
        for label, block in blocks:
            if label != block_label:
                continue
            node = block
            ok = True
            for part in rest:
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if not ok:
                continue
            val = coerce(node)
            if val is not None:
                return path, val
    return None, None


def _eval_closes_at(value, closes_at):
    """Evaluate a PRODUCER-DECLARED ``closes_at`` threshold against ``value``.

    Returns True/False when the declared threshold could actually be checked,
    or None when its shape could not be interpreted. A caller MUST skip a
    None rather than guess: fabricating a comparison here would be inventing
    a threshold the producer never declared, exactly what this fallback
    exists to avoid.
    """
    if not isinstance(closes_at, str):
        return None
    match = re.match(r"^\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$", closes_at)
    if not match:
        return None
    op, rhs_raw = match.group(1), match.group(2).strip().lower()
    if rhs_raw in ("true", "false"):
        if not isinstance(value, bool):
            return None
        rhs = (rhs_raw == "true")
        if op == "==":
            return value == rhs
        if op == "!=":
            return value != rhs
        return None  # ordering ops on a boolean threshold are not meaningful
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        rhs = float(rhs_raw)
    except (TypeError, ValueError):
        return None
    value = float(value)
    if op == "==":
        return abs(value - rhs) < 1e-9
    if op == "!=":
        return abs(value - rhs) >= 1e-9
    if op == ">=":
        return value >= rhs - 1e-9
    if op == "<=":
        return value <= rhs + 1e-9
    if op == ">":
        return value > rhs
    if op == "<":
        return value < rhs
    return None


_HARD_GATE_DISPOSITIONS = re.compile(r"^hard_gate_(pass|fail)$")
# Wrapper keys a `disposition: hard_gate_pass/fail` (or `verdict: pass/fail`,
# see below) dict may carry its count under. `value` is deliberately EXCLUDED:
# MEASURED on cts.3's `results.clock_skew` ({"value": 0.05, "limit": 0.25,
# "verdict": "pass"}), a bare `value` sibling to `verdict` is a MARGIN
# measurement (compared against `limit`), not a violations-style count
# implicitly closing at 0 -- reading it as one would have flipped a real
# PASS (0.05 < 0.25) into a fabricated FAIL (0.05 != 0).
_HARD_GATE_VALUE_KEYS = ("violations", "shortfalls", "count")


def _find_declared_gating(blocks, _max_depth=4):
    """Find every producer-declared ``class: gating`` metric with an explicit
    ``closes_at`` (or a `limit`) that could be evaluated, plus three more
    self-declared-polarity dialects.

    <TaskID> fallback: a modelled stage whose declared source keys (`direct`,
    `named_families`, ...) do not bind to this envelope must not silently
    default-close its gate. Rather than adding alias strings for every
    near-miss key name a producer happens to use (whack-a-mole that fixes only
    the instances already found), read the threshold the producer ITSELF
    stated on the metric it emitted. A metric lacking an explicit
    ``closes_at``/``limit``, or whose value/threshold shapes cannot be
    compared, is skipped -- never guessed at.

    <TaskID> REWORK: `class: gating` + `closes_at` is not the only self-declared
    gating vocabulary in the corpus. Three more are matched, all because the
    producer names its OWN polarity explicitly (never guessed):

      * `class: gating` + `value` + `limit` (no `closes_at`) -- MEASURED on
        `cts.3`/`cts.6`'s `results.clock_skew`: same "must not exceed"
        semantics as `closes_at`, just a different label. Only a NUMERIC
        `limit` is trusted; folded into an implicit `"<= limit"` closes_at.
      * `disposition: hard_gate_pass`/`hard_gate_fail` (metal-fill-family). Its
        counterpart, `disposition: "not_gating"` / `"advisory/not_gating"`, is
        never matched (no such string satisfies `_HARD_GATE_DISPOSITIONS`), so
        a diagnostic-only shortfall can never masquerade as a closed gate.
      * `verdict: "pass"/"fail"` paired with a `violations`/`shortfalls`/
        `count` SIBLING key in the SAME dict (e.g.
        `validation.maximum_density: {"verdict": "pass", "violations": 0}`).
        Deliberately narrow: the numeric key must be a DIRECT sibling of
        `verdict`, not merely reachable somewhere nearby -- a bare top-level
        `validation.verdict: "pass"` with no adjoining count is NOT matched,
        because that alone does not name what was measured, only that
        *something* passed (the exact ambiguity a hand-authored stub trades
        on).
      * `"residual" in val` + `status` starting with `"pass"`/`"fail"`
        (MEASURED on `eco.4`'s `mandatory_checks.<name>` dicts) -- the
        producer states BOTH its own residual count AND its own pass/fail
        status in one place. `status: "unavailable"` (measurement not taken)
        is deliberately excluded so an un-run check is never counted as
        either polarity.

    A bare, unannotated `checks: {name: bool, ...}` dict (no `class`,
    `disposition` or `verdict` on the dict that carries it) is deliberately
    NEVER read as gating evidence here, however common the convention: MEASURED
    on `eco.5`, such a dict's booleans are NEGATIVE-POLARITY audit assertions
    (`no_wave_committed: true`, `before_after_residuals_unavailable: true`) --
    all "true" because the wave FAILED, not because it passed. Nothing in a
    bare boolean's own name is machine-checkable as positive- vs
    negative-polarity, so a blind "count of False == violations" reading would
    have inverted a failure into a fabricated pass. Only a dict that ALSO
    carries its own explicit polarity marker (`class`, `disposition`,
    `verdict`) is read as gating evidence; a `checks` dict without one is
    correctly left as unbound rather than guessed at.

    Returns a list of (metric_name, dotted_source_path, satisfied) triples,
    at most one per distinct metric name (first occurrence, by block
    priority order, wins).
    """
    found = {}

    def _walk(node, path, depth):
        if depth < 0 or not isinstance(node, dict):
            return
        for key, val in node.items():
            if not isinstance(val, dict) or _is_advisory(key, val):
                continue
            if key not in found and val.get("class") == "gating" and "value" in val:
                closes_at = val.get("closes_at")
                if closes_at is None and isinstance(val.get("limit"), (int, float)) \
                        and not isinstance(val.get("limit"), bool):
                    closes_at = "<= %s" % val["limit"]
                if closes_at is not None:
                    satisfied = _eval_closes_at(val["value"], closes_at)
                    if satisfied is not None:
                        found[key] = (path + "." + key, satisfied)
            elif key not in found and (
                    _HARD_GATE_DISPOSITIONS.match(str(val.get("disposition") or ""))
                    or str(val.get("verdict") or "").lower() in ("pass", "fail")):
                for value_key in _HARD_GATE_VALUE_KEYS:
                    num = _as_number(val.get(value_key)) \
                        if value_key in val else None
                    if num is not None:
                        found[key] = (path + "." + key, abs(num) < 1e-9)
                        break
            elif key not in found and "residual" in val \
                    and str(val.get("status") or "").startswith(("pass", "fail")):
                num = _as_number(val.get("residual"))
                if num is not None:
                    found[key] = (path + "." + key, abs(num) < 1e-9)
            elif key not in found and isinstance(val.get("value"), bool):
                # <TaskID> REWORK: `cts_validation.json`'s `checks.<name>:
                # {"value": true, "measured_ns": 0.0554, "limit_ns": 0.25}`
                # (MEASURED on cts.6) pairs a declared boolean verdict with an
                # INDEPENDENTLY VERIFIABLE measured/limit margin -- unlike a
                # bare boolean audit flag (eco.5's `no_wave_committed: true`),
                # this one can be CHECKED, not merely trusted: only accepted
                # when a `measured_*`/`limit_*` (or `_ns`/`_ns`) sibling pair
                # exists AND recomputing `measured <= limit` agrees with the
                # declared boolean. A dict lacking that verifiable pair, or
                # whose recomputation disagrees with its own declared value,
                # is left unbound rather than blindly trusted.
                measured = limit = None
                for k2, v2 in val.items():
                    if k2 == "value" or not isinstance(v2, (int, float)) \
                            or isinstance(v2, bool):
                        continue
                    if k2.startswith("measured"):
                        measured = v2
                    elif k2.startswith("limit"):
                        limit = v2
                if measured is not None and limit is not None:
                    recomputed = measured <= limit
                    if recomputed == val["value"]:
                        found[key] = (path + "." + key, recomputed)
            _walk(val, path + "." + key, depth - 1)

    for label, block in blocks:
        _walk(block, label, _max_depth)
    return [(name, src, satisfied) for name, (src, satisfied) in found.items()]


def _load_json_evidence(path):
    """Best-effort load of a producer-referenced JSON evidence file.

    <TaskID> REWORK: `cts.6` and siblings do not inline every gating number --
    some point at them via `validation.report` / `signoff_evidence.
    native_tool_cde` (a plain path string, or `{"path": ...}`). Every path
    observed in this corpus is already recorded repo-root-relative, so no
    `attempt_dir` plumbing is needed to resolve it. Returns ``None`` on any
    failure (missing file, bad JSON, wrong type) -- this is a fallback
    source, never a required one, and must never raise.
    """
    if not isinstance(path, str) or not path:
        return None
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _referenced_evidence_blocks(results):
    """Resolve producer-referenced external evidence files into scannable
    blocks: `validation.report`, and `signoff_evidence.native_tool_cde(s)` /
    `native_cde` (a nested Common Design Envelope). Every pointer form
    observed in the corpus (bare string, or `{"path": ...}`) is accepted.
    """
    out = []
    validation = results.get("validation")
    if isinstance(validation, dict):
        report = validation.get("report")
        loaded = _load_json_evidence(report if isinstance(report, str) else None)
        if isinstance(loaded, dict):
            checks = loaded.get("checks")
            if isinstance(checks, dict):
                out.append(("validation.report.checks", checks))
    signoff = results.get("signoff_evidence")
    if not isinstance(signoff, dict):
        return out
    refs = []
    many = signoff.get("native_tool_cdes")
    if isinstance(many, dict):
        for name, ref in many.items():
            if isinstance(ref, dict):
                refs.append((str(name), ref.get("path")))
            elif isinstance(ref, str):
                refs.append((str(name), ref))
    for singular in ("native_tool_cde", "native_cde"):
        ref = signoff.get(singular)
        if isinstance(ref, dict):
            refs.append((singular, ref.get("path")))
        elif isinstance(ref, str):
            refs.append((singular, ref))
    for name, path in refs:
        loaded = _load_json_evidence(path)
        if not isinstance(loaded, dict):
            continue
        for sub_key in ("results", "qor_metrics", "signoff_evidence"):
            sub_block = loaded.get(sub_key)
            if isinstance(sub_block, dict):
                out.append(("native_tool_cde.%s.%s" % (name, sub_key), sub_block))
    return out


def _flow_mode(results):
    """Return the envelope's explicit flow-position mode, if any.

    ``timing_mode`` has appeared in both ``results`` and ``signoff_evidence``
    across real STA envelopes. Reading the controlled value from either location
    is safer than guessing from a directory spelling such as ``sta-pre-synth``.
    """
    if not isinstance(results, dict):
        return None
    for key in ("results", "signoff_evidence", "signoff", "qor_metrics"):
        block = results.get(key)
        if isinstance(block, dict) and block.get("timing_mode") is not None:
            return str(block["timing_mode"]).strip().lower()
    if results.get("timing_mode") is not None:
        return str(results["timing_mode"]).strip().lower()
    return None


def compute_progress(results, stage=None):
    """Build the normalized progress block for one envelope. Never raises."""
    progress = {
        "schema": SCHEMA,
        "metric_id": None,
        "residual": None,
        "closes_at": 0,
        "direction": "minimize",
        "metric_kind": "unavailable",
        "unit": None,
        "source": None,
        "denominator": None,
        "verdict_normalized": VERDICT_NOT_ASSESSABLE,
        "gate_closed": False,
        "alignment": "unknown",
        "iterating": False,
    }
    try:
        if not isinstance(results, dict):
            return progress

        stage_key = normalize_stage(stage or results.get("stage"))
        if stage_key is None:
            # An envelope that never stamped `stage` (or stamped a spelling the
            # registry does not know) would otherwise report NO METRIC -- and a
            # missing metric is indistinguishable downstream from a clean gate.
            # The producing tool identifies the gate just as well, so it is the
            # fallback rather than accepting silence. Recorded, because routing
            # by producer is weaker evidence than an explicit stage stamp.
            stage_key = normalize_stage(results.get("tool"))
            if stage_key is not None:
                progress["stage_key_source"] = "tool_fallback"
                progress["stage_key_note"] = (
                    "stage was absent or unrecognized; gate identified from the "
                    "producing tool. Stamp `stage` explicitly to remove the guess."
                )
        progress["stage_key"] = stage_key

        verdict = _locate_verdict(results)
        norm = normalize_verdict(verdict, results.get("status"))
        progress["verdict_normalized"] = norm
        progress["gate_closed"] = (norm in CLOSING_VERDICTS)
        # A caveated pass keeps the stage ITERABLE: the caveat is unfinished work,
        # and closing on it would stop the effort framework short of the gate.
        progress["closed_with_caveats"] = (norm == VERDICT_PASS_WITH_CAVEATS)

        spec = STAGE_RESIDUALS.get(stage_key)
        if not spec:
            progress["alignment"] = "unknown"
            return progress

        progress["metric_id"] = spec.get("metric_id")
        progress["metric_kind"] = spec.get("kind", "unavailable")
        progress["unit"] = spec.get("unit")
        progress["iterating"] = bool(spec.get("iterating", False))
        # <TaskID> (item 3, wave 3, the `gds` finding): a stage with NO scalar
        # metric (`metric_id: None`, `kind: "unavailable"` -- e.g. `gds`,
        # whose real gate is a SET of independent signoff-family closures,
        # not one number) used to bail out here before `obligation_families`
        # ever ran, so a stage-authored family recipe silently never bound
        # regardless of how it was declared. `metric_id: None` only means
        # "no single collapsed scalar"; it does not mean "no obligations
        # exist to derive". Only skip the rest of derivation when the spec
        # ALSO declares no `obligation_families` (still true for `opendb`/
        # `pdk`, which genuinely have neither).
        if spec.get("metric_id") is None and not spec.get("obligation_families"):

            return progress

        flow_mode = _flow_mode(results)
        flow_scope = (spec.get("flow_scopes") or {}).get(flow_mode) or {}
        deferred_groups = {
            str(name).strip().lower()
            for name in flow_scope.get("deferred_family_groups", [])
            if str(name).strip()
        }
        if flow_scope:
            progress["flow_mode"] = flow_mode
            progress["gate_scope"] = flow_scope.get("gate")
            progress["deferred_to"] = flow_scope.get("deferred_to")

        # qor_metrics first: the audit found it materially more stable within a
        # stage than the freeform results block.
        blocks = []
        if stage_key == "domain-map":
            raw_results = results.get("results")
            raw_inputs = results.get("inputs_ref")
            raw_outputs = results.get("outputs_ref")
            raw_validation = results.get("validation")
            raw_signoff = results.get("signoff_evidence")
            raw_results = raw_results if isinstance(raw_results, dict) else {}
            raw_inputs = raw_inputs if isinstance(raw_inputs, dict) else {}
            raw_outputs = raw_outputs if isinstance(raw_outputs, dict) else {}
            raw_validation = raw_validation if isinstance(raw_validation, dict) else {}
            raw_signoff = raw_signoff if isinstance(raw_signoff, dict) else {}
            # <TaskID> REOPEN: the campaign carries (at least) two conformant
            # domain-map envelope dialects with different key vocabularies for
            # the SAME facts -- domain-map.2 (task-<TaskID>-era) and domain-map.3
            # (catalog/chip-design-intent producer). Requiring one dialect's
            # key name against the other's envelope coerces a legitimately
            # absent-under-this-dialect key into a fabricated defect. Detect
            # the .3 vocabulary from its own unambiguous markers (`spec_cde` in
            # inputs_ref, or an `unresolved` fact with no `unresolved_questions`
            # key at all) rather than from "is this key merely missing", so a
            # domain-map.2 envelope that has genuinely LOST a required key
            # still fails closed instead of being reclassified as "not
            # applicable".
            is_v3_dialect = bool(raw_inputs.get("spec_cde")) or (
                "unresolved_questions" not in raw_results
                and "unresolved" in raw_results
            )
            unresolved = raw_results.get("unresolved_questions")
            if unresolved is None and is_v3_dialect:
                unresolved = raw_results.get("unresolved")
            if isinstance(unresolved, bool) or not isinstance(unresolved, (int, float)) \
                    or unresolved < 0:
                unresolved = 1
            # `semantic_review` is a domain-map.2-only concept (the dialect that
            # tracks an explicit review phase). domain-map.3 has no such phase in
            # its schema at all -- absence there is "not applicable", not "review
            # incomplete". Only waive the requirement when the envelope is
            # unambiguously the .3 dialect; a .2-dialect envelope that has lost
            # the key stays fail-closed.
            semantic_review_ok = (
                raw_results.get("semantic_review") == "complete"
                or (is_v3_dialect and "semantic_review" not in raw_results)
            )
            derived = {
                "unresolved_questions": unresolved,
                "schema_semantic_defects": (
                    0 if semantic_review_ok
                    and raw_validation.get("alignment") == "ok" else 1
                ),
                # <TaskID>: a real, schema-conformant domain-map envelope anchors
                # its provenance in a pointer to the source spec document
                # (`frozen_spec` under domain-map.2, `spec_cde` under
                # domain-map.3) plus a content-addressed link back to that spec
                # (`source_sha256` / `upstream_spec_cde` / `upstream_spec_self_hash`
                # under domain-map.2, `specification_sha256` / `spec_cde_self_hash`
                # under domain-map.3). It never populates a `contract` key (that
                # name belongs to a different, unrelated field on other stages).
                # Requiring `contract`, or requiring one dialect's key names
                # against the other dialect's envelope, pinned
                # provenance_defects>=1 for legitimately closed domain-map gates;
                # see <TaskID-A>/<TaskID-B>.
                #
                # <TaskID>: a THIRD dialect (<myDesign-C>.1/domain-map.1, task
                # <TaskID>, `spec_document`/`spec_origin`/`requirements_matrix`
                # inputs_ref shape) anchors the content-addressed link back to
                # the source spec under `hash_chain.frozen_spec_sha256` rather
                # than any `inputs_ref` key at all. That is the SAME fact
                # (a hash tying this envelope to its frozen source spec) under
                # a THIRD name, not a missing fact -- so it is read here too
                # before concluding the hash link is absent.
                "provenance_defects": sum([
                    not bool(
                        raw_inputs.get("frozen_spec")
                        or raw_inputs.get("spec_cde")
                    ),
                    not bool(
                        raw_inputs.get("source_sha256")
                        or raw_inputs.get("upstream_spec_cde")
                        or raw_inputs.get("upstream_spec_self_hash")
                        or raw_inputs.get("specification_sha256")
                        or raw_inputs.get("spec_cde_self_hash")
                        or (isinstance(results.get("hash_chain"), dict)
                            and results["hash_chain"].get("frozen_spec_sha256"))
                    ),
                    not isinstance(results.get("hash_chain"), dict),
                    not bool(results.get("self_hash")),
                ]),
                # `role_published` is a domain-map.2-only results field; the
                # unambiguously-.3-dialect envelope that never tracks it at
                # all must not be charged for its absence (a .2-dialect
                # envelope that has genuinely lost the key still fails
                # closed). That waiver must not double up on the one
                # obligation both dialects DO share: publishing a pointer to
                # the produced domain-map artifact in `outputs_ref.domain_map`.
                # A missing `outputs_ref.domain_map` is a genuine publication
                # defect under EITHER dialect and is never waived here.
                #
                # <TaskID>: the domain-map.3 producer (catalog/chip-design-intent)
                # publishes that SAME pointer under `signoff_evidence.domain_map`
                # instead of `outputs_ref.domain_map` (confirmed on
                # <myDesign-B>.1/domain-map.3 and <myDesign-A>.1/domain-map.3, both of
                # which carry a `results/domain_map.json` reference only there).
                # Reading either location honours the shared obligation without
                # requiring one dialect's location against the other's envelope.
                "publication_defects": sum([
                    (
                        not (is_v3_dialect and "role_published" not in raw_results)
                        and raw_results.get("role_published") is not True
                    ),
                    not bool(raw_outputs.get("domain_map")
                             or raw_signoff.get("domain_map")),
                ]),
            }
            blocks.append(("derived.domain_map", derived))
        if isinstance(results.get("qor_metrics"), dict):
            blocks.append(("qor_metrics", results["qor_metrics"]))
        if isinstance(results.get("results"), dict):
            blocks.append(("results", results["results"]))
        if isinstance(results.get("signoff_evidence"), dict):
            blocks.append(("signoff_evidence", results["signoff_evidence"]))
        if isinstance(results.get("mandatory_checks"), dict):
            # <TaskID> REWORK: `eco.4` (<myDesign-B>) records real DRV-violation
            # evidence (`physical_drv.max_transition`: 33, etc., LITERAL
            # dotted-string keys) in a TOP-LEVEL `mandatory_checks` block, a
            # dialect neither `results` nor `signoff_evidence` covers.
            blocks.append(("mandatory_checks", results["mandatory_checks"]))
        blocks.extend(_referenced_evidence_blocks(results))
        if not blocks:
            return progress

        # A gate is usually MULTI-COMPONENT (synthesis = latches AND timing AND
        # don't-use; coverage = line AND branch AND toggle). Two rules apply, and
        # BOTH are load-bearing:
        #
        #  1. NEVER let a clean component mask a violating one. First-match-wins
        #     once hid a multi-million-nanosecond TNS violation behind a 0-latch
        #     result, so every field that resolves is recorded.
        #  2. NEVER compare across UNITS. Latch counts and nanoseconds are not
        #     commensurable: collapsing them with max() lets the residual switch
        #     basis between attempts (3 latches -> 2.0 ns reads as "improved by
        #     1.0" while timing actually got 5x worse). So components are grouped
        #     into unit FAMILIES, and each family carries its own residual.
        #
        # `residual` remains the worst value WITHIN THE PRIMARY FAMILY only, so a
        # scalar consumer is never handed a unit-swapped number. Consumers that
        # judge progress must use `families`: improvement requires at least one
        # family better by min_delta AND no family worse.
        families = {}
        deferred_family_metrics = {}

        def _record_into(target, family, unit, source, value):
            slot = target.setdefault(family, {"unit": unit, "components": {}})
            slot["components"][str(source)] = round(float(value), 6)

        def _record(family, unit, source, value):
            _record_into(families, family, unit, source, value)

        # <TaskID>: a stage-scoped opt-in guard (`suppress_evidence_if_present`,
        # currently only declared on `pdn`) against a producer's OWN disclosed
        # methodology gap for the specific attempt. Presence of one of these
        # keys (a non-empty free-text note, checked at the top level of any
        # block so it can never be a coincidental nested field) means the
        # producer has admitted its documented derivation path for its
        # primary check is broken for THIS attempt -- so an alias added to
        # widen binding coverage elsewhere must not read this attempt's
        # evidence as gating. This can only ever suppress binding, never
        # fabricate a defect: a stage without the flag, or an envelope
        # without the disclosure key, is completely unaffected.
        gap_keys = spec.get("suppress_evidence_if_present")
        disclosed_gap = bool(gap_keys) and any(
            isinstance(block, dict) and isinstance(block.get(k), str)
            and block.get(k).strip()
            for _label, block in blocks for k in gap_keys)
        if disclosed_gap:
            progress["residual_source_note"] = (
                "producer disclosed a methodology gap for this attempt (%s); "
                "declared source keys withheld from gate closure rather than "
                "read as evidence" % ", ".join(gap_keys))
        direct_names = [] if disclosed_gap else spec.get("direct", [])
        for name in direct_names:
            src, val = _find(blocks, [name])
            if val is not None:
                _record("count", spec.get("unit_count") or spec.get("unit"),
                        src, max(0.0, val))
        for name in spec.get("pct_to_100", []):
            src, val = _find(blocks, [name])
            if val is not None and 0.0 <= val <= 100.0:
                _record("percent_gap", "percent_gap",
                        str(src) + "(gap_to_100)", 100.0 - val)
        for name in spec.get("neg_slack", []):
            src, val = _find(blocks, [name])
            if val is not None:
                _record("slack_ns", "ns", str(src) + "(neg_slack)",
                        abs(min(0.0, val)))
        # Declared boolean gates: True == closed. Recorded in the `count` family
        # so a tool that reports a flag AND a count stays on one comparable basis.
        for name in spec.get("bool_ok", []):
            src, flag = _find_bool(blocks, name)
            if flag is not None:
                _record("count", spec.get("unit_count") or spec.get("unit"),
                        str(src) + "(bool)", 0.0 if flag else 1.0)

        # Explicitly-named families (see `named_families` in the spec header): one
        # family per causally-distinct component, so reopen-target selection can
        # route on WHICH component is open rather than a collapsed maximum.
        for fam_name, candidates in (spec.get("named_families") or {}).items():
            src, val = _find(blocks, list(candidates))
            # `None` is the tool's honest "not characterized / not checked" signal.
            # Recording it as 0.0 would manufacture a clean result for a check that
            # never ran -- the exact laundering this contract exists to prevent.
            if val is not None:
                target = (deferred_family_metrics
                          if _covered_by_deferral(fam_name, deferred_groups)
                          else families)
                _record_into(
                    target, fam_name,
                    spec.get("named_family_unit") or spec.get("unit"),
                    src, max(0.0, val))

        # Obligation-family recipes (see `obligation_families` in the spec
        # header, <TaskID>). Each declared family is ONE VERIFICATION OBLIGATION
        # the stage actually checks (e.g. dft's scannability, hazards,
        # chain_integrity, ...), derived from EXACT dotted fact paths rather
        # than a bare leaf-name search -- this is what lets two producer
        # dialects with different key spellings both bind to the SAME family
        # without one dialect's `verdict`/`match` leaking into an unrelated
        # family's residual. A family that cannot bind to ANY of its declared
        # paths is not dropped: <TaskID> measured that a dropped family and a
        # closed one are indistinguishable once the family disappears from
        # `families`, so it is recorded here as `not_assessable` with the
        # exact candidate paths that were checked, and merged back in after
        # closure is computed (never allowed to participate in
        # `all_families_closed` or `primary_family` selection).
        obligation_specs = spec.get("obligation_families") or {}
        not_assessable_obligations = {}
        # <TaskID> (REOPENED, item 2, the pdn.5 decision): `suppress_evidence_
        # if_present` (<TaskID>) was written before `obligation_families`
        # existed and only ever guarded `direct`/`bool_ok`. A prior <TaskID>
        # pass then widened it to blanket-suppress EVERY obligation family
        # whenever the disclosure key was present, reasoning the gap was
        # "attempt-scoped, not family-scoped". Re-examined against the
        # actual disclosure text (<myDesign-B>.1/pdn.5's own `assumptions[]`):
        # the gap is BOTH narrower and more precisely attributable than that
        # blanket read assumed --
        #   - It names EXACTLY two checks: `zero_open_power_nets` and
        #     `zero_failed_vias`, both backed by the SAME `direct`-family
        #     aliases (`floating_power_nets`/`open_power_nets`/
        #     `power_ground_shorts`) that `direct_names = []` above already
        #     withholds unconditionally. It never mentions
        #     `standard_cell_pg_iterms_*`, `rows_*`, or
        #     `macro_power_boundary_exposed` -- the three fields backing
        #     `power_connectivity`/`pg_pin_reach`/`macro_boundary`.
        #   - It is attributed to ONE PINNED IMAGE BUILD for THIS ATTEMPT
        #     (image_id 83b244236819, "a newer build than the one pdn.4
        #     used"), not a permanent property of the `pdn` stage type: the
        #     sibling `<myDesign-A>.1/pdn.5`, run against a build that still
        #     emits the legacy keys, carries NO such note at all and its
        #     `standard_cell_pg_iterms_*`/`rows_*`/boundary fields are
        #     structurally identical in shape and origin to <myDesign-B>'s.
        # Blanket-suppressing all THREE obligations for a disclosure that
        # concerns neither their obligation nor their source fields is the
        # same silent-narrowing defect this task exists to fix, just via an
        # over-wide guard instead of an under-wide recipe. `suppress_
        # evidence_if_present_obligations` makes the covered subset an
        # EXPLICIT, stage-authored list (default: none) rather than an
        # implicit "everything", so a future stage reusing this mechanism
        # for a genuinely attempt-wide gap can still opt every family in.
        gap_obligation_scope = set(
            spec.get("suppress_evidence_if_present_obligations") or [])
        if obligation_specs and disclosed_gap and gap_obligation_scope:
            fam_unit = spec.get("obligation_unit") or spec.get("unit")
            for fam_name in gap_obligation_scope:
                recipes = obligation_specs.get(fam_name)
                if recipes is None:
                    continue
                candidate_paths = sorted({
                    p for r in recipes
                    for p in (r.get("paths", [])
                              + r.get("population_paths", [])
                              + r.get("achieved_paths", []))
                })
                not_assessable_obligations[fam_name] = {
                    "unit": fam_unit,
                    "residual": None,
                    "components": {},
                    "not_assessable": True,
                    "reason": (
                        "producer disclosed a methodology gap for this "
                        "attempt (%s); this obligation's declared source "
                        "paths withheld from gate closure rather than read "
                        "as evidence (checked: %s)"
                        % (", ".join(gap_keys), ", ".join(candidate_paths))),
                }
        # Families NOT in the covered scope (or every family, when the gap
        # isn't disclosed at all) still bind normally below, against their
        # own real evidence.
        obligation_specs_to_bind = (
            {k: v for k, v in obligation_specs.items()
             if k not in gap_obligation_scope}
            if (obligation_specs and disclosed_gap and gap_obligation_scope)
            else obligation_specs)
        if obligation_specs_to_bind:
            obligation_specs = obligation_specs_to_bind
            ob_blocks = list(blocks)
            _validation_block = results.get("validation")
            if isinstance(_validation_block, dict):
                ob_blocks.append(("validation", _validation_block))
            fam_unit = spec.get("obligation_unit") or spec.get("unit")
            # <TaskID> (sta wave): `named_families`' flow-scope deferral
            # (`deferred_family_groups`, e.g. pre-layout STA deferring
            # `drv.*` to post-route) matches on a `drv.`-PREFIXED family
            # name. `obligation_families` deliberately names families to
            # match a stage's REAL stored names (sta's `max_transition` has
            # no such prefix, to match the census's own cited names) -- so
            # the same deferral needs a name-independent hook. A stage
            # declares `obligation_deferral_groups: {family: group}` to opt
            # specific obligations into the SAME `deferred_groups` set
            # `flow_scopes` already computed above; MEASURED on
            # `<myDesign-B>.1/sta-pre-synth.3` (etc.): without this, 21-46 real
            # DRV violations that the pre-layout flow_scope explicitly
            # defers were surfacing as a false `metric_defect`/`blocking`
            # for a check the stage's OWN policy says is not this
            # attempt's to close.
            obligation_deferral_groups = spec.get(
                "obligation_deferral_groups") or {}
            for fam_name, recipes in obligation_specs.items():
                ob_group = obligation_deferral_groups.get(fam_name)
                ob_target = (deferred_family_metrics
                             if ob_group and _covered_by_deferral(
                                 ob_group, deferred_groups)
                             else families)
                bound = False
                for recipe in recipes:
                    kind = recipe.get("kind")
                    if kind == "count":
                        for path in recipe.get("paths", []):
                            src, val = _find_dotted(ob_blocks, [path], _coerce_number)
                            if val is not None:
                                _record_into(ob_target, fam_name, fam_unit, src,
                                             max(0.0, val))
                                bound = True
                    elif kind == "neg_slack":
                        # Same semantics as the top-level `neg_slack` list
                        # (residual = abs(min(0, value))): a signed slack field
                        # is a VIOLATION only in its negative half; a positive
                        # value is margin, not progress-in-reverse. Recorded
                        # here rather than reusing the shared spec-level list
                        # because that list always writes to the single
                        # `slack_ns` family, and this obligation needs its OWN
                        # named family (e.g. synthesis's `timing`).
                        for path in recipe.get("paths", []):
                            src, val = _find_dotted(ob_blocks, [path], _coerce_number)
                            if val is not None:
                                # A per-recipe `unit` overrides the stage's
                                # shared `obligation_unit`/`unit` (<TaskID>): a
                                # slack-style obligation is measured in a
                                # DIFFERENT unit (ns) than the stage's other
                                # defect-count families, and folding it into
                                # the shared unit would be the exact
                                # unit-mixing defect this recipe kind exists
                                # to avoid.
                                _record_into(ob_target, fam_name,
                                             recipe.get("unit") or fam_unit, src,
                                             abs(min(0.0, val)))
                                bound = True
                    elif kind == "bool_true_ok":
                        src, flag = _find_dotted(ob_blocks, recipe.get("paths", []),
                                                  _coerce_bool)
                        if flag is not None:
                            _record_into(ob_target, fam_name, fam_unit, src,
                                         0.0 if flag else 1.0)
                            bound = True
                    elif kind == "bool_false_ok":
                        # Mirror of `bool_true_ok` for a field whose CLOSED
                        # state is `False` (<TaskID>, item 1c): e.g. synthesis's
                        # `scan_fusion_enabled`, where fused scan must stay
                        # OFF until the dedicated DFT stage. `_coerce_bool`
                        # only returns an actual Python bool (never a stray
                        # falsy value coerced from a string/number), so a
                        # real, present `False` is read as evidence rather
                        # than treated as absent -- the exact present-but-
                        # falsy defect this kind was added to fix.
                        src, flag = _find_dotted(ob_blocks, recipe.get("paths", []),
                                                  _coerce_bool)
                        if flag is not None:
                            _record_into(ob_target, fam_name, fam_unit, src,
                                         0.0 if not flag else 1.0)
                            bound = True
                    elif kind == "string_pass_ok":
                        src, sval = _find_dotted(ob_blocks, recipe.get("paths", []),
                                                  _coerce_string)
                        if sval is not None:
                            # `complete` added for <TaskID> (vplan's
                            # `semantic_review`: "complete" is the same closed
                            # state a review-phase field reports, not a
                            # differently-spelled failure).
                            ok = sval.strip().lower() in ("pass", "ok", "clean",
                                                           "closed", "complete")
                            _record_into(ob_target, fam_name, fam_unit, src,
                                         0.0 if ok else 1.0)
                            bound = True
                    elif kind == "string_startswith_ok":
                        # `string_pass_ok` requires an EXACT token match
                        # ("pass"/"ok"/...); several producers instead write a
                        # free-text disposition sentence in a `result`/`summary`
                        # field (e.g. `"PASS (depth 40, 11/11 non-VR205 asserts
                        # incl. new VR-203)"` -- MEASURED on
                        # <myTopDesign>.1/assertions.14's
                        # `signoff_evidence.bmc_isolated.result` and
                        # `signoff_evidence.cover.result`). An exact match
                        # against that string always misses, so this kind
                        # accepts a leading token (case-insensitive) instead of
                        # demanding the whole field spell only the token.
                        for path in recipe.get("paths", []):
                            src, sval = _find_dotted(ob_blocks, [path],
                                                      _coerce_string)
                            if sval is not None:
                                accept = tuple(
                                    t.lower() for t in
                                    (recipe.get("accept") or ("pass", "ok")))
                                ok = sval.strip().lower().startswith(accept)
                                _record_into(ob_target, fam_name, fam_unit, src,
                                             0.0 if ok else 1.0)
                                bound = True
                    elif kind == "declared_threshold":
                        for path in recipe.get("paths", []):
                            src, node = _find_dotted(ob_blocks, [path],
                                                      _coerce_raw_gating_node)
                            if node is not None:
                                sat = _eval_closes_at(node["value"],
                                                       node["closes_at"])
                                if sat is not None:
                                    _record_into(ob_target, fam_name, fam_unit,
                                                 src, 0.0 if sat else 1.0)
                                    bound = True
                    elif kind == "list_len":
                        for path in recipe.get("paths", []):
                            src, val = _find_dotted(ob_blocks, [path],
                                                     _coerce_list_len)
                            if val is not None:
                                _record_into(ob_target, fam_name, fam_unit, src,
                                             max(0.0, val))
                                bound = True
                    elif kind == "bools_by_shape":
                        # A per-ITEM boolean family whose KEY NAMES are not knowable
                        # when the registry is authored -- one flag per supply net,
                        # per corner, per engine -- so the recipe declares the key
                        # SHAPE (block + prefix/suffix) instead of an alias list.
                        #
                        # WHY: `pdn` publishes PSM's own `check_power_grid` verdict as
                        # `validation.checks.psm_<net>_connected`, and `<net>` is the
                        # design's supply-net name (`vccd`/`vssd` on one design,
                        # `vpwr`/`vgnd` on another). Enumerating those in the registry
                        # would hard-code net names into the progress model -- the same
                        # "the config only knows the names someone typed" defect that
                        # left every VPB/VNB body tie floating. residual = how many
                        # matching flags are NOT true; binds only when at least one
                        # matching key exists, so absence stays `not_assessable`.
                        prefix = recipe.get("prefix") or ""
                        suffix = recipe.get("suffix") or ""
                        matched, failed, first_src = 0, 0, None
                        for block_path in recipe.get("blocks", []):
                            parts = block_path.split(".")
                            for label, block in ob_blocks:
                                if label != parts[0]:
                                    continue
                                node = block
                                for part in parts[1:]:
                                    node = node.get(part) if isinstance(node, dict) \
                                        else None
                                if not isinstance(node, dict):
                                    continue
                                for key, value in node.items():
                                    if not (key.startswith(prefix)
                                            and key.endswith(suffix)):
                                        continue
                                    flag = _coerce_bool(value)
                                    if flag is None:
                                        continue
                                    matched += 1
                                    if not flag:
                                        failed += 1
                                    if first_src is None:
                                        first_src = "%s.%s" % (block_path, key)
                        if matched:
                            _record_into(ob_target, fam_name, fam_unit,
                                         "%s (+%d more)" % (first_src, matched - 1)
                                         if matched > 1 else first_src,
                                         float(failed))
                            bound = True
                    elif kind == "gap":
                        psrc, pval = _find_dotted(
                            ob_blocks, recipe.get("population_paths", []),
                            _coerce_number)
                        asrc, aval = _find_dotted(
                            ob_blocks, recipe.get("achieved_paths", []),
                            _coerce_number)
                        if pval is not None and aval is not None:
                            _record_into(ob_target, fam_name, fam_unit,
                                         "%s-%s" % (psrc, asrc),
                                         max(0.0, pval - aval))
                            bound = True
                    elif kind == "target_delta":
                        src, val = _find_dotted(ob_blocks, recipe.get("paths", []),
                                                 _coerce_number)
                        if val is not None:
                            _record_into(ob_target, fam_name, fam_unit, src,
                                         abs(val - float(recipe.get("target", 0))))
                            bound = True
                    elif kind == "exclusive_floor":
                        # For a "some real work happened" obligation (e.g.
                        # `property_work` must be > 0, not merely recorded) --
                        # NOT the same as `gap`, which is always 0 when
                        # population==achieved regardless of magnitude and so
                        # would be a VACUOUS check here. residual is 0 once
                        # value is strictly above the floor, else the exact
                        # shortfall (floor - value + 1) so a 0 count reads as
                        # a real, non-zero defect rather than an accidental
                        # pass.
                        floor = float(recipe.get("floor", 0))
                        src, val = _find_dotted(ob_blocks, recipe.get("paths", []),
                                                 _coerce_number)
                        if val is not None:
                            _record_into(ob_target, fam_name, fam_unit, src,
                                         0.0 if val > floor else floor - val + 1)
                            bound = True
                if not bound:
                    candidate_paths = sorted({
                        p for r in recipes
                        for p in (r.get("paths", [])
                                  + r.get("population_paths", [])
                                  + r.get("achieved_paths", []))
                    })
                    not_assessable_obligations[fam_name] = {
                        "unit": fam_unit,
                        "residual": None,
                        "components": {},
                        "not_assessable": True,
                        "reason": (
                            "no recorded evidence bound to any declared "
                            "source path for this obligation (checked: %s)"
                            % ", ".join(candidate_paths)),
                    }

        # SILENT NON-BINDING GUARD (<TaskID>): a stage can be MODELLED (`spec` is
        # non-empty) while NONE of its declared source keys (`direct`,
        # `pct_to_100`, `neg_slack`, `bool_ok`, `named_families`) bind to this
        # envelope's actual field names -- e.g. the producer emitted
        # `compile_errors` where funcverif's model expects
        # `errors`/`elaboration_errors`. Before this guard, that silently left
        # `families` empty, so `residual`/`source` stayed None while
        # `gate_closed` (set earlier straight from the raw verdict) stayed
        # whatever the envelope claimed -- an unevidenced PASS. An unrun or
        # unbindable check must never be upgraded to a pass.
        nothing_bound = not families and not deferred_family_metrics
        if nothing_bound:
            declared_gating = _find_declared_gating(blocks)
            if declared_gating:
                # Prefer the PRODUCER'S OWN declared contract over alias
                # whack-a-mole: every metric it marked `class: gating` already
                # carries an explicit `closes_at`, so reading it honours a
                # threshold the producer stated instead of inventing one, and
                # is robust to key-naming drift the model has not caught up
                # with yet.
                for metric_name, src, satisfied in declared_gating:
                    _record("declared_gating", "gate", src,
                            0.0 if satisfied else 1.0)
                progress["residual_source_mode"] = "declared_gating_fallback"
                progress["residual_source_note"] = (
                    "no modelled source key (%s) bound to this envelope; "
                    "residual derived instead from the producer's own "
                    "declared `class: gating` metrics and their stated "
                    "`closes_at` thresholds (%s)"
                    % (spec.get("metric_id"),
                       ", ".join(sorted(n for n, _s, _sat in declared_gating))))
                nothing_bound = False
            else:
                # Truly nothing to derive a residual from: fail closed rather
                # than default to the raw verdict.
                original_gate_closed = progress["gate_closed"]
                progress["alignment"] = "metric_defect"
                progress["alignment_severity"] = (
                    "blocking" if original_gate_closed else "advisory")
                progress["alignment_owner"] = "stage_owner"
                progress["alignment_detail"] = (
                    "stage resolved to a modelled residual (metric_id=%s) but "
                    "none of its declared source keys bound to this "
                    "envelope's fields, and no producer-declared "
                    "`class: gating` metric with an explicit `closes_at` was "
                    "found either; gate_closed forced to False rather than "
                    "defaulting to the raw verdict -- raise against the stage "
                    "owner to add the missing source key or gating "
                    "declaration, never reinterpret as a design defect"
                    % spec.get("metric_id"))
                progress["gate_closed"] = False

        def _finalize_slots(group):
            for slot in group.values():
                worst_src, worst = max(slot["components"].items(),
                                       key=lambda kv: kv[1])
                slot["residual"] = worst
                slot["source"] = worst_src

        # Flow-position-deferred measurements remain first-class evidence, but
        # are intentionally outside the ACTIVE gate families. This is the key
        # distinction that prevents a pre-layout DRV observation from changing
        # a setup-only verdict while retaining every raw count for downstream
        # repair and signoff.
        if deferred_family_metrics:
            _finalize_slots(deferred_family_metrics)
            progress["deferred_family_metrics"] = deferred_family_metrics
            deferred_open = sorted(
                name for name, slot in deferred_family_metrics.items()
                if _family_is_open(slot, progress["closes_at"]))
            if deferred_open:
                progress["deferred_families"] = deferred_open
                declared = _declared_deferral(results) or set()
                declared_all = all(
                    _covered_by_deferral(name, declared)
                    for name in deferred_open)
                progress["deferred_obligation_status"] = (
                    "declared" if declared_all else "implicit_from_flow_scope")

        if families:
            _finalize_slots(families)
            primary = spec.get("primary_family")
            if primary not in families:
                # deterministic fallback: declared family order, never dict order
                for candidate in ("count", "percent_gap", "slack_ns",
                                  "declared_gating"):
                    if candidate in families:
                        primary = candidate
                        break
            if primary not in families:
                # Ultimate deterministic fallback (e.g. a stage whose only
                # populated family is a `named_families` entry with no
                # declared `primary_family`): pick alphabetically so the
                # choice is stable across attempts rather than KeyError-ing.
                primary = sorted(families)[0]
            # A CLOSED declared-primary must never speak for an OPEN sibling.  With
            # multi-family gates the declared primary can sit at 0 (e.g. STA slack
            # met) while another family is violating (DRV dirty) -- and a scalar
            # consumer reading `residual` would then see 0 and conclude "closed".
            # That is precisely how 261 DRV violations were recorded as a passing
            # STA row.  So when the declared primary is closed but some family is
            # not, promote the WORST OPEN family (ties broken by name, so the
            # choice is deterministic across attempts and the trend stays stable).
            closes_at = progress["closes_at"]

            def _is_open(slot):
                return abs(slot["residual"] - closes_at) >= 1e-9

            if primary in families and not _is_open(families[primary]):
                diagnostic_only = set(spec.get("diagnostic_only_families") or ())
                open_fams = sorted((n for n, s in families.items()
                                    if _is_open(s) and n not in diagnostic_only),
                                   key=lambda n: (-families[n]["residual"], n))
                if open_fams:
                    primary = open_fams[0]
                    progress["primary_family_promoted_from"] = \
                        spec.get("primary_family")
            progress["families"] = families
            progress["primary_family"] = primary
            progress["residual"] = families[primary]["residual"]
            progress["source"] = families[primary]["source"]
            progress["unit"] = families[primary].get("unit") or progress["unit"]
            # Flat view retained for reporting only -- NOT for cross-attempt
            # comparison, which must go family by family.
            progress["components"] = {k: v for slot in families.values()
                                      for k, v in slot["components"].items()}
            # The gate is closed only when EVERY family is at its closure value,
            # EXCEPT a family the model itself marks `diagnostic_only_families`
            # (<TaskID> REWORK): such a family is a coverage-completeness reading,
            # not an independent gate, so it must not force `metric_defect` on a
            # genuinely-closed gate the same way an excluded primary must not be
            # promoted from it (see above).
            diagnostic_only = set(spec.get("diagnostic_only_families") or ())
            progress["all_families_closed"] = all(
                abs(slot["residual"] - progress["closes_at"]) < 1e-9
                for name, slot in families.items() if name not in diagnostic_only)

        # Merge not-assessable obligation families back in for VISIBILITY only,
        # after primary/residual/closure are already decided from assessable
        # families alone -- a missing check must never move the gate, but it
        # must not vanish from the basis either (<TaskID>).
        #
        # <TaskID> (`eco`): a name can legitimately be declared by BOTH
        # `named_families` (bare-leaf search, for a flat literal-dotted-key
        # dialect) and `obligation_families` (dotted-path search, for a
        # nested dialect) when two real producer dialects use the SAME
        # obligation name but different key shapes -- MEASURED: without this
        # guard, `obligation_families` failing to bind on the flat-key
        # dialect stamped a `not_assessable` stub over a family
        # `named_families` had ALREADY bound from real evidence on the exact
        # same attempt, discarding a genuine result as if it were missing.
        # Only fill in names not already present.
        if not_assessable_obligations:
            fams = progress.setdefault("families", {})
            actually_not_assessable = []
            for fam_name, stub in not_assessable_obligations.items():
                if fam_name not in fams:
                    fams[fam_name] = stub
                    actually_not_assessable.append(fam_name)
            progress["not_assessable_families"] = sorted(actually_not_assessable)
        elif obligation_specs:
            # `obligation_specs` declared but every family bound: nothing to
            # merge, still worth a stable empty marker for consumers.
            progress["not_assessable_families"] = []

        # Preserve existing named-family commitments that this fresh recompute
        # cannot bind. Dropping a family is basis narrowing: downstream gates
        # would appear to improve only because the measured set shrank. The
        # preserved stubs are visibility-only and non-gating, matching the
        # not-assessable obligation merge above: they must not change the
        # scalar residual, selected source, alignment, or gate_closed state.
        existing_families = (
            results.get("progress", {}).get("families")
            if isinstance(results.get("progress"), dict) else None)
        if isinstance(existing_families, dict) and existing_families:
            fams = progress.setdefault("families", {})
            preserved = []
            not_assessable = set(progress.get("not_assessable_families") or [])
            for fam_name in sorted(set(existing_families) - set(fams)):
                old = existing_families.get(fam_name)
                fams[fam_name] = {
                    "unit": old.get("unit") if isinstance(old, dict) else None,
                    "residual": None,
                    "components": {},
                    "not_assessable": True,
                    "reason": (
                        "family was present in the existing progress block but "
                        "fresh recompute found no bound source; preserved as "
                        "not_assessable to prevent silent basis narrowing"),
                }
                preserved.append(fam_name)
                not_assessable.add(fam_name)
            if preserved:
                progress["preserved_existing_families"] = preserved
                progress["not_assessable_families"] = sorted(not_assessable)

        pop_src, pop = _find(blocks, spec.get("population", []))
        if pop is not None:
            progress["denominator"] = pop
            progress["denominator_source"] = pop_src

        # Closure invariant: residual == closes_at  <=>  gate closes.
        # Only checkable against a DECISIVE verdict. When the envelope carries no
        # usable verdict (not_assessable/error) there is nothing to disagree with,
        # so the check is skipped rather than reported as a metric defect.
        decisive = norm in (VERDICT_PASS, VERDICT_FAIL)
        if progress["residual"] is None:
            # `nothing_bound` staying True here means the SILENT NON-BINDING
            # GUARD above already assigned the correct `metric_defect`
            # alignment and forced `gate_closed` to False; overwriting it with
            # "unknown" would erase that finding. Any other None-residual path
            # (genuinely unmodelled stage) already returned earlier.
            if not nothing_bound:
                progress["alignment"] = "unknown"
        elif not decisive:
            progress["alignment"] = "unknown"
            progress["alignment_detail"] = (
                "no decisive verdict on this envelope (normalized=%s); closure "
                "invariant not checkable" % norm)
        else:
            # Every family must be closed, not just the primary one -- otherwise a
            # clean count family would vouch for a violating timing family.
            at_zero = progress.get("all_families_closed")
            if at_zero is None:
                at_zero = abs(progress["residual"] - progress["closes_at"]) < 1e-9
            if at_zero == progress["gate_closed"]:
                progress["alignment"] = "ok"
            else:
                progress["alignment"] = "metric_defect"
                # Severity routes the finding. `blocking` means a gate was called
                # CLOSED while a residual says otherwise -- that is the laundering
                # the resolution-first ladder forbids, so it must never be
                # consumed as a pass. `advisory` means the gate FAILED with a zero
                # residual: conservative (nothing is being laundered), usually an
                # incomplete metric, so it is reported without blocking the flow.
                severity = "blocking" if progress["gate_closed"] else "advisory"

                # THIRD CASE: a DOCUMENTED, OBLIGATION-CARRYING DEFERRAL.
                #
                # A stage may legitimately close at one flow position on a subset
                # of its checks, because the rest are not yet physically
                # assessable. STA is the worked example: pre-layout there is no
                # SPEF, so net RC and clock skew do not exist, and DRV/hold
                # numbers describe a design that placement and CTS have not
                # touched (AMEND-PRELAYOUT-STA-SCOPE-001). It therefore emits
                # verdict=pass with verdict_full=fail and names what it deferred.
                #
                # MEASURED 2026-09-02: that made EVERY pre-layout STA run with a
                # DRV violation emit a BLOCKING defect, which `_auto_topup_eligible`
                # reads as laundering and uses to suspend autonomy -- on a stage
                # behaving exactly as designed.
                #
                # *** THIS IS NOT A SUPPRESSION. *** The contradiction is still
                # reported; it is CLASSIFIED. Two conditions must BOTH hold, and
                # the second is what keeps the laundering path closed:
                #   1. the envelope DECLARES the deferral (a deferred list AND the
                #      unrelaxed `verdict_full`), so the claim is auditable; and
                #   2. EVERY open family is covered by that declaration. If any
                #      NON-deferred family is open, the deferral does not explain
                #      it and the finding stays BLOCKING. A deferral must never
                #      become a blanket excuse for unrelated violations.
                deferred = _declared_deferral(results)
                if severity == "blocking" and deferred:
                    open_fams = [n for n, s in
                                 (progress.get("families") or {}).items()
                                 if _family_is_open(s, progress["closes_at"])]
                    uncovered = [n for n in open_fams
                                 if not _covered_by_deferral(n, deferred)]
                    if open_fams and not uncovered:
                        severity = "deferred_scope"
                        progress["deferred_families"] = sorted(open_fams)
                        progress["deferred_scope_note"] = (
                            "DEFERRED, NOT WAIVED: the gate closed at this flow "
                            "position with %s still open, and the envelope "
                            "declares those checks as deferred (%s) while "
                            "carrying the unrelaxed verdict_full. The obligation "
                            "to gate them downstream STANDS -- this is a scope "
                            "statement, not a pass."
                            % (", ".join(sorted(open_fams)),
                               ", ".join(sorted(deferred))))
                    elif uncovered:
                        progress["undeferred_open_families"] = sorted(uncovered)

                progress["alignment_severity"] = severity
                progress["alignment_owner"] = "stage_owner"
                progress["alignment_detail"] = (
                    "gate_closed=%s but residual=%s (closes_at=%s, families=%s); "
                    "the metric and the verdict disagree -- raise against the "
                    "stage owner, never reinterpret as a design defect"
                    % (progress["gate_closed"], progress["residual"],
                       progress["closes_at"],
                       sorted(progress.get("families", {}))))
                if severity == "deferred_scope":
                    progress["alignment_detail"] = progress["deferred_scope_note"]
                    progress["alignment_owner"] = "downstream_gate"

        # Stage-declared numerator/denominator ARITHMETIC CONSISTENCY check
        # (see `_BALANCE_CHECKS` above). Runs independently of the residual
        # invariant, and can OVERRIDE an "ok" alignment the invariant produced:
        # a triple can satisfy `residual == closes_at <=> gate_closed` (unproven
        # correctly reads 0 from the verdict-bearing proof) while its paired
        # proved/compared counts still come from a different, superseded run.
        bc_spec = _BALANCE_CHECKS.get(stage_key)
        if bc_spec and blocks:
            _, total_n = _find(blocks, [bc_spec["total"]])
            _, proven_n = _find(blocks, [bc_spec["proven"]])
            _, unproven_n = _find(blocks, [bc_spec["unproven"]])
            if total_n is not None and proven_n is not None and unproven_n is not None:
                balanced = abs(total_n - (proven_n + unproven_n)) < 1e-9
                progress["balance_check"] = {
                    bc_spec["total"]: total_n,
                    bc_spec["proven"]: proven_n,
                    bc_spec["unproven"]: unproven_n,
                    "balanced": balanced,
                }
                if not balanced:
                    superseded = False
                    if stage_key == "lec":
                        signoff = results.get("signoff_evidence")
                        wdc = signoff.get("whole_design_confirmation") \
                            if isinstance(signoff, dict) else None
                        if isinstance(wdc, dict) and wdc.get("ran") is True:
                            wdc_unproven = _as_number(wdc.get("unproven_cells"))
                            superseded = wdc_unproven is not None
                    progress["balance_check"]["balanced"] = balanced
                    if superseded:
                        # <TaskID> REWORK: MEASURED on lec-post-synth.3 -- a
                        # partitioned EQY tally (19 partitions, 14 proven) and
                        # a flat whole-design equiv_induct proof (49/49 cells,
                        # 0 unproven) are BOTH present, and the imbalance is
                        # simply that they are DIFFERENT proof methods over
                        # DIFFERENT units (partitions vs. cells) -- not a stale
                        # numerator/denominator mismatch (<TaskID>'s original
                        # concern). A flat whole-design proof is STRICTLY
                        # STRONGER than a partitioned one (no free partition
                        # inputs to hide a counterexample behind), so it
                        # supersedes rather than contradicts. Leave `alignment`
                        # as whatever the residual invariant already decided
                        # instead of forcing metric_defect.
                        progress["balance_check"]["superseded_by_whole_design_confirmation"] = True
                        progress["balance_check"]["note"] = (
                            "partitioned tally imbalance superseded by a flat "
                            "whole_design_confirmation proof (stronger: no "
                            "free partition inputs); not treated as a "
                            "numerator/denominator staleness defect"
                        )
                    else:
                        progress["alignment"] = "metric_defect"
                        progress["alignment_severity"] = "blocking"
                        progress["alignment_owner"] = "stage_owner"
                        progress["alignment_detail"] = (
                            "arithmetic balance check failed: %s=%s but "
                            "%s(%s)+%s(%s)=%s -- the numerator and denominator were "
                            "sourced from DIFFERENT proof runs (e.g. a partitioned "
                            "EQY tally mixed with a superseding flat whole-design "
                            "proof); raise against the stage owner, never "
                            "reinterpret as a design defect"
                            % (bc_spec["total"], total_n, bc_spec["proven"], proven_n,
                               bc_spec["unproven"], unproven_n, proven_n + unproven_n))

        # <TaskID> (REOPENED, item 1): HARD RULE, not a one-off -- a gate must
        # never report CLOSED while a `not_assessable` family covers one of
        # the stage's declared ACCEPTANCE-CRITICAL obligations. Zero
        # assessable defects out of N families is not the same claim as zero
        # out of the FULL declared basis: an acceptance-criterion family that
        # never bound (e.g. synthesis's `area`, when no <myDesign-B>-scoped budget
        # exists to check `cell_area` against) means the criterion was never
        # actually verified, not that it passed. This is a real, visible
        # finding -- `verdict_gate_closed` preserves what the raw verdict
        # claimed, the same pattern already used for `formal`/`domain-map`
        # above -- and can flip a previously-closed gate open; that is the
        # correct outcome, not a regression to tune away.
        acceptance_critical = set(spec.get("acceptance_critical_obligations") or ())
        if acceptance_critical and progress.get("gate_closed"):
            blocking_gaps = sorted(
                acceptance_critical & set(progress.get("not_assessable_families") or ()))
            if blocking_gaps:
                progress["verdict_gate_closed"] = progress["gate_closed"]
                progress["gate_closed"] = False
                progress["alignment"] = "metric_defect"
                progress["alignment_severity"] = "blocking"
                progress["alignment_owner"] = "stage_owner"
                progress["alignment_detail"] = (
                    "gate reported closed while acceptance-critical "
                    "obligation(s) %s are not_assessable (no recorded "
                    "evidence bound to any declared source path, or no "
                    "declared gating threshold for it); a gate must never "
                    "close while a family covering an acceptance criterion "
                    "is unassessed -- raise against the stage owner to "
                    "supply the missing evidence/threshold, never waive or "
                    "tune this closed" % ", ".join(blocking_gaps))

        if stage_key == "domain-map" \
                and progress.get("alignment_severity") == "blocking":
            progress["verdict_gate_closed"] = progress["gate_closed"]
            progress["gate_closed"] = False
            progress["alignment_detail"] += (
                "; canonical domain-map progress is fail-closed until every "
                "machine-derived family reaches zero")

        # <TaskID> FIX 1: a `formal` gate must not stay reported CLOSED when its
        # own envelope shows the gating population was narrowed below the
        # authored population (see the `gap` recipes on `unproven_assertions`
        # / `counterexamples` / `self_waivers` above) -- a stage must not be
        # able to shrink its own denominator and then report a clean residual
        # over the remainder. This is fail-closed, not a tuned threshold: a
        # `formal` envelope whose gating and authored populations agree (the
        # <myDesign-A>.1/formal.1 and <myDesign-B>.1/formal.2 dialects, MEASURED
        # unaffected) never reaches `alignment_severity == "blocking"` here and
        # so is untouched.
        if stage_key == "formal" \
                and progress.get("alignment_severity") == "blocking":
            progress["verdict_gate_closed"] = progress["gate_closed"]
            progress["gate_closed"] = False
            progress["alignment_detail"] += (
                "; formal progress is fail-closed until the gating population "
                "is reconciled with the authored population (a narrowed "
                "denominator is an undisclosed self-waiver, not a closed gate)")
    except Exception as exc:            # never break a tool over bookkeeping
        progress["alignment"] = "unknown"
        progress["error"] = str(exc)
    return progress


def stage_key_contract(results, stage=None):
    """Return the exact obligation-key contract and its binding state.

    The contract is derived from ``STAGE_RESIDUALS`` rather than copied into a
    sidecar, so the authoring check cannot drift from the model that computes
    progress. ``advisory`` identifies the <TaskID-A>/<TaskID-B>/<TaskID-C> recurrence: a pass
    still reports a closed gate because some family bound, while one or more
    registered exact-path obligation families remained unassessed. Gate policy
    is unchanged here; acceptance-critical families are already handled by the
    fail-closed rule in ``compute_progress``.
    """
    if not isinstance(results, dict):
        return {
            "stage": None,
            "metric_id": None,
            "verdict_normalized": VERDICT_NOT_ASSESSABLE,
            "gate_closed": False,
            "advisory": False,
            "declared_paths": [],
            "bound_families": [],
            "unbound_families": [],
            "families": {},
        }

    requested_stage = stage or results.get("stage") or results.get("tool")
    stage_key = normalize_stage(requested_stage)
    spec = STAGE_RESIDUALS.get(stage_key, {})
    obligation_specs = spec.get("obligation_families") or {}
    progress = compute_progress(results, requested_stage)
    unbound = set(progress.get("not_assessable_families") or ())
    families = {}
    all_paths = set()
    for family, recipes in sorted(obligation_specs.items()):
        paths = sorted({
            path
            for recipe in recipes
            for path in (
                recipe.get("paths", [])
                + recipe.get("population_paths", [])
                + recipe.get("achieved_paths", [])
            )
        })
        all_paths.update(paths)
        families[family] = {
            "declared_paths": paths,
            "bound": family not in unbound,
        }

    unbound_families = sorted(name for name in families if name in unbound)
    bound_families = sorted(name for name in families if name not in unbound)
    advisory = (
        progress.get("verdict_normalized") == VERDICT_PASS
        and progress.get("gate_closed") is True
        and bool(unbound_families)
    )
    return {
        "stage": stage_key,
        "metric_id": spec.get("metric_id"),
        "verdict_normalized": progress.get("verdict_normalized"),
        "gate_closed": progress.get("gate_closed") is True,
        "advisory": advisory,
        "declared_paths": sorted(all_paths),
        "bound_families": bound_families,
        "unbound_families": unbound_families,
        "families": families,
    }


_DEFERRAL_FIELDS = ("deferred_to_post_cts", "deferred_checks", "deferred")


def _declared_deferral(results):
    """Return the set of check names an envelope DECLARES it deferred, else None.

    A deferral is only credible if the envelope also carries the UNRELAXED answer
    (`verdict_full`). Requiring both is what stops a stage from excusing its own
    open gate by merely asserting "deferred": it must simultaneously publish the
    strict verdict that says it did not actually close. A deferral without that
    is an unsupported claim and is deliberately NOT honoured here.
    """
    if not isinstance(results, dict):
        return None
    for block in (results.get("signoff_evidence"), results.get("signoff"),
                  results.get("qor_metrics"), results):
        if not isinstance(block, dict):
            continue
        if not block.get("verdict_full"):
            continue
        for field in _DEFERRAL_FIELDS:
            raw = block.get(field)
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, (list, tuple)) and raw:
                names = {str(x).strip().lower() for x in raw if str(x).strip()}
                if names:
                    return names
    return None


def _family_is_open(slot, closes_at):
    """True when a unit family still carries a residual away from its closing point."""
    if isinstance(slot, dict):
        val = slot.get("residual")
    else:
        val = slot
    if val is None:
        return False
    try:
        return abs(float(val) - float(closes_at)) >= 1e-9
    except (TypeError, ValueError):
        return False


def _covered_by_deferral(family, deferred):
    """Is this family named by the deferral declaration?

    Families are dotted (`drv.max_fanout`), while a deferral names the GROUP
    (`drv`). Matching is on the dotted prefix or the whole name -- never a bare
    substring, or a deferral of `drv` would also silently excuse a family merely
    containing those letters.
    """
    fam = str(family).strip().lower()
    for d in deferred:
        if fam == d or fam.startswith(d + "."):
            return True
    return False


def stamp_progress(results, stage=None):
    """Attach the progress block to an envelope in place. Never raises.

    Non-destructive except for domain-map, whose closure block must always be
    machine-derived from the envelope rather than accepted from its producer.
    """
    try:
        if not isinstance(results, dict):
            return results
        existing = results.get("progress")
        stage_key = normalize_stage(stage or results.get("stage"))
        if stage_key != "domain-map" \
                and isinstance(existing, dict) and existing.get("schema") == SCHEMA \
                and existing.get("residual") is not None:
            return results
        results["progress"] = compute_progress(results, stage)
    except Exception:
        pass
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the registry-derived stage key contract without "
            "modifying the Common Design Envelope."))
    parser.add_argument("cde", help="CDE JSON path, or - for stdin")
    parser.add_argument("--stage", help="override the CDE stage/tool value")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="emit the exact obligation paths and their current binding state")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("--dry-run is required; this command never writes a CDE")
    try:
        if args.cde == "-":
            envelope = json.load(sys.stdin)
        else:
            with open(args.cde, "r", encoding="utf-8-sig") as fh:
                envelope = json.load(fh)
    except (OSError, ValueError) as exc:
        print("ERROR: could not read CDE %s: %s" % (args.cde, exc),
              file=sys.stderr)
        return 2
    print(json.dumps(stage_key_contract(envelope, args.stage),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
