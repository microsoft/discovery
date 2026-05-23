"""
statagent_utils.py - Statistical Validation Utilities for Discovery Platform

Provides comprehensive statistical validation tools for evaluating computational
workflow results: descriptive statistics, correlation analysis, hypothesis testing,
effect sizes, model evaluation, bootstrap confidence intervals, Bayesian analysis,
domain-specific thresholds, and HTML report generation.
"""

import os
import sys
import glob
import shutil
import logging
import numpy as np
import pandas as pd
import json
import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from datetime import datetime


# ============================================================================
# Directory Globals & Setup / Teardown
# ============================================================================

INPUT_DIR = '/input'
OUTPUT_DIR = '/output'
WORK_DIR = '/workdir'


def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize directories, logging, and copy input files to workdir."""
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    for d in [WORK_DIR, OUTPUT_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)

    # Copy input files to workdir for convenience
    if os.path.exists(INPUT_DIR) and os.path.realpath(INPUT_DIR) != os.path.realpath(WORK_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)

    logging.info(f"statagent initialized. Working dir: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else []}")


def quick_finish():
    """Copy key output files from workdir to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.json', '*.csv', '*.png', '*.html', '*.svg', '*.log']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def save_final_results(results, output_files=None, file_descriptions=None,
                       status="completed"):
    """Save structured results to final_results.json (MANDATORY for every script)."""
    def _convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient='records')
        elif isinstance(obj, pd.Series):
            return obj.to_dict()
        elif isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        return obj

    final = {"status": status, "summary": _convert(results)}
    if output_files:
        final["output_files"] = _convert(output_files)
    if file_descriptions:
        final["file_descriptions"] = _convert(file_descriptions)

    path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(path, 'w') as f:
        json.dump(final, f, indent=2, default=str)
    logging.info(f"Saved final_results.json → {path}")

# Statistical packages
from scipy import stats
from scipy.stats import (
    shapiro, normaltest, levene, bartlett,
    ttest_ind, ttest_rel, mannwhitneyu, wilcoxon,
    f_oneway, kruskal, chi2_contingency, spearmanr,
    pearsonr, kendalltau, pointbiserialr
)
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.stattools import durbin_watson
from statsmodels.stats.power import TTestIndPower
import pingouin as pg

# ML packages
from sklearn.metrics import (
    r2_score, mean_squared_error, mean_absolute_error,
    accuracy_score, precision_score, recall_score, f1_score,
    matthews_corrcoef, cohen_kappa_score, roc_auc_score,
    average_precision_score, confusion_matrix, classification_report,
    explained_variance_score, max_error
)


# ============================================================================
# Domain-Specific Thresholds
# ============================================================================

DOMAIN_THRESHOLDS = {
    "qsar": {
        "description": "QSAR/QSPR model validation",
        "r_squared": {"good": 0.7, "acceptable": 0.5, "poor": 0.3},
        "rmse_relative": {"good": 0.1, "acceptable": 0.2, "poor": 0.3},
        "correlation": {"good": 0.8, "acceptable": 0.6, "poor": 0.4},
        "cross_val_q2": {"good": 0.6, "acceptable": 0.5, "poor": 0.3},
        "overfitting_ratio": {"good": 1.1, "acceptable": 1.2, "poor": 1.5},
    },
    "docking": {
        "description": "Molecular docking validation",
        "rmsd_redocking": {"good": 2.0, "acceptable": 3.0, "poor": 4.0},
        "enrichment_factor": {"good": 10, "acceptable": 5, "poor": 2},
        "correlation_exp": {"good": 0.6, "acceptable": 0.4, "poor": 0.2},
        "score_range_min": {"good": -15, "acceptable": -20, "poor": -25},
        "pose_convergence": {"good": 0.8, "acceptable": 0.5, "poor": 0.3},
    },
    "md_simulation": {
        "description": "Molecular dynamics simulation validation",
        "rmsd_equilibrium": {"good": 0.3, "acceptable": 0.5, "poor": 1.0},
        "energy_drift": {"good": 0.01, "acceptable": 0.05, "poor": 0.1},
        "temperature_stability": {"good": 2, "acceptable": 5, "poor": 10},
        "pressure_stability": {"good": 50, "acceptable": 100, "poor": 200},
        "density_deviation": {"good": 0.01, "acceptable": 0.02, "poor": 0.05},
    },
    "quantum_chemistry": {
        "description": "Quantum chemistry calculation validation",
        "scf_convergence": {"good": 1e-8, "acceptable": 1e-6, "poor": 1e-4},
        "geometry_convergence": {"good": 1e-5, "acceptable": 1e-4, "poor": 1e-3},
        "basis_set_superposition": {"good": 0.5, "acceptable": 1.0, "poor": 2.0},
        "imaginary_frequencies": {"good": 0, "acceptable": 1, "poor": 3},
        "t1_diagnostic": {"good": 0.02, "acceptable": 0.04, "poor": 0.05},
    },
    "free_energy": {
        "description": "Free energy perturbation / thermodynamic integration",
        "hysteresis": {"good": 0.5, "acceptable": 1.0, "poor": 2.0},
        "convergence_overlap": {"good": 0.3, "acceptable": 0.1, "poor": 0.03},
        "mue_vs_experiment": {"good": 1.0, "acceptable": 1.5, "poor": 2.0},
        "correlation_exp": {"good": 0.7, "acceptable": 0.5, "poor": 0.3},
        "rmse_exp": {"good": 1.0, "acceptable": 1.5, "poor": 2.5},
    },
    "admet": {
        "description": "ADMET property prediction",
        "classification_auc": {"good": 0.85, "acceptable": 0.75, "poor": 0.65},
        "classification_mcc": {"good": 0.5, "acceptable": 0.3, "poor": 0.1},
        "regression_r2": {"good": 0.6, "acceptable": 0.4, "poor": 0.2},
        "logp_rmse": {"good": 0.5, "acceptable": 0.8, "poor": 1.2},
        "solubility_rmse": {"good": 0.7, "acceptable": 1.0, "poor": 1.5},
    },
    "general_ml": {
        "description": "General machine learning model validation",
        "r_squared": {"good": 0.8, "acceptable": 0.6, "poor": 0.4},
        "accuracy_balanced": {"good": 0.85, "acceptable": 0.7, "poor": 0.55},
        "f1_score": {"good": 0.8, "acceptable": 0.6, "poor": 0.4},
        "mcc": {"good": 0.6, "acceptable": 0.4, "poor": 0.2},
        "overfitting_ratio": {"good": 1.1, "acceptable": 1.2, "poor": 1.5},
    },
}


def get_domain_thresholds(domain: str) -> dict:
    """Get thresholds for a specific domain. Returns general_ml if domain not found."""
    return DOMAIN_THRESHOLDS.get(domain, DOMAIN_THRESHOLDS["general_ml"])


def evaluate_metric(value: float, metric_name: str, domain: str = "general_ml",
                    lower_is_better: bool = False) -> dict:
    """Evaluate a metric against domain-specific thresholds.

    Returns: {value, rating, threshold_good, threshold_acceptable, threshold_poor, domain}
    rating is one of: 'good', 'acceptable', 'poor', 'unknown'
    """
    thresholds = get_domain_thresholds(domain)
    if metric_name not in thresholds:
        return {"value": value, "rating": "unknown", "domain": domain, "metric": metric_name}

    t = thresholds[metric_name]
    if lower_is_better:
        if value <= t["good"]:
            rating = "good"
        elif value <= t["acceptable"]:
            rating = "acceptable"
        else:
            rating = "poor"
    else:
        if value >= t["good"]:
            rating = "good"
        elif value >= t["acceptable"]:
            rating = "acceptable"
        else:
            rating = "poor"

    return {
        "value": value, "rating": rating, "domain": domain, "metric": metric_name,
        "threshold_good": t["good"], "threshold_acceptable": t["acceptable"],
        "threshold_poor": t["poor"]
    }


# ============================================================================
# ValidationState - Workflow Confidence Tracker
# ============================================================================

