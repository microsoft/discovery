import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import debug_utils


class ReducedDeterminismInput(unittest.TestCase):
    def test_reexecutes_the_materialized_minimal_stimulus(self):
        work = Path(__file__).resolve().parent
        observed = []

        def replay(command, **kwargs):
            self.assertNotIn("{input}", command)
            candidate = json.loads(Path(shlex.split(command)[-1]).read_text(encoding="utf-8"))
            observed.append(candidate)
            return dict(assessable=True, deterministic=True, runs=3,
                        distinct_outcomes=1, failure_reproduced=True,
                        basis="unit_test_replay")

        try:
            with mock.patch.object(debug_utils, "_WORK_DIR", str(work)), \
                    mock.patch.object(debug_utils, "_analyze_waveform", return_value=({}, {})), \
                    mock.patch.object(debug_utils.reproducer, "make_command_oracle",
                                      return_value=lambda values: 7 in values), \
                    mock.patch.object(debug_utils.reproducer, "check_determinism", side_effect=replay), \
                    mock.patch.object(debug_utils, "_cde", side_effect=lambda **kw: kw):
                result = debug_utils._reduce(dict(
                    scenario="reduce", stimulus=[1, 2, 7, 9], fail_regex="MISMATCH",
                    repro_cmd="python3 oracle.py {input}", determinism_runs=3))
            self.assertEqual(observed, [[7]])
            self.assertEqual(result["validation"]["verdict"], "pass")
            self.assertEqual(result["signoff"]["minimal_reproducer"]["minimal_stimulus"], [7])
        finally:
            (work / "determinism_stimulus.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
