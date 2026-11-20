"""Build-time capability gate for chip-qor-analytics. NON-VACUOUS BY DESIGN.

Run during `podman build`; a non-zero exit fails the build.

The defect this tool was repaired for is a SIGN ERROR with a plausible-looking
output: without polarity, a slack improvement and an area regression are
numerically identical (|6%|) and were both reported as regressions. A gate that
only checked "does it return a number" would pass on the broken version, so
every check below pins the DIRECTION and the classification, not just the shape.
"""

import sys

sys.path.insert(0, "/app")

import qor_stats  # noqa: E402


def main():
    # 1. Polarity of the metrics most likely to be inverted.
    #    Slack MAXIMIZES (it is negative when timing fails); area MINIMIZES.
    assert qor_stats.resolve_polarity("wns")["polarity"] == "max"
    assert qor_stats.resolve_polarity("slack")["polarity"] == "max"
    assert qor_stats.resolve_polarity("area")["polarity"] == "min"
    assert qor_stats.resolve_polarity("leakage_power")["polarity"] == "min"
    assert qor_stats.resolve_polarity("coverage")["polarity"] == "max"
    assert qor_stats.resolve_polarity("drc_violations")["polarity"] == "min"

    # 2. THE ORIGINAL DEFECT. Same magnitude, opposite meaning.
    slack_up = qor_stats.classify_change("wns", -0.94, -1.0)      # less negative
    area_up = qor_stats.classify_change("area", 106.0, 100.0)
    assert slack_up["direction"] == "improvement", slack_up
    assert area_up["direction"] == "regression", area_up
    assert abs(slack_up["delta_percent"]) == abs(area_up["delta_percent"]) == 6.0, (
        slack_up, area_up)

    # 3. Unknown polarity must NOT be guessed.
    u = qor_stats.classify_change("frobnication_index", 10, 5)
    assert u["direction"] == "unclassified", u
    assert u["polarity"] is None, u

    # 4. A caller declaration wins over the table.
    d = qor_stats.classify_change("frobnication_index", 10, 5,
                                  {"frobnication_index": "max"})
    assert d["direction"] == "improvement", d

    # 5. Target-band metrics are not monotone and must not be judged.
    assert qor_stats.resolve_polarity("utilization")["polarity"] is None

    # 6. Ordering: run.10 must follow run.2, not sit between run.1 and run.2.
    rows = [{"id": "run.%d" % i, "area": 100.0 + i} for i in (1, 2, 10)]
    ordered, basis = qor_stats.order_runs(list(reversed(rows)))
    assert [r["id"] for r in ordered] == ["run.1", "run.2", "run.10"], ordered
    assert basis["basis"] == "natural_sort_of_id", basis

    # 7. Trajectory must detect a real degrading trend AND label it by polarity.
    growing = [{"id": "r%d" % i, "order": i, "area": 100.0 + 5 * i}
               for i in range(6)]
    t = qor_stats.trajectory(growing, "area")
    assert t["assessable"] and t["direction"] == "degrading", t
    assert t["slope_per_run"] > 0 and t["r_squared"] > 0.99, t

    #    ... and the same rising numbers on a MAXIMIZE metric are improving.
    t2 = qor_stats.trajectory(
        [{"id": "r%d" % i, "order": i, "coverage": 60.0 + 5 * i} for i in range(6)],
        "coverage")
    assert t2["direction"] == "improving", t2

    # 8. Two points must NOT yield a trend (they always fit R^2 = 1).
    t3 = qor_stats.trajectory(
        [{"id": "a", "order": 0, "area": 1.0}, {"id": "b", "order": 1, "area": 2.0}],
        "area")
    assert t3["assessable"] is False and t3["slope_per_run"] is None, t3

    # 9. Per-metric N must reflect only the runs that reported the metric.
    sparse = [{"id": "r%d" % i, "order": i,
               "area": (100.0 + i) if i % 2 == 0 else None} for i in range(6)]
    t4 = qor_stats.trajectory(sparse, "area")
    assert t4["n_used"] == 3 and t4["n_runs"] == 6, t4

    # 10. Comparability: mixing corners must be caught; missing context must be
    #     not_assessable rather than "comparable".
    bad = qor_stats.comparability([{"id": "a", "corner": "tt"},
                                   {"id": "b", "corner": "ff"}])
    assert bad["comparable"] is False and "corner" in bad["conflicts"], bad
    unknown = qor_stats.comparability([{"id": "a"}, {"id": "b"}])
    assert unknown["assessable"] is False and unknown["comparable"] is None, unknown

    print("QOR_ANALYTICS_CAPABILITY_OK")


if __name__ == "__main__":
    main()