class ValidationState:
    """Tracks cumulative validation confidence across all workflow steps.

    Maintains a running confidence score (0-100) that degrades as checks fail.
    Records all checks with categories, severities, and metrics for reporting.
    Can be serialized to JSON and resumed across pipeline steps.
    """

    def __init__(self, workflow_name: str = "Unnamed Workflow"):
        self.workflow_name = workflow_name
        self.checks: List[dict] = []
        self.created_at = datetime.utcnow().isoformat()
        self._step_counter = 0

    def add_check(self, name: str, category: str, passed: bool,
                  details: str = "", severity: str = "warning",
                  metrics: Optional[dict] = None, step: Optional[str] = None):
        """Record a validation check result.

        Args:
            name: Short description of the check
            category: One of 'assumption', 'significance', 'effect_size',
                      'model_quality', 'data_quality', 'domain_specific'
            passed: Whether the check passed
            details: Human-readable description of the result
            severity: 'critical', 'warning', or 'info'
            metrics: Dict of metric values for machine-readable output
            step: Pipeline step name (for intermediate validation)
        """
        self._step_counter += 1
        self.checks.append({
            "id": self._step_counter,
            "name": name,
            "category": category,
            "passed": passed,
            "details": details,
            "severity": severity,
            "metrics": metrics or {},
            "step": step or "global",
            "timestamp": datetime.utcnow().isoformat()
        })

    def confidence_score(self) -> float:
        """Compute overall confidence score (0-100).

        Scoring:
        - Start at 100
        - Each failed critical check: -15 points
        - Each failed warning check: -8 points
        - Each failed info check: -3 points
        - Bonus: +2 per passed assumption check (max +10)
        - Floor at 0, cap at 100
        """
        if not self.checks:
            return 100.0

        score = 100.0
        penalties = {"critical": 15, "warning": 8, "info": 3}

        for check in self.checks:
            if not check["passed"]:
                score -= penalties.get(check["severity"], 5)

        # Bonus for passed assumption checks
        assumption_passes = sum(
            1 for c in self.checks
            if c["category"] == "assumption" and c["passed"]
        )
        score += min(assumption_passes * 2, 10)

        return max(0.0, min(100.0, score))

    def confidence_label(self) -> str:
        """Human-readable confidence label."""
        score = self.confidence_score()
        if score >= 90:
            return "HIGH"
        elif score >= 70:
            return "MODERATE"
        elif score >= 50:
            return "LOW"
        else:
            return "VERY LOW"

    def summary(self) -> dict:
        """Get summary of all validation checks."""
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c["passed"])
        failed = total - passed

        by_category = {}
        for c in self.checks:
            cat = c["category"]
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "failed": 0, "total": 0}
            by_category[cat]["total"] += 1
            if c["passed"]:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1

        critical_failures = [
            c for c in self.checks
            if not c["passed"] and c["severity"] == "critical"
        ]

        by_step = {}
        for c in self.checks:
            step = c["step"]
            if step not in by_step:
                by_step[step] = {"passed": 0, "failed": 0, "total": 0}
            by_step[step]["total"] += 1
            if c["passed"]:
                by_step[step]["passed"] += 1
            else:
                by_step[step]["failed"] += 1

        return {
            "workflow_name": self.workflow_name,
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "confidence_score": round(self.confidence_score(), 1),
            "confidence_label": self.confidence_label(),
            "checks_by_category": by_category,
            "checks_by_step": by_step,
            "critical_failures": critical_failures,
            "all_checks": self.checks,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.summary(), indent=2, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> 'ValidationState':
        """Deserialize from JSON (for resuming validation across steps)."""
        data = json.loads(json_str) if isinstance(json_str, str) else json_str
        state = cls(workflow_name=data.get("workflow_name", "Resumed"))
        state.checks = data.get("all_checks", [])
        state._step_counter = len(state.checks)
        state.created_at = data.get("created_at", datetime.utcnow().isoformat())
        return state


# ============================================================================
# DescriptiveAnalyzer - Summary Statistics with Error Bars
# ============================================================================

class DescriptiveAnalyzer:
    """Compute descriptive statistics with error bars and diagnostics."""

    def __init__(self, data, column: Optional[str] = None):
        if isinstance(data, pd.DataFrame):
            if column is None:
                raise ValueError("column must be specified for DataFrame input")
            self.values = data[column].dropna().values.astype(float)
            self.column_name = column
        elif isinstance(data, pd.Series):
            self.values = data.dropna().values.astype(float)
            self.column_name = data.name or "values"
        else:
            self.values = np.array(data, dtype=float)
            self.values = self.values[~np.isnan(self.values)]
            self.column_name = column or "values"

    def describe(self) -> dict:
        """Full descriptive report with error bars and diagnostics."""
        v = self.values
        n = len(v)
        if n == 0:
            return {"error": "No data", "n": 0}

        mean_val = float(np.mean(v))
        std_val = float(np.std(v, ddof=1)) if n > 1 else 0.0
        sem_val = std_val / np.sqrt(n) if n > 0 else 0.0

        # 95% CI for the mean
        if n > 1:
            ci = stats.t.interval(0.95, df=n - 1, loc=mean_val, scale=sem_val)
        else:
            ci = (mean_val, mean_val)

        q1, median_val, q3 = np.percentile(v, [25, 50, 75])

        result = {
            "column": self.column_name,
            "n": n,
            "mean": round(mean_val, 6),
            "median": round(float(median_val), 6),
            "std": round(std_val, 6),
            "sem": round(float(sem_val), 6),
            "ci_95_lower": round(float(ci[0]), 6),
            "ci_95_upper": round(float(ci[1]), 6),
            "iqr": round(float(q3 - q1), 6),
            "skewness": round(float(stats.skew(v)), 4) if n > 2 else None,
            "kurtosis": round(float(stats.kurtosis(v)), 4) if n > 3 else None,
            "min": round(float(np.min(v)), 6),
            "max": round(float(np.max(v)), 6),
            "q1": round(float(q1), 6),
            "q3": round(float(q3), 6),
            "normality_test": self.test_normality(),
            "outliers": self.detect_outliers(),
        }
        return result

    def test_normality(self) -> dict:
        """Test normality (auto-selects method based on sample size)."""
        v = self.values
        n = len(v)
        if n < 3:
            return {"method": "none", "reason": "n < 3", "is_normal": None, "p_value": None}

        try:
            if n < 5000:
                method = "Shapiro-Wilk"
                stat, p = shapiro(v)
            else:
                method = "D'Agostino-Pearson"
                stat, p = normaltest(v)
        except Exception as e:
            return {"method": "error", "reason": str(e), "is_normal": None, "p_value": None}

        return {
            "method": method,
            "statistic": round(float(stat), 6),
            "p_value": float(p),
            "is_normal": p > 0.05,
            "interpretation": "Normal (p > 0.05)" if p > 0.05 else "Non-normal (p <= 0.05)"
        }

    def detect_outliers(self, method: str = "auto") -> dict:
        """Detect outliers using IQR or Z-score method."""
        v = self.values
        n = len(v)
        if n < 4:
            return {"count": 0, "indices": [], "method": "none", "reason": "n < 4", "values": []}

        if method == "auto":
            norm = self.test_normality()
            method = "zscore" if norm.get("is_normal", False) else "iqr"

        if method == "iqr":
            q1, q3 = np.percentile(v, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            mask = (v < lower) | (v > upper)
        elif method == "zscore":
            z = np.abs(stats.zscore(v))
            mask = z > 3
        else:
            mask = np.zeros(n, dtype=bool)

        indices = np.where(mask)[0].tolist()
        return {
            "count": int(mask.sum()),
            "indices": indices,
            "method": method,
            "values": [round(float(v[i]), 6) for i in indices[:20]],
        }

    def error_bars(self, method: str = "ci95") -> dict:
        """Compute error bar values for plotting.

        Args:
            method: 'sd' (standard deviation), 'sem' (standard error),
                    'ci95' (95% confidence interval), 'iqr' (interquartile range)
        """
        v = self.values
        n = len(v)
        mean_val = float(np.mean(v))

        if method == "sd":
            std = float(np.std(v, ddof=1)) if n > 1 else 0
            return {"center": mean_val, "lower": mean_val - std, "upper": mean_val + std,
                    "error": std, "method": "Standard Deviation"}
        elif method == "sem":
            sem = float(np.std(v, ddof=1) / np.sqrt(n)) if n > 1 else 0
            return {"center": mean_val, "lower": mean_val - sem, "upper": mean_val + sem,
                    "error": sem, "method": "Standard Error of the Mean"}
        elif method == "ci95":
            sem = float(np.std(v, ddof=1) / np.sqrt(n)) if n > 1 else 0
            if n > 1:
                ci = stats.t.interval(0.95, df=n - 1, loc=mean_val, scale=sem)
            else:
                ci = (mean_val, mean_val)
            return {"center": mean_val, "lower": float(ci[0]), "upper": float(ci[1]),
                    "error": float(ci[1] - mean_val), "method": "95% Confidence Interval"}
        elif method == "iqr":
            q1, median_val, q3 = np.percentile(v, [25, 50, 75])
            return {"center": float(median_val), "lower": float(q1), "upper": float(q3),
                    "error": float(q3 - q1), "method": "Interquartile Range"}
        else:
            raise ValueError(f"Unknown method: {method}. Use 'sd', 'sem', 'ci95', or 'iqr'.")


# ============================================================================
# CorrelationAnalyzer - Smart Correlation Selection
# ============================================================================

class CorrelationAnalyzer:
    """Analyze correlations with automatic method selection."""

    def __init__(self, data: Optional[pd.DataFrame] = None,
                 x: Optional[str] = None, y: Optional[str] = None,
                 x_data: Optional[np.ndarray] = None, y_data: Optional[np.ndarray] = None):
        if data is not None and x is not None and y is not None:
            mask = data[[x, y]].dropna().index
            self.x = data.loc[mask, x].values.astype(float)
            self.y = data.loc[mask, y].values.astype(float)
            self.x_name = x
            self.y_name = y
        elif x_data is not None and y_data is not None:
            self.x = np.array(x_data, dtype=float)
            self.y = np.array(y_data, dtype=float)
            self.x_name = "x"
            self.y_name = "y"
        else:
            raise ValueError("Provide either (data, x, y) or (x_data, y_data)")

    def auto_analyze(self) -> dict:
        """Auto-select and compute the most appropriate correlation."""
        n = len(self.x)
        if n < 3:
            return {"error": "Insufficient data (n < 3)", "n": n}

        # Check normality of both variables
        norm_x = DescriptiveAnalyzer(self.x).test_normality()
        norm_y = DescriptiveAnalyzer(self.y).test_normality()
        both_normal = norm_x.get("is_normal", False) and norm_y.get("is_normal", False)

        # Check for ties (suggests ordinal data)
        x_unique_ratio = len(np.unique(self.x)) / n
        y_unique_ratio = len(np.unique(self.y)) / n
        many_ties = x_unique_ratio < 0.5 or y_unique_ratio < 0.5

        # Decision logic
        if many_ties:
            method = "kendall"
            reason = "Many tied values detected - Kendall tau-b handles ties better"
        elif both_normal:
            method = "pearson"
            reason = "Both variables normally distributed - Pearson is optimal"
        else:
            method = "spearman"
            reason = "Non-normal distribution detected - Spearman is robust"

        result = self.compute(method=method)
        result["reason"] = reason
        result["normality_x"] = norm_x
        result["normality_y"] = norm_y
        result["alternative_methods"] = self.compare_methods()
        return result

    def compute(self, method: str = "pearson") -> dict:
        """Compute correlation with CI and interpretation."""
        n = len(self.x)

        if method == "pearson":
            r, p = pearsonr(self.x, self.y)
        elif method == "spearman":
            r, p = spearmanr(self.x, self.y)
        elif method == "kendall":
            r, p = kendalltau(self.x, self.y)
        elif method == "point_biserial":
            r, p = pointbiserialr(self.x, self.y)
        else:
            raise ValueError(f"Unknown method: {method}")

        # Confidence interval via Fisher z-transform
        ci_lower, ci_upper = self._correlation_ci(r, n)

        # Interpretation
        abs_r = abs(r)
        if abs_r >= 0.9:
            strength = "very strong"
        elif abs_r >= 0.7:
            strength = "strong"
        elif abs_r >= 0.5:
            strength = "moderate"
        elif abs_r >= 0.3:
            strength = "weak"
        else:
            strength = "negligible"

        direction = "positive" if r > 0 else "negative"

        return {
            "method": method,
            "r": round(float(r), 6),
            "p_value": float(p),
            "ci_lower": round(ci_lower, 4),
            "ci_upper": round(ci_upper, 4),
            "n": n,
            "strength": strength,
            "direction": direction,
            "interpretation": f"{strength.capitalize()} {direction} correlation",
            "x_name": self.x_name,
            "y_name": self.y_name,
        }

    def compare_methods(self) -> list:
        """Compare all applicable correlation methods."""
        results = []
        for method in ["pearson", "spearman", "kendall"]:
            try:
                results.append(self.compute(method=method))
            except Exception as e:
                results.append({"method": method, "error": str(e)})
        return results

    def _correlation_ci(self, r: float, n: int) -> Tuple[float, float]:
        """Compute 95% CI for correlation via Fisher z-transform."""
        if n < 4 or abs(r) >= 1.0:
            return (float(r), float(r))
        try:
            z = np.arctanh(r)
            se = 1.0 / np.sqrt(n - 3)
            z_lower = z - 1.96 * se
            z_upper = z + 1.96 * se
            return (float(np.tanh(z_lower)), float(np.tanh(z_upper)))
        except Exception:
            return (float(r), float(r))

    @staticmethod
    def correlation_matrix(df: pd.DataFrame, columns: Optional[List[str]] = None,
                           method: str = "pearson", adjust_pvalues: bool = True) -> dict:
        """Compute correlation matrix with p-values and optional multiple comparison correction."""
        if columns is None:
            columns = df.select_dtypes(include=[np.number]).columns.tolist()

        n_cols = len(columns)
        r_matrix = np.zeros((n_cols, n_cols))
        p_matrix = np.zeros((n_cols, n_cols))

        for i in range(n_cols):
            for j in range(n_cols):
                if i == j:
                    r_matrix[i, j] = 1.0
                    p_matrix[i, j] = 0.0
                elif i < j:
                    x = df[columns[i]].dropna()
                    y = df[columns[j]].dropna()
                    common = x.index.intersection(y.index)
                    if len(common) < 3:
                        r_matrix[i, j] = r_matrix[j, i] = np.nan
                        p_matrix[i, j] = p_matrix[j, i] = np.nan
                        continue

                    if method == "pearson":
                        r, p = pearsonr(x[common], y[common])
                    elif method == "spearman":
                        r, p = spearmanr(x[common], y[common])
                    elif method == "kendall":
                        r, p = kendalltau(x[common], y[common])
                    else:
                        r, p = pearsonr(x[common], y[common])

                    r_matrix[i, j] = r_matrix[j, i] = r
                    p_matrix[i, j] = p_matrix[j, i] = p

        # Adjust p-values for multiple comparisons
        if adjust_pvalues:
            upper_tri = []
            for i in range(n_cols):
                for j in range(i + 1, n_cols):
                    if not np.isnan(p_matrix[i, j]):
                        upper_tri.append(p_matrix[i, j])

            if upper_tri:
                _, adjusted, _, _ = multipletests(upper_tri, method='holm')
                idx = 0
                adjusted_p_matrix = p_matrix.copy()
                for i in range(n_cols):
                    for j in range(i + 1, n_cols):
                        if not np.isnan(p_matrix[i, j]):
                            adjusted_p_matrix[i, j] = adjusted_p_matrix[j, i] = adjusted[idx]
                            idx += 1
                p_matrix = adjusted_p_matrix

        return {
            "columns": columns,
            "r_matrix": pd.DataFrame(r_matrix, index=columns, columns=columns).round(4).to_dict(),
            "p_matrix": pd.DataFrame(p_matrix, index=columns, columns=columns).round(6).to_dict(),
            "method": method,
            "adjusted": adjust_pvalues,
        }


# ============================================================================
# HypothesisTester - Tests with Effect Sizes
# ============================================================================

class HypothesisTester:
    """Perform hypothesis tests with automatic method selection and effect sizes."""

    def compare_two_groups(self, group_a, group_b, paired: bool = False,
                           alternative: str = "two-sided") -> dict:
        """Compare two groups with auto-selected test and effect size.

        Checks assumptions (normality, homoscedasticity) before selecting
        parametric vs non-parametric tests. Always reports effect size,
        confidence interval, and statistical power.
        """
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)
        a = a[~np.isnan(a)]
        b = b[~np.isnan(b)]

        assumptions = []

        if paired:
            if len(a) != len(b):
                return {"error": "Paired test requires equal-length groups"}
            diff = a - b
            norm_diff = DescriptiveAnalyzer(diff).test_normality()
            assumptions.append({
                "name": "Normality of differences",
                "met": norm_diff.get("is_normal", False),
                "details": f"{norm_diff['method']}: p={norm_diff.get('p_value', 'N/A')}"
            })

            if norm_diff.get("is_normal", False):
                stat, p = ttest_rel(a, b, alternative=alternative)
                test_name = "Paired t-test"
                d_std = np.std(diff, ddof=1)
                d = float(np.mean(diff) / d_std) if d_std > 0 else 0
                es_name = "Cohen's d_z"
            else:
                stat, p = wilcoxon(diff, alternative=alternative)
                test_name = "Wilcoxon signed-rank"
                n_pairs = len(diff)
                d = float(stat / (n_pairs * (n_pairs + 1) / 4))  # approximation
                es_name = "Matched-pairs rank-biserial r"
        else:
            norm_a = DescriptiveAnalyzer(a).test_normality()
            norm_b = DescriptiveAnalyzer(b).test_normality()
            both_normal = norm_a.get("is_normal", False) and norm_b.get("is_normal", False)

            assumptions.append({
                "name": "Normality (group A)",
                "met": norm_a.get("is_normal", False),
                "details": f"{norm_a['method']}: p={norm_a.get('p_value', 'N/A')}"
            })
            assumptions.append({
                "name": "Normality (group B)",
                "met": norm_b.get("is_normal", False),
                "details": f"{norm_b['method']}: p={norm_b.get('p_value', 'N/A')}"
            })

            if both_normal:
                lev_stat, lev_p = levene(a, b)
                equal_var = lev_p > 0.05
                assumptions.append({
                    "name": "Homoscedasticity (Levene's)",
                    "met": equal_var,
                    "details": f"F={lev_stat:.4f}, p={lev_p:.4f}"
                })

                if equal_var:
                    stat, p = ttest_ind(a, b, equal_var=True, alternative=alternative)
                    test_name = "Independent t-test"
                else:
                    stat, p = ttest_ind(a, b, equal_var=False, alternative=alternative)
                    test_name = "Welch's t-test"

                # Cohen's d with pooled SD
                na, nb = len(a), len(b)
                pooled_std = np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
                d = float((np.mean(a) - np.mean(b)) / pooled_std) if pooled_std > 0 else 0
                es_name = "Cohen's d"
            else:
                stat, p = mannwhitneyu(a, b, alternative=alternative)
                test_name = "Mann-Whitney U"
                n1, n2 = len(a), len(b)
                d = float(1 - 2 * stat / (n1 * n2))  # rank-biserial
                es_name = "Rank-biserial correlation"

        # Effect size interpretation
        abs_d = abs(d)
        if abs_d < 0.2:
            es_interp = "negligible"
        elif abs_d < 0.5:
            es_interp = "small"
        elif abs_d < 0.8:
            es_interp = "medium"
        else:
            es_interp = "large"

        # Statistical power (for t-test variants)
        power = None
        n_for_80 = None
        try:
            if "t-test" in test_name.lower() or "welch" in test_name.lower():
                power_analyzer = TTestIndPower()
                effect = abs_d if abs_d > 0.01 else 0.01
                power = float(power_analyzer.solve_power(
                    effect_size=effect,
                    nobs1=len(a), ratio=len(b) / len(a),
                    alpha=0.05, alternative=alternative
                ))
                n_for_80 = int(power_analyzer.solve_power(
                    effect_size=effect,
                    power=0.8, ratio=1.0,
                    alpha=0.05, alternative=alternative
                ))
        except Exception:
            pass

        # Bootstrap CI for mean difference
        boot = BootstrapCI(n_iterations=5000)
        try:
            es_ci = boot.difference(a, b, statistic_fn=np.mean)
            ci_lower = es_ci["ci_lower"]
            ci_upper = es_ci["ci_upper"]
        except Exception:
            ci_lower = ci_upper = None

        return {
            "test_name": test_name,
            "statistic": round(float(stat), 6),
            "p_value": float(p),
            "effect_size": round(d, 4),
            "effect_size_name": es_name,
            "effect_size_interpretation": es_interp,
            "ci_lower": round(ci_lower, 4) if ci_lower is not None else None,
            "ci_upper": round(ci_upper, 4) if ci_upper is not None else None,
            "n_a": len(a),
            "n_b": len(b),
            "mean_a": round(float(np.mean(a)), 6),
            "mean_b": round(float(np.mean(b)), 6),
            "assumptions_checked": assumptions,
            "power": round(power, 4) if power is not None else None,
            "sample_size_for_80pct_power": n_for_80,
        }

    def compare_multiple_groups(self, groups: List, group_labels: Optional[List[str]] = None) -> dict:
        """Compare 3+ groups with auto-selected test and post-hoc analysis."""
        clean_groups = []
        for g in groups:
            arr = np.array(g, dtype=float)
            clean_groups.append(arr[~np.isnan(arr)])

        if group_labels is None:
            group_labels = [f"Group_{i + 1}" for i in range(len(clean_groups))]

        # Check normality for all groups
        all_normal = True
        normality_results = []
        for i, g in enumerate(clean_groups):
            norm = DescriptiveAnalyzer(g).test_normality()
            normality_results.append(norm)
            if not norm.get("is_normal", False):
                all_normal = False

        if all_normal:
            lev_stat, lev_p = levene(*clean_groups)
            equal_var = lev_p > 0.05

            if equal_var:
                stat, p = f_oneway(*clean_groups)
                test_name = "One-way ANOVA"
            else:
                # Welch's ANOVA via pingouin
                df_data = []
                for i, g in enumerate(clean_groups):
                    for val in g:
                        df_data.append({"value": float(val), "group": group_labels[i]})
                df = pd.DataFrame(df_data)
                welch = pg.welch_anova(dv="value", between="group", data=df)
                stat = float(welch["F"].iloc[0])
                p = float(welch["p-unc"].iloc[0])
                test_name = "Welch's ANOVA"

            # Eta-squared
            grand_mean = np.mean(np.concatenate(clean_groups))
            ss_between = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in clean_groups)
            ss_total = sum(np.sum((g - grand_mean) ** 2) for g in clean_groups)
            es = float(ss_between / ss_total) if ss_total > 0 else 0
            es_name = "Eta-squared"
        else:
            stat, p = kruskal(*clean_groups)
            test_name = "Kruskal-Wallis H"
            n_total = sum(len(g) for g in clean_groups)
            k = len(clean_groups)
            es = float((stat - k + 1) / (n_total - k)) if (n_total - k) > 0 else 0
            es_name = "Epsilon-squared"

        # Post-hoc tests if significant
        post_hoc = None
        if p < 0.05:
            df_data = []
            for i, g in enumerate(clean_groups):
                for val in g:
                    df_data.append({"value": float(val), "group": group_labels[i]})
            df = pd.DataFrame(df_data)

            try:
                if all_normal:
                    ph = pg.pairwise_tukey(dv="value", between="group", data=df)
                else:
                    ph = pg.pairwise_tests(dv="value", between="group", data=df,
                                           parametric=False, padjust="holm")
                post_hoc = ph.to_dict(orient="records")
            except Exception as e:
                post_hoc = [{"error": str(e)}]

        return {
            "test_name": test_name,
            "statistic": round(float(stat), 6),
            "p_value": float(p),
            "effect_size": round(es, 4),
            "effect_size_name": es_name,
            "n_groups": len(clean_groups),
            "group_labels": group_labels,
            "group_sizes": [len(g) for g in clean_groups],
            "group_means": [round(float(np.mean(g)), 6) for g in clean_groups],
            "normality_results": normality_results,
            "post_hoc": post_hoc,
            "significant": p < 0.05,
        }

    def chi_squared(self, observed, expected=None) -> dict:
        """Chi-squared test for categorical data."""
        observed = np.array(observed)

        if observed.ndim == 2:
            stat, p, dof, exp = chi2_contingency(observed)
            n = observed.sum()
            k = min(observed.shape)
            cramers_v = float(np.sqrt(stat / (n * (k - 1)))) if n > 0 and k > 1 else 0
        else:
            if expected is None:
                expected = np.full_like(observed, observed.mean(), dtype=float)
            stat, p = stats.chisquare(observed, f_exp=expected)
            dof = len(observed) - 1
            exp = expected
            n = observed.sum()
            cramers_v = None

        return {
            "test_name": "Chi-squared",
            "statistic": round(float(stat), 6),
            "p_value": float(p),
            "dof": int(dof),
            "effect_size": round(cramers_v, 4) if cramers_v is not None else None,
            "effect_size_name": "Cramer's V" if cramers_v is not None else None,
        }

    def equivalence_test(self, group_a, group_b, equivalence_margin: float = 0.5) -> dict:
        """Two One-Sided Tests (TOST) for equivalence."""
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)

        diff = float(np.mean(a) - np.mean(b))
        na, nb = len(a), len(b)
        pooled_std = np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
        d = diff / pooled_std if pooled_std > 0 else 0

        # TOST: test if mean(a) > mean(b) - margin AND mean(a) < mean(b) + margin
        _, p1 = ttest_ind(a - (-equivalence_margin), b)
        _, p2 = ttest_ind(a - equivalence_margin, b)
        p_tost = max(p1, p2) / 2  # one-sided

        return {
            "test_name": "TOST equivalence",
            "mean_difference": round(diff, 6),
            "equivalence_margin": equivalence_margin,
            "p_value_tost": float(p_tost),
            "equivalent": p_tost < 0.05,
            "cohens_d": round(d, 4),
            "details": f"TOST p={p_tost:.4f}; margin=+/-{equivalence_margin}"
        }


