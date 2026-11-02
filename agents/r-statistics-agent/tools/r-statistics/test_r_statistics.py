"""Container integration tests; build r-statistics:1.1.0 before running."""

import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL_DIR = Path(__file__).resolve().parent
IMAGE = os.environ.get("R_STATISTICS_IMAGE", "r-statistics:1.1.0")


class RStatisticsTests(unittest.TestCase):
    def run_r(self, *arguments: str, mounts: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
        command = [
            "docker", "run", "--rm", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        ]
        for mount in mounts:
            command.extend(["--mount", mount])
        command.extend([IMAGE, "Rscript", "--vanilla", *arguments])
        return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)

    def test_runtime_packages_and_non_root_mount_permissions(self) -> None:
        with (TOOL_DIR / "packages.csv").open(newline="", encoding="utf-8") as stream:
            packages = list(csv.DictReader(stream))
        version_checks = "; ".join(
            f'stopifnot(packageVersion("{p["package"]}") == package_version("{p["version"]}"))'
            for p in packages
        )
        result = self.run_r(
            "-e",
            'stopifnot(getRversion() == "4.5.3", '
            'system2("id", "-u", stdout=TRUE) == "10001"); '
            'for (p in c("stats", "utils", "graphics", "grDevices", "MASS", '
            '"Matrix", "survival", "lattice")) loadNamespace(p); '
            'for (p in c("/output", "/workdir", Sys.getenv("HOME"))) { '
            'f <- tempfile(tmpdir=p); writeLines("ok", f); unlink(f) }; '
            f'{version_checks}; cat("runtime-ok")',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("runtime-ok", result.stdout)

    def test_csv_regression_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            result = self.run_r(
                "/analysis.R",
                mounts=(
                    f"type=bind,source={TOOL_DIR / 'examples'},target=/input,readonly",
                    f"type=bind,source={TOOL_DIR / 'examples' / 'analysis.R'},target=/analysis.R,readonly",
                    f"type=bind,source={output},target=/output",
                ),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Analyzed 5 rows; slope = 2.100", result.stdout)
            output_path = Path(output)
            with (output_path / "coefficients.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["term"] for row in rows], ["(Intercept)", "x"])
            self.assertAlmostEqual(float(rows[0]["Estimate"]), 0.7)
            self.assertAlmostEqual(float(rows[1]["Estimate"]), 2.1)
            for filename in ("scatter.png", "diagnostics.png"):
                content = (output_path / filename).read_bytes()
                self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertGreater(len(content), 1000)
            self.assertIn("R version 4.5.3", (output_path / "session-info.txt").read_text())
            self.assertIn("Residual standard error", (output_path / "model-summary.txt").read_text())
            self.assertEqual(
                (output_path / "analysis.R").read_bytes(),
                (TOOL_DIR / "examples" / "analysis.R").read_bytes(),
            )

    def test_invalid_input_fails_without_results(self) -> None:
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as output:
            (Path(input_dir) / "observations.csv").write_text("x,y\n1,2\n2,NA\n3,4\n", encoding="utf-8")
            result = self.run_r(
                "/analysis.R",
                mounts=(
                    f"type=bind,source={input_dir},target=/input,readonly",
                    f"type=bind,source={TOOL_DIR / 'examples' / 'analysis.R'},target=/analysis.R,readonly",
                    f"type=bind,source={output},target=/output",
                ),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("finite numeric values", result.stderr)
            self.assertEqual(list(Path(output).iterdir()), [])

    def test_script_errors_propagate(self) -> None:
        result = self.run_r("-e", 'stop("expected-analysis-error")')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected-analysis-error", result.stderr)

    def test_ggplot_headless_png(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            result = self.run_r(
                "-e",
                'stopifnot(requireNamespace("ggplot2", quietly=TRUE), capabilities("cairo")); '
                'p <- ggplot2::ggplot(data.frame(x=1:5,y=c(3,4,8,9,11)), '
                'ggplot2::aes(x=x,y=y)) + ggplot2::geom_point(); '
                'ggplot2::ggsave("/output/ggplot.png", p, device="png", '
                'type="cairo", width=4, height=3, dpi=100)',
                mounts=(f"type=bind,source={output},target=/output",),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            content = (Path(output) / "ggplot.png").read_bytes()
            self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(content), 1000)

    def test_empty_outliers_and_degenerate_columns(self) -> None:
        result = self.run_r(
            "-e",
            """
iqr_outliers <- function(values, variable) {
  if (!is.numeric(values) || !any(is.finite(values))) {
    stop("Outlier checks require at least one finite numeric observation.")
  }
  finite <- values[is.finite(values)]
  bounds <- unname(quantile(finite, c(0.25, 0.75)))
  spread <- diff(bounds)
  lower <- bounds[1] - 1.5 * spread
  upper <- bounds[2] + 1.5 * spread
  idx <- which(is.finite(values) & (values < lower | values > upper))
  data.frame(
    variable = rep(variable, length(idx)),
    row = idx,
    value = values[idx],
    lower = rep(lower, length(idx)),
    upper = rep(upper, length(idx)),
    row.names = NULL
  )
}
empty <- iqr_outliers(as.double(1:5), "x")
constant <- iqr_outliers(rep(2, 5), "constant")
flagged <- iqr_outliers(c(1, 2, 3, 4, 100), "flagged")
stopifnot(
  nrow(empty) == 0L,
  nrow(constant) == 0L,
  identical(names(empty), c("variable", "row", "value", "lower", "upper")),
  is.character(empty$variable),
  is.integer(empty$row),
  is.double(empty$value),
  nrow(flagged) == 1L,
  flagged$row == 5L,
  nrow(rbind(empty, constant, flagged)) == 1L
)
for (values in list(c(NA_real_, NA_real_), numeric(0))) {
  message <- tryCatch(
    { iqr_outliers(values, "invalid"); stop("Expected validation failure.") },
    error = conditionMessage
  )
  stopifnot(identical(message, "Outlier checks require at least one finite numeric observation."))
}
cat("edge-cases-ok\\n")
""",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("edge-cases-ok", result.stdout)

    def test_degenerate_regression_inputs_fail_without_artifacts(self) -> None:
        for label, data, message in (
            ("all-missing", "x,y\nNA,NA\nNA,NA\nNA,NA\n", "finite numeric values"),
            ("constant", "x,y\n1,2\n1,3\n1,4\n", "two distinct x values"),
            ("small", "x,y\n1,2\n2,3\n", "at least three observations"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as inputs, tempfile.TemporaryDirectory() as output:
                (Path(inputs) / "observations.csv").write_text(data, encoding="utf-8")
                result = self.run_r(
                    "/analysis.R",
                    mounts=(
                        f"type=bind,source={inputs},target=/input,readonly",
                        f"type=bind,source={TOOL_DIR / 'examples' / 'analysis.R'},target=/analysis.R,readonly",
                        f"type=bind,source={output},target=/output",
                    ),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(list(Path(output).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