# ============================================================================
# EffectSizeCalculator - Comprehensive Effect Sizes
# ============================================================================

class EffectSizeCalculator:
    """Calculate various effect sizes with confidence intervals."""

    def cohens_d(self, group_a, group_b, correction: Optional[str] = "hedges") -> dict:
        """Cohen's d with optional Hedges' g or Glass's delta correction."""
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)
        na, nb = len(a), len(b)

        mean_diff = float(np.mean(a) - np.mean(b))

        if correction == "glass":
            denom = float(np.std(b, ddof=1))
            name = "Glass's delta"
        else:
            denom = float(np.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2)))
            name = "Cohen's d"

        d = mean_diff / denom if denom > 0 else 0

        if correction == "hedges" and (na + nb) > 2:
            cf = 1 - 3 / (4 * (na + nb) - 9)
            d *= cf
            name = "Hedges' g"

        # Approximate CI for d
        se_d = np.sqrt((na + nb) / (na * nb) + d ** 2 / (2 * (na + nb)))
        ci_lower = d - 1.96 * se_d
        ci_upper = d + 1.96 * se_d

        abs_d = abs(d)
        if abs_d < 0.2:
            interp = "negligible"
        elif abs_d < 0.5:
            interp = "small"
        elif abs_d < 0.8:
            interp = "medium"
        else:
            interp = "large"

        return {
            "d": round(d, 4),
            "name": name,
            "ci_lower": round(float(ci_lower), 4),
            "ci_upper": round(float(ci_upper), 4),
            "interpretation": interp,
            "mean_diff": round(mean_diff, 6),
        }

    def cohens_d_paired(self, pre, post) -> dict:
        """Cohen's d for paired/repeated measures."""
        pre = np.array(pre, dtype=float)
        post = np.array(post, dtype=float)
        diff = post - pre
        diff_std = np.std(diff, ddof=1)
        d = float(np.mean(diff) / diff_std) if diff_std > 0 else 0

        se_d = np.sqrt(1 / len(diff) + d ** 2 / (2 * len(diff)))
        abs_d = abs(d)

        return {
            "d": round(d, 4),
            "name": "Cohen's d_z (paired)",
            "ci_lower": round(d - 1.96 * float(se_d), 4),
            "ci_upper": round(d + 1.96 * float(se_d), 4),
            "interpretation": "negligible" if abs_d < 0.2 else "small" if abs_d < 0.5 else "medium" if abs_d < 0.8 else "large",
            "mean_diff": round(float(np.mean(diff)), 6),
        }

    def odds_ratio(self, table_2x2) -> dict:
        """Odds ratio from 2x2 contingency table [[a,b],[c,d]]."""
        t = np.array(table_2x2, dtype=float)
        a, b, c, d = t[0, 0], t[0, 1], t[1, 0], t[1, 1]

        or_val = (a * d) / (b * c) if (b * c) > 0 else float('inf')
        log_or = np.log(or_val) if 0 < or_val < float('inf') else 0
        se_log_or = np.sqrt(1 / max(a, 0.5) + 1 / max(b, 0.5) + 1 / max(c, 0.5) + 1 / max(d, 0.5))

        return {
            "odds_ratio": round(float(or_val), 4),
            "log_odds_ratio": round(float(log_or), 4),
            "ci_lower": round(float(np.exp(log_or - 1.96 * se_log_or)), 4),
            "ci_upper": round(float(np.exp(log_or + 1.96 * se_log_or)), 4),
        }

    def risk_ratio(self, table_2x2) -> dict:
        """Risk ratio from 2x2 contingency table."""
        t = np.array(table_2x2, dtype=float)
        risk_exposed = t[0, 0] / (t[0, 0] + t[0, 1]) if (t[0, 0] + t[0, 1]) > 0 else 0
        risk_unexposed = t[1, 0] / (t[1, 0] + t[1, 1]) if (t[1, 0] + t[1, 1]) > 0 else 0
        rr = risk_exposed / risk_unexposed if risk_unexposed > 0 else float('inf')

        log_rr = np.log(rr) if 0 < rr < float('inf') else 0
        se_log_rr = 0
        if t[0, 0] > 0 and t[1, 0] > 0:
            se_log_rr = np.sqrt(
                1 / t[0, 0] - 1 / (t[0, 0] + t[0, 1]) + 1 / t[1, 0] - 1 / (t[1, 0] + t[1, 1])
            )

        return {
            "risk_ratio": round(float(rr), 4),
            "ci_lower": round(float(np.exp(log_rr - 1.96 * se_log_rr)), 4),
            "ci_upper": round(float(np.exp(log_rr + 1.96 * se_log_rr)), 4),
        }

    def number_needed_to_treat(self, table_2x2) -> dict:
        """NNT from 2x2 contingency table."""
        t = np.array(table_2x2, dtype=float)
        risk_exp = t[0, 0] / (t[0, 0] + t[0, 1]) if (t[0, 0] + t[0, 1]) > 0 else 0
        risk_unexp = t[1, 0] / (t[1, 0] + t[1, 1]) if (t[1, 0] + t[1, 1]) > 0 else 0
        ard = risk_exp - risk_unexp
        nnt = 1 / abs(ard) if ard != 0 else float('inf')

        return {
            "nnt": round(float(nnt), 1),
            "absolute_risk_difference": round(float(ard), 4),
        }

    def eta_squared(self, ss_between: float, ss_total: float) -> dict:
        """Eta-squared effect size for ANOVA."""
        es = ss_between / ss_total if ss_total > 0 else 0
        return {"eta_squared": round(float(es), 4), "interpretation": self._interpret_eta(es)}

    def omega_squared(self, ss_between: float, ss_within: float,
                      df_between: int, ms_within: float) -> dict:
        """Omega-squared (less biased than eta-squared)."""
        ss_total = ss_between + ss_within
        es = (ss_between - df_between * ms_within) / (ss_total + ms_within)
        return {"omega_squared": round(float(max(0, es)), 4), "interpretation": self._interpret_eta(max(0, es))}

    def r_squared(self, y_true, y_pred, n_predictors: int = 1) -> dict:
        """R-squared with adjusted R-squared."""
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        n = len(y_true)
        r2 = float(r2_score(y_true, y_pred))
        adj_r2 = 1 - (1 - r2) * (n - 1) / (n - n_predictors - 1) if n > n_predictors + 1 else r2

        return {"r_squared": round(r2, 4), "adjusted_r_squared": round(float(adj_r2), 4), "n": n}

    def cles(self, group_a, group_b) -> dict:
        """Common Language Effect Size (probability of superiority)."""
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)

        count = sum(
            1 if ai > bi else 0.5 if ai == bi else 0
            for ai in a for bi in b
        )
        total = len(a) * len(b)
        p_sup = count / total if total > 0 else 0.5

        return {
            "probability_of_superiority": round(float(p_sup), 4),
            "interpretation": f"{p_sup * 100:.1f}% chance a random value from A exceeds one from B"
        }

    @staticmethod
    def _interpret_eta(es: float) -> str:
        if es < 0.01:
            return "negligible"
        elif es < 0.06:
            return "small"
        elif es < 0.14:
            return "medium"
        else:
            return "large"


# ============================================================================
# BootstrapCI - Non-parametric Confidence Intervals
# ============================================================================

class BootstrapCI:
    """Bootstrap confidence intervals for any statistic."""

    def __init__(self, n_iterations: int = 10000, confidence_level: float = 0.95,
                 random_state: int = 42):
        self.n_iterations = n_iterations
        self.confidence_level = confidence_level
        self.rng = np.random.RandomState(random_state)

    def compute(self, data, statistic_fn: Callable = np.mean) -> dict:
        """Bootstrap CI for a single-sample statistic."""
        data = np.array(data, dtype=float)
        data = data[~np.isnan(data)]
        n = len(data)

        estimate = float(statistic_fn(data))

        boot_stats = np.array([
            statistic_fn(data[self.rng.randint(0, n, n)])
            for _ in range(self.n_iterations)
        ])

        alpha = 1 - self.confidence_level
        ci_lower = float(np.percentile(boot_stats, 100 * alpha / 2))
        ci_upper = float(np.percentile(boot_stats, 100 * (1 - alpha / 2)))
        se = float(np.std(boot_stats))

        return {
            "estimate": round(estimate, 6),
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
            "se": round(se, 6),
            "method": "Percentile bootstrap",
            "n_iterations": self.n_iterations,
            "confidence_level": self.confidence_level,
        }

    def difference(self, group_a, group_b, statistic_fn: Callable = np.mean) -> dict:
        """Bootstrap CI for difference between two groups."""
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)
        a = a[~np.isnan(a)]
        b = b[~np.isnan(b)]

        observed_diff = float(statistic_fn(a) - statistic_fn(b))

        boot_diffs = np.array([
            statistic_fn(a[self.rng.randint(0, len(a), len(a))]) -
            statistic_fn(b[self.rng.randint(0, len(b), len(b))])
            for _ in range(self.n_iterations)
        ])

        alpha = 1 - self.confidence_level
        ci_lower = float(np.percentile(boot_diffs, 100 * alpha / 2))
        ci_upper = float(np.percentile(boot_diffs, 100 * (1 - alpha / 2)))

        return {
            "estimate": round(observed_diff, 6),
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
            "se": round(float(np.std(boot_diffs)), 6),
            "method": "Percentile bootstrap (difference)",
            "n_iterations": self.n_iterations,
            "confidence_level": self.confidence_level,
        }

    def correlation(self, x, y, method: str = "pearson") -> dict:
        """Bootstrap CI for correlation coefficient."""
        x = np.array(x, dtype=float)
        y = np.array(y, dtype=float)
        mask = ~(np.isnan(x) | np.isnan(y))
        x, y = x[mask], y[mask]
        n = len(x)

        corr_fns = {
            "pearson": lambda a, b: pearsonr(a, b)[0],
            "spearman": lambda a, b: spearmanr(a, b)[0],
            "kendall": lambda a, b: kendalltau(a, b)[0],
        }
        corr_fn = corr_fns.get(method, corr_fns["pearson"])

        observed = float(corr_fn(x, y))

        boot_corrs = []
        for _ in range(self.n_iterations):
            idx = self.rng.randint(0, n, n)
            try:
                boot_corrs.append(corr_fn(x[idx], y[idx]))
            except Exception:
                pass

        boot_corrs = np.array(boot_corrs)
        alpha = 1 - self.confidence_level

        return {
            "estimate": round(observed, 6),
            "ci_lower": round(float(np.percentile(boot_corrs, 100 * alpha / 2)), 4),
            "ci_upper": round(float(np.percentile(boot_corrs, 100 * (1 - alpha / 2))), 4),
            "se": round(float(np.std(boot_corrs)), 6),
            "method": f"Bootstrap {method} correlation",
            "n_iterations": self.n_iterations,
        }


# ============================================================================
# BayesianAnalyzer - Judicious Bayesian Methods
# ============================================================================

class BayesianAnalyzer:
    """Bayesian statistical methods for when frequentist approaches are insufficient.

    Use judiciously: Bayesian methods are most valuable when:
    - Sample sizes are small and prior information is available
    - You need to quantify evidence FOR the null hypothesis
    - Frequentist tests give ambiguous results (p near 0.05)
    - You need probability statements about parameters
    """

    @staticmethod
    def _get_col(df, candidates):
        """Get value from DataFrame using first matching column name."""
        for c in candidates:
            if c in df.columns:
                return df[c].iloc[0]
        return None

    def bayesian_ttest(self, group_a, group_b, paired: bool = False,
                       rope: float = 0.1) -> dict:
        """Bayesian t-test using pingouin (JZS Bayes factor).

        Args:
            rope: Region of Practical Equivalence (in Cohen's d units)
        """
        a = np.array(group_a, dtype=float)
        b = np.array(group_b, dtype=float)

        result = pg.ttest(a, b, paired=paired)
        bf = float(result["BF10"].iloc[0])

        # Interpret Bayes factor (Jeffreys scale)
        if bf > 100:
            evidence = "extreme evidence for H1"
        elif bf > 30:
            evidence = "very strong evidence for H1"
        elif bf > 10:
            evidence = "strong evidence for H1"
        elif bf > 3:
            evidence = "moderate evidence for H1"
        elif bf > 1:
            evidence = "anecdotal evidence for H1"
        elif bf > 1 / 3:
            evidence = "anecdotal evidence (inconclusive)"
        elif bf > 1 / 10:
            evidence = "moderate evidence for H0"
        elif bf > 1 / 30:
            evidence = "strong evidence for H0"
        else:
            evidence = "very strong evidence for H0"

        p_val = self._get_col(result, ["p-val", "p_val", "pval"])
        cohens_d = self._get_col(result, ["cohen-d", "cohen_d", "cohend"])

        return {
            "bayes_factor_10": round(bf, 4),
            "bayes_factor_01": round(1 / bf, 4) if bf > 0 else float('inf'),
            "evidence": evidence,
            "interpretation": f"BF10={bf:.2f}: {evidence}",
            "t_statistic": round(float(result["T"].iloc[0]), 4),
            "p_value": float(p_val) if p_val is not None else None,
            "cohens_d": round(float(cohens_d), 4) if cohens_d is not None else None,
            "rope": rope,
            "method": "JZS Bayes factor (Rouder et al., 2009)",
        }

    def bayesian_correlation(self, x, y, method: str = "pearson") -> dict:
        """Bayesian correlation test."""
        x = np.array(x, dtype=float)
        y = np.array(y, dtype=float)

        result = pg.corr(x, y, method=method)

        bf = float(result["BF10"].iloc[0]) if "BF10" in result.columns else None
        ci = self._get_col(result, ["CI95%", "CI95"])
        p_val = self._get_col(result, ["p-val", "p_val", "pval"])

        ci_lower = float(ci[0]) if ci is not None else None
        ci_upper = float(ci[1]) if ci is not None else None

        return {
            "r": round(float(result["r"].iloc[0]), 4),
            "ci_lower": round(ci_lower, 4) if ci_lower is not None else None,
            "ci_upper": round(ci_upper, 4) if ci_upper is not None else None,
            "p_value": float(p_val) if p_val is not None else None,
            "bayes_factor": round(bf, 4) if bf is not None else None,
            "method": method,
            "n": int(result["n"].iloc[0]),
        }


# ============================================================================
# ModelEvaluator - ML/Regression Model Assessment
# ============================================================================

class ModelEvaluator:
    """Evaluate model performance with comprehensive metrics and diagnostics."""

    def evaluate_regression(self, y_true, y_pred, n_predictors: int = 1) -> dict:
        """Full regression evaluation with residual diagnostics."""
        y_true = np.array(y_true, dtype=float)
        y_pred = np.array(y_pred, dtype=float)
        n = len(y_true)

        residuals = y_true - y_pred

        r2 = float(r2_score(y_true, y_pred))
        adj_r2 = 1 - (1 - r2) * (n - 1) / (n - n_predictors - 1) if n > n_predictors + 1 else r2
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        mae = float(mean_absolute_error(y_true, y_pred))

        # MAPE (handle zeros)
        nonzero_mask = y_true != 0
        if nonzero_mask.sum() > 0:
            mape = float(np.mean(np.abs(residuals[nonzero_mask] / y_true[nonzero_mask])) * 100)
        else:
            mape = None

        # Residual diagnostics
        norm_test = DescriptiveAnalyzer(residuals).test_normality()

        # Heteroscedasticity (Breusch-Pagan)
        try:
            X = sm.add_constant(y_pred)
            bp_stat, bp_p, _, _ = het_breuschpagan(residuals, X)
            hetero = {
                "test": "Breusch-Pagan",
                "statistic": round(float(bp_stat), 4),
                "p_value": float(bp_p),
                "homoscedastic": bp_p > 0.05,
                "details": f"BP={bp_stat:.4f}, p={bp_p:.4f}"
            }
        except Exception:
            hetero = {"test": "Breusch-Pagan", "homoscedastic": None, "details": "Could not compute"}

        # Autocorrelation (Durbin-Watson)
        try:
            dw = float(durbin_watson(residuals))
            autocorr = {
                "test": "Durbin-Watson",
                "statistic": round(dw, 4),
                "independent": 1.5 < dw < 2.5,
                "details": f"DW={dw:.4f} ({'independent' if 1.5 < dw < 2.5 else 'autocorrelated'})"
            }
        except Exception:
            autocorr = {"test": "Durbin-Watson", "independent": None, "details": "Could not compute"}

        return {
            "n": n,
            "r_squared": round(r2, 4),
            "adjusted_r_squared": round(float(adj_r2), 4),
            "rmse": round(rmse, 4),
            "mae": round(mae, 4),
            "mape": round(mape, 2) if mape is not None else None,
            "max_error": round(float(max_error(y_true, y_pred)), 4),
            "explained_variance": round(float(explained_variance_score(y_true, y_pred)), 4),
            "residual_analysis": {
                "normality": {
                    "method": norm_test.get("method", ""),
                    "p_value": norm_test.get("p_value"),
                    "is_normal": norm_test.get("is_normal"),
                    "details": norm_test.get("interpretation", "")
                },
                "heteroscedasticity": hetero,
                "autocorrelation": autocorr,
            },
            "residual_stats": {
                "mean": round(float(np.mean(residuals)), 6),
                "std": round(float(np.std(residuals)), 4),
                "skew": round(float(stats.skew(residuals)), 4),
                "kurtosis": round(float(stats.kurtosis(residuals)), 4),
            }
        }

    def evaluate_classification(self, y_true, y_pred, y_prob=None,
                                labels=None, average="weighted") -> dict:
        """Full classification evaluation."""
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)

        n = len(y_true)
        unique_classes = np.unique(np.concatenate([y_true, y_pred]))
        n_classes = len(unique_classes)

        acc = float(accuracy_score(y_true, y_pred))

        # Wilson score CI for accuracy
        z = 1.96
        p_hat = acc
        denom = 1 + z ** 2 / n
        center = (p_hat + z ** 2 / (2 * n)) / denom
        spread = z * np.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * n)) / n) / denom

        result = {
            "n": n,
            "n_classes": n_classes,
            "accuracy": round(acc, 4),
            "accuracy_ci_lower": round(float(center - spread), 4),
            "accuracy_ci_upper": round(float(center + spread), 4),
            "precision": round(float(precision_score(y_true, y_pred, average=average, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true, y_pred, average=average, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true, y_pred, average=average, zero_division=0)), 4),
            "mcc": round(float(matthews_corrcoef(y_true, y_pred)), 4),
            "cohen_kappa": round(float(cohen_kappa_score(y_true, y_pred)), 4),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        }

        if y_prob is not None:
            y_prob = np.array(y_prob)
            try:
                if n_classes == 2:
                    y_prob_pos = y_prob[:, 1] if y_prob.ndim == 2 else y_prob
                    result["roc_auc"] = round(float(roc_auc_score(y_true, y_prob_pos)), 4)
                    result["pr_auc"] = round(float(average_precision_score(y_true, y_prob_pos)), 4)
                else:
                    result["roc_auc"] = round(float(roc_auc_score(y_true, y_prob, multi_class='ovr')), 4)
            except Exception as e:
                result["roc_auc_error"] = str(e)

        return result

    def cross_validate_arrays(self, y_true_folds: List, y_pred_folds: List,
                              task: str = "regression") -> dict:
        """Cross-validation summary from pre-computed fold predictions."""
        fold_metrics = []

        for y_t, y_p in zip(y_true_folds, y_pred_folds):
            y_t = np.array(y_t, dtype=float)
            y_p = np.array(y_p, dtype=float)
            if task == "regression":
                fold_metrics.append({
                    "r2": r2_score(y_t, y_p),
                    "rmse": np.sqrt(mean_squared_error(y_t, y_p)),
                    "mae": mean_absolute_error(y_t, y_p),
                })
            else:
                fold_metrics.append({
                    "accuracy": accuracy_score(y_t, y_p),
                    "f1": f1_score(y_t, y_p, average="weighted", zero_division=0),
                    "mcc": matthews_corrcoef(y_t, y_p),
                })

        df_metrics = pd.DataFrame(fold_metrics)
        summary = {}
        for col in df_metrics.columns:
            vals = df_metrics[col].values
            mean_val = float(np.mean(vals))
            std_val = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0
            sem_val = std_val / np.sqrt(len(vals)) if len(vals) > 0 else 0
            if len(vals) > 1 and sem_val > 0:
                ci = stats.t.interval(0.95, df=len(vals) - 1, loc=mean_val, scale=sem_val)
            else:
                ci = (mean_val, mean_val)
            summary[col] = {
                "mean": round(mean_val, 4),
                "std": round(std_val, 4),
                "ci_lower": round(float(ci[0]), 4),
                "ci_upper": round(float(ci[1]), 4),
                "values": [round(float(v), 4) for v in vals],
            }

        return {
            "n_folds": len(y_true_folds),
            "scores_by_metric": summary,
            "task": task,
        }


# ============================================================================
# ReportGenerator - HTML Validation Reports
# ============================================================================

class ReportGenerator:
    """Generate comprehensive HTML validation reports."""

    def __init__(self, state: Optional[ValidationState] = None,
                 css_path: str = "/input/discovery-report.css"):
        self.state = state
        self.sections = []
        self.css_path = css_path

    def add_summary(self):
        """Add executive summary from ValidationState."""
        if self.state is None:
            return
        s = self.state.summary()
        score = s["confidence_score"]
        label = s["confidence_label"]

        if score >= 90:
            css_class = "success"
        elif score >= 70:
            css_class = "warning"
        else:
            css_class = "error"

        failed_class = "error" if s["failed"] > 0 else "success"
        crit_class = "error" if len(s["critical_failures"]) > 0 else "success"

        html = f'''
        <div class="summary-box {css_class}">
            <div class="box-title">Validation Confidence: {label} ({score}/100)</div>
            <div class="progress-bar"><div class="fill" style="width: {score}%"></div></div>
            <div class="metric-grid">
                <div class="metric-card">
                    <div class="metric-value">{s["total_checks"]}</div>
                    <div class="metric-label">Total Checks</div>
                </div>
                <div class="metric-card success">
                    <div class="metric-value">{s["passed"]}</div>
                    <div class="metric-label">Passed</div>
                </div>
                <div class="metric-card {failed_class}">
                    <div class="metric-value">{s["failed"]}</div>
                    <div class="metric-label">Failed</div>
                </div>
                <div class="metric-card {crit_class}">
                    <div class="metric-value">{len(s["critical_failures"])}</div>
                    <div class="metric-label">Critical Failures</div>
                </div>
            </div>
        </div>
        '''

        # Checks by category
        if s["checks_by_category"]:
            html += '<h3>Checks by Category</h3><table><thead><tr>'
            html += '<th>Category</th><th>Passed</th><th>Failed</th><th>Total</th></tr></thead><tbody>'
            for cat, counts in s["checks_by_category"].items():
                f_class = "error" if counts["failed"] > 0 else ""
                html += f'<tr><td>{cat}</td><td class="success">{counts["passed"]}</td>'
                html += f'<td class="{f_class}">{counts["failed"]}</td>'
                html += f'<td>{counts["total"]}</td></tr>'
            html += '</tbody></table>'

        # Checks by pipeline step
        if s["checks_by_step"] and len(s["checks_by_step"]) > 1:
            html += '<h3>Checks by Pipeline Step</h3><table><thead><tr>'
            html += '<th>Step</th><th>Passed</th><th>Failed</th><th>Total</th></tr></thead><tbody>'
            for step, counts in s["checks_by_step"].items():
                f_class = "error" if counts["failed"] > 0 else ""
                html += f'<tr><td>{step}</td><td class="success">{counts["passed"]}</td>'
                html += f'<td class="{f_class}">{counts["failed"]}</td>'
                html += f'<td>{counts["total"]}</td></tr>'
            html += '</tbody></table>'

        # All checks detail (collapsible)
        html += '<details><summary>All Validation Checks (click to expand)</summary>'
        html += '<table><thead><tr>'
        html += '<th>#</th><th>Check</th><th>Category</th><th>Severity</th><th>Status</th><th>Details</th></tr></thead><tbody>'
        for c in s["all_checks"]:
            status_class = "success" if c["passed"] else "error"
            status_text = "PASS" if c["passed"] else "FAIL"
            sev_class = {"critical": "error", "warning": "warning", "info": "info"}.get(c["severity"], "neutral")
            html += f'<tr><td>{c["id"]}</td><td>{c["name"]}</td><td>{c["category"]}</td>'
            html += f'<td><span class="badge {sev_class}">{c["severity"]}</span></td>'
            html += f'<td><span class="badge {status_class}">{status_text}</span></td>'
            html += f'<td>{c["details"]}</td></tr>'
        html += '</tbody></table></details>'

        self.sections.append(("Executive Summary", html))

    def add_descriptive_table(self, results: Union[dict, List[dict]],
                              title: str = "Descriptive Statistics"):
        """Add descriptive statistics table."""
        if isinstance(results, dict):
            results = [results]

        html = '<table><thead><tr><th>Column</th><th>N</th><th>Mean</th><th>SD</th>'
        html += '<th>95% CI</th><th>Median</th><th>IQR</th><th>Skew</th><th>Normal?</th><th>Outliers</th></tr></thead><tbody>'

        for r in results:
            if "error" in r:
                html += f'<tr><td colspan="10">{r["error"]}</td></tr>'
                continue

            norm_badge = "success" if r.get("normality_test", {}).get("is_normal") else "warning"
            norm_text = "Yes" if r.get("normality_test", {}).get("is_normal") else "No"
            outlier_count = r.get("outliers", {}).get("count", 0)

            html += f'<tr><td>{r.get("column", "")}</td><td>{r["n"]}</td>'
            html += f'<td class="num">{r["mean"]:.4f}</td><td class="num">{r["std"]:.4f}</td>'
            html += f'<td class="num">[{r["ci_95_lower"]:.4f}, {r["ci_95_upper"]:.4f}]</td>'
            html += f'<td class="num">{r["median"]:.4f}</td><td class="num">{r["iqr"]:.4f}</td>'
            html += f'<td class="num">{r.get("skewness", "N/A")}</td>'
            html += f'<td><span class="badge {norm_badge}">{norm_text}</span></td>'
            html += f'<td>{outlier_count}</td></tr>'

        html += '</tbody></table>'
        self.sections.append((title, html))

    def add_correlation_section(self, results: Union[dict, List[dict]],
                                title: str = "Correlation Analysis"):
        """Add correlation results."""
        if isinstance(results, dict):
            results = [results]

        html = '<table><thead><tr><th>Method</th><th>r</th><th>95% CI</th>'
        html += '<th>p-value</th><th>Strength</th><th>N</th></tr></thead><tbody>'

        for r in results:
            if "error" in r:
                html += f'<tr><td colspan="6">{r.get("method", "")} - {r["error"]}</td></tr>'
                continue
            p_str = f'{r["p_value"]:.2e}' if r["p_value"] < 0.001 else f'{r["p_value"]:.4f}'
            sig = "success" if r["p_value"] < 0.05 else "warning"
            html += f'<tr><td>{r["method"]}</td><td class="num">{r["r"]:.4f}</td>'
            html += f'<td class="num">[{r["ci_lower"]:.4f}, {r["ci_upper"]:.4f}]</td>'
            html += f'<td class="num"><span class="badge {sig}">{p_str}</span></td>'
            html += f'<td>{r.get("strength", "")}</td><td>{r["n"]}</td></tr>'

        html += '</tbody></table>'
        self.sections.append((title, html))

    def add_hypothesis_section(self, results: Union[dict, List[dict]],
                               title: str = "Hypothesis Tests"):
        """Add hypothesis test results."""
        if isinstance(results, dict):
            results = [results]

        html = '<table><thead><tr><th>Test</th><th>Statistic</th><th>p-value</th>'
        html += '<th>Effect Size</th><th>Interpretation</th><th>Power</th></tr></thead><tbody>'

        for r in results:
            if "error" in r:
                html += f'<tr><td colspan="6">{r["error"]}</td></tr>'
                continue
            p_str = f'{r["p_value"]:.2e}' if r["p_value"] < 0.001 else f'{r["p_value"]:.4f}'
            sig = "success" if r["p_value"] < 0.05 else "neutral"
            power_str = f'{r["power"]:.2f}' if r.get("power") else "N/A"
            power_class = "success" if r.get("power") and r["power"] >= 0.8 else "warning"

            html += f'<tr><td>{r["test_name"]}</td><td class="num">{r["statistic"]:.4f}</td>'
            html += f'<td><span class="badge {sig}">{p_str}</span></td>'
            html += f'<td class="num">{r.get("effect_size_name", "")}: {r["effect_size"]:.3f}</td>'
            html += f'<td>{r.get("effect_size_interpretation", "")}</td>'
            html += f'<td><span class="badge {power_class}">{power_str}</span></td></tr>'

        html += '</tbody></table>'
        self.sections.append((title, html))

    def add_model_section(self, results: dict, title: str = "Model Evaluation"):
        """Add model evaluation results."""
        if "r_squared" in results:
            # Regression metrics
            html = '<div class="metric-grid">'
            for metric, label in [("r_squared", "R-squared"), ("adjusted_r_squared", "Adj R-squared"),
                                  ("rmse", "RMSE"), ("mae", "MAE")]:
                val = results.get(metric)
                if val is not None:
                    html += f'<div class="metric-card"><div class="metric-value">{val:.4f}</div>'
                    html += f'<div class="metric-label">{label}</div></div>'
            html += '</div>'

            # Residual diagnostics
            ra = results.get("residual_analysis", {})
            if ra:
                html += '<h4>Residual Diagnostics</h4><table><thead><tr>'
                html += '<th>Test</th><th>Result</th><th>Status</th></tr></thead><tbody>'
                for key, label in [("normality", "Normal residuals"),
                                   ("heteroscedasticity", "Homoscedastic"),
                                   ("autocorrelation", "Independent")]:
                    if key in ra:
                        detail = ra[key].get("details", str(ra[key]))
                        ok = ra[key].get("is_normal", ra[key].get("homoscedastic", ra[key].get("independent")))
                        badge = "success" if ok else "warning"
                        html += f'<tr><td>{label}</td><td>{detail}</td>'
                        html += f'<td><span class="badge {badge}">{"PASS" if ok else "CHECK"}</span></td></tr>'
                html += '</tbody></table>'
        else:
            # Classification metrics
            html = '<div class="metric-grid">'
            for metric, label in [("accuracy", "Accuracy"), ("f1", "F1"),
                                  ("mcc", "MCC"), ("roc_auc", "ROC AUC")]:
                val = results.get(metric)
                if val is not None:
                    html += f'<div class="metric-card"><div class="metric-value">{val:.4f}</div>'
                    html += f'<div class="metric-label">{label}</div></div>'
            html += '</div>'

        self.sections.append((title, html))

    def add_domain_evaluation(self, evaluations: dict, domain: str,
                              title: str = "Domain-Specific Evaluation"):
        """Add domain-specific threshold evaluations."""
        desc = DOMAIN_THRESHOLDS.get(domain, {}).get("description", domain)
        html = f'<p>Domain: <strong>{desc}</strong></p>'
        html += '<table><thead><tr><th>Metric</th><th>Value</th><th>Rating</th>'
        html += '<th>Good</th><th>Acceptable</th><th>Poor</th></tr></thead><tbody>'

        for metric_name, ev in evaluations.items():
            if ev.get("rating") == "unknown":
                continue
            rating_class = {"good": "success", "acceptable": "warning", "poor": "error"}.get(ev["rating"], "neutral")
            html += f'<tr><td>{metric_name}</td><td class="num">{ev["value"]:.4f}</td>'
            html += f'<td><span class="badge {rating_class}">{ev["rating"]}</span></td>'
            html += f'<td class="num">{ev.get("threshold_good", "")}</td>'
            html += f'<td class="num">{ev.get("threshold_acceptable", "")}</td>'
            html += f'<td class="num">{ev.get("threshold_poor", "")}</td></tr>'

        html += '</tbody></table>'
        self.sections.append((title, html))

    def add_custom_section(self, html_content: str, title: str = "Additional Analysis"):
        """Add custom HTML content as a section."""
        self.sections.append((title, html_content))

    def add_plotly_chart(self, fig_json: str, title: str = "Chart",
                         chart_id: Optional[str] = None):
        """Add a Plotly chart from JSON figure specification."""
        cid = chart_id or f"chart_{len(self.sections)}"
        html = f'<div class="chart-container"><div id="{cid}"></div></div>'
        html += f'<script>Plotly.newPlot("{cid}", {fig_json}, {{}}, {{responsive: true}});</script>'
        self.sections.append((title, html))

    def generate(self, title: str = "Statistical Validation Report",
                 subtitle: str = "", author: str = "statagent") -> str:
        """Generate complete HTML report."""
        try:
            with open(self.css_path) as f:
                css = f.read()
        except FileNotFoundError:
            css = ""

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>{css}</style></head>
<body><div class="discovery-report">
<div class="report-header">
    <h1>{title}</h1>
    <span class="subtitle">{subtitle}</span>
    <div class="meta">
        <span>Generated: {now}</span>
        <span>Agent: {author}</span>
    </div>
</div>
'''
        for section_title, section_html in self.sections:
            html += f'<div class="card"><div class="card-title">{section_title}</div>{section_html}</div>\n'

        html += '</div></body></html>'
        return html

    def save_json(self, path: str):
        """Save machine-readable validation results."""
        data = {
            "validation_state": self.state.summary() if self.state else None,
            "generated_at": datetime.utcnow().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Convenience function: quick_validate
# ============================================================================

def quick_validate(data: pd.DataFrame, target_col: str = None, pred_col: str = None,
                   group_col: str = None, domain: str = "general_ml",
                   workflow_name: str = "Quick Validation") -> dict:
    """One-call comprehensive validation for common scenarios.

    Args:
        data: DataFrame with results
        target_col: Column with true/experimental values
        pred_col: Column with predicted values
        group_col: Column with group labels (for comparison)
        domain: Domain for thresholds
        workflow_name: Name for the validation state

    Returns:
        Dict with state, descriptive, correlation, hypothesis, model results
    """
    state = ValidationState(workflow_name=workflow_name)
    results = {"state": state, "descriptive": {}, "correlation": None,
               "hypothesis": None, "model": None, "domain_evaluation": {}}

    # Descriptive stats for all numeric columns
    numeric_cols = data.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        analyzer = DescriptiveAnalyzer(data, column=col)
        desc = analyzer.describe()
        results["descriptive"][col] = desc

        n_total = len(data)
        n_missing = data[col].isnull().sum()
        state.add_check(
            name=f"Completeness: {col}",
            category="data_quality",
            passed=n_missing / n_total < 0.05 if n_total > 0 else True,
            details=f"{n_missing}/{n_total} missing ({n_missing / n_total * 100:.1f}%)" if n_total > 0 else "No data",
            severity="warning"
        )

        outlier_count = desc.get("outliers", {}).get("count", 0)
        state.add_check(
            name=f"Outliers: {col}",
            category="data_quality",
            passed=outlier_count / n_total < 0.05 if n_total > 0 else True,
            details=f"{outlier_count} outliers ({desc.get('outliers', {}).get('method', 'N/A')})",
            severity="info"
        )

    # Correlation analysis (predicted vs experimental)
    if target_col and pred_col and target_col in data.columns and pred_col in data.columns:
        corr = CorrelationAnalyzer(data, x=pred_col, y=target_col)
        corr_result = corr.auto_analyze()
        results["correlation"] = corr_result

        state.add_check(
            name=f"Correlation ({corr_result.get('method', 'auto')})",
            category="significance",
            passed=corr_result.get("p_value", 1) < 0.05 and abs(corr_result.get("r", 0)) > 0.5,
            details=f"r={corr_result.get('r', 'N/A')}, p={corr_result.get('p_value', 'N/A')}",
            severity="critical"
        )

        # Model evaluation
        valid = data[[target_col, pred_col]].dropna()
        if len(valid) > 2:
            evaluator = ModelEvaluator()
            model_result = evaluator.evaluate_regression(
                valid[target_col].values, valid[pred_col].values
            )
            results["model"] = model_result

            state.add_check(
                name="Model R-squared",
                category="model_quality",
                passed=model_result["r_squared"] > 0.5,
                details=f"R2={model_result['r_squared']:.3f}, RMSE={model_result['rmse']:.3f}",
                severity="critical"
            )

            # Domain-specific evaluation
            domain_eval = evaluate_metric(model_result["r_squared"], "r_squared", domain)
            results["domain_evaluation"]["r_squared"] = domain_eval
            state.add_check(
                name=f"Domain threshold: R2 ({domain})",
                category="domain_specific",
                passed=domain_eval["rating"] in ["good", "acceptable"],
                details=f"R2={model_result['r_squared']:.3f} rated '{domain_eval['rating']}'",
                severity="warning"
            )

    # Group comparison
    if group_col and target_col and group_col in data.columns and target_col in data.columns:
        groups_dict = data.groupby(group_col)[target_col].apply(lambda x: x.dropna().tolist()).to_dict()
        group_arrays = [v for v in groups_dict.values() if len(v) > 1]
        group_labels = [str(k) for k, v in groups_dict.items() if len(v) > 1]

        if len(group_arrays) == 2:
            tester = HypothesisTester()
            hyp_result = tester.compare_two_groups(group_arrays[0], group_arrays[1])
            results["hypothesis"] = hyp_result
            state.add_check(
                name=f"Group difference ({hyp_result.get('test_name', '')})",
                category="significance",
                passed=True,
                details=f"p={hyp_result.get('p_value', 'N/A')}, "
                        f"{hyp_result.get('effect_size_name', '')}"
                        f"={hyp_result.get('effect_size', 'N/A')}",
                severity="info"
            )
        elif len(group_arrays) > 2:
            tester = HypothesisTester()
            hyp_result = tester.compare_multiple_groups(group_arrays, group_labels=group_labels)
            results["hypothesis"] = hyp_result

    return results
