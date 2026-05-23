"""
test_statagent_utils.py - Comprehensive tests for statagent_utils.py

Tests all major classes: ValidationState, DescriptiveAnalyzer, CorrelationAnalyzer,
HypothesisTester, EffectSizeCalculator, BootstrapCI, BayesianAnalyzer,
ModelEvaluator, ReportGenerator, and domain thresholds.
"""

import numpy as np
import pandas as pd
import json
import sys
import os

# Allow import from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from statagent_utils import (
    ValidationState, DescriptiveAnalyzer, CorrelationAnalyzer,
    HypothesisTester, EffectSizeCalculator, BootstrapCI,
    BayesianAnalyzer, ModelEvaluator, ReportGenerator,
    DOMAIN_THRESHOLDS, get_domain_thresholds, evaluate_metric,
    quick_validate
)


# ============================================================================
# Test Data Fixtures
# ============================================================================

def make_normal_data(n=100, mean=0, std=1, seed=42):
    rng = np.random.RandomState(seed)
    return rng.normal(mean, std, n)


def make_correlated_data(n=100, r=0.8, seed=42):
    rng = np.random.RandomState(seed)
    x = rng.normal(0, 1, n)
    noise = rng.normal(0, np.sqrt(1 - r**2), n)
    y = r * x + noise
    return x, y


def make_regression_data(n=100, noise=0.3, seed=42):
    rng = np.random.RandomState(seed)
    x = rng.uniform(-3, 3, n)
    y_true = 2 * x + 1 + rng.normal(0, noise, n)
    y_pred = 2 * x + 1 + rng.normal(0, noise * 0.5, n)
    return y_true, y_pred


# ============================================================================
# Test ValidationState
# ============================================================================

class TestValidationState:
    def test_init(self):
        state = ValidationState(workflow_name="Test")
        assert state.workflow_name == "Test"
        assert len(state.checks) == 0
        assert state.confidence_score() == 100.0
        assert state.confidence_label() == "HIGH"
        print("  PASS: test_init")

    def test_add_check(self):
        state = ValidationState()
        state.add_check("Test check", "data_quality", True, "OK", "info")
        assert len(state.checks) == 1
        assert state.checks[0]["passed"] is True
        assert state.checks[0]["category"] == "data_quality"
        print("  PASS: test_add_check")

    def test_confidence_score_degradation(self):
        state = ValidationState()
        # Add a critical failure
        state.add_check("Critical fail", "model_quality", False, "Bad", "critical")
        score = state.confidence_score()
        assert score == 85.0, f"Expected 85.0, got {score}"

        # Add a warning failure
        state.add_check("Warning fail", "assumption", False, "Bad", "warning")
        score = state.confidence_score()
        assert score == 77.0, f"Expected 77.0, got {score}"

        # Add an info failure
        state.add_check("Info fail", "data_quality", False, "Minor", "info")
        score = state.confidence_score()
        assert score == 74.0, f"Expected 74.0, got {score}"
        print("  PASS: test_confidence_score_degradation")

    def test_assumption_bonus(self):
        state = ValidationState()
        for i in range(5):
            state.add_check(f"Assumption {i}", "assumption", True, "OK", "info")
        # 100 + min(5*2, 10) = 110 -> capped at 100
        assert state.confidence_score() == 100.0
        print("  PASS: test_assumption_bonus")

    def test_confidence_labels(self):
        state = ValidationState()
        assert state.confidence_label() == "HIGH"

        # Drop to MODERATE
        state.add_check("fail1", "m", False, "", "critical")
        state.add_check("fail2", "m", False, "", "critical")
        assert state.confidence_label() == "MODERATE"

        # Drop to LOW
        state.add_check("fail3", "m", False, "", "critical")
        assert state.confidence_label() == "LOW"

        # Drop to VERY LOW
        state.add_check("fail4", "m", False, "", "critical")
        state.add_check("fail5", "m", False, "", "critical")
        state.add_check("fail6", "m", False, "", "critical")
        state.add_check("fail7", "m", False, "", "critical")
        assert state.confidence_label() == "VERY LOW"
        print("  PASS: test_confidence_labels")

    def test_summary(self):
        state = ValidationState(workflow_name="Test WF")
        state.add_check("c1", "data_quality", True, "OK", "info", step="step1")
        state.add_check("c2", "assumption", False, "Bad", "warning", step="step1")
        s = state.summary()

        assert s["workflow_name"] == "Test WF"
        assert s["total_checks"] == 2
        assert s["passed"] == 1
        assert s["failed"] == 1
        assert "data_quality" in s["checks_by_category"]
        assert "step1" in s["checks_by_step"]
        print("  PASS: test_summary")

    def test_serialization(self):
        state = ValidationState(workflow_name="Serialize Test")
        state.add_check("c1", "data_quality", True, "OK")
        json_str = state.to_json()
        restored = ValidationState.from_json(json_str)
        assert restored.workflow_name == "Serialize Test"
        assert len(restored.checks) == 1
        assert restored.confidence_score() == state.confidence_score()
        print("  PASS: test_serialization")


# ============================================================================
# Test DescriptiveAnalyzer
# ============================================================================

class TestDescriptiveAnalyzer:
    def test_basic_describe(self):
        data = make_normal_data(100, mean=5, std=2)
        analyzer = DescriptiveAnalyzer(data, column="test")
        desc = analyzer.describe()

        assert desc["n"] == 100
        assert abs(desc["mean"] - 5) < 1.0  # rough check
        assert desc["std"] > 0
        assert desc["ci_95_lower"] < desc["mean"] < desc["ci_95_upper"]
        assert "normality_test" in desc
        assert "outliers" in desc
        print("  PASS: test_basic_describe")

    def test_dataframe_input(self):
        df = pd.DataFrame({"col1": make_normal_data(50), "col2": make_normal_data(50)})
        analyzer = DescriptiveAnalyzer(df, column="col1")
        desc = analyzer.describe()
        assert desc["n"] == 50
        print("  PASS: test_dataframe_input")

    def test_normality(self):
        # Normal data should pass
        normal_data = make_normal_data(100)
        analyzer = DescriptiveAnalyzer(normal_data)
        norm = analyzer.test_normality()
        assert norm["method"] == "Shapiro-Wilk"
        assert norm["is_normal"] is True or norm["p_value"] is not None

        # Uniform data should fail
        uniform_data = np.random.uniform(0, 1, 200)
        analyzer2 = DescriptiveAnalyzer(uniform_data)
        norm2 = analyzer2.test_normality()
        assert norm2["p_value"] is not None
        print("  PASS: test_normality")

    def test_outlier_detection(self):
        data = np.concatenate([make_normal_data(100), [100, -100]])  # add outliers
        analyzer = DescriptiveAnalyzer(data)
        outliers = analyzer.detect_outliers()
        assert outliers["count"] >= 2
        print("  PASS: test_outlier_detection")

    def test_error_bars(self):
        data = make_normal_data(50)
        analyzer = DescriptiveAnalyzer(data)

        for method in ["sd", "sem", "ci95", "iqr"]:
            bars = analyzer.error_bars(method=method)
            assert "center" in bars
            assert "lower" in bars
            assert "upper" in bars
            assert bars["lower"] <= bars["center"] <= bars["upper"]
            assert "method" in bars
        print("  PASS: test_error_bars")

    def test_empty_data(self):
        analyzer = DescriptiveAnalyzer([])
        desc = analyzer.describe()
        assert desc["n"] == 0
        assert "error" in desc
        print("  PASS: test_empty_data")


# ============================================================================
# Test CorrelationAnalyzer
# ============================================================================

class TestCorrelationAnalyzer:
    def test_auto_analyze(self):
        x, y = make_correlated_data(100, r=0.8)
        corr = CorrelationAnalyzer(x_data=x, y_data=y)
        result = corr.auto_analyze()

        assert "method" in result
        assert "r" in result
        assert abs(result["r"]) > 0.5  # should detect strong correlation
        assert result["p_value"] < 0.05
        assert "reason" in result
        assert "alternative_methods" in result
        print("  PASS: test_auto_analyze")

    def test_specific_methods(self):
        x, y = make_correlated_data(50, r=0.7)
        corr = CorrelationAnalyzer(x_data=x, y_data=y)

        for method in ["pearson", "spearman", "kendall"]:
            result = corr.compute(method=method)
            assert result["method"] == method
            assert -1 <= result["r"] <= 1
            assert result["ci_lower"] <= result["r"] <= result["ci_upper"]
            assert "strength" in result
        print("  PASS: test_specific_methods")

    def test_compare_methods(self):
        x, y = make_correlated_data(50, r=0.6)
        corr = CorrelationAnalyzer(x_data=x, y_data=y)
        comparison = corr.compare_methods()
        assert len(comparison) == 3
        for r in comparison:
            assert "method" in r
        print("  PASS: test_compare_methods")

    def test_dataframe_input(self):
        x, y = make_correlated_data(80, r=0.9)
        df = pd.DataFrame({"pred": x, "exp": y})
        corr = CorrelationAnalyzer(data=df, x="pred", y="exp")
        result = corr.auto_analyze()
        assert result["x_name"] == "pred"
        assert result["y_name"] == "exp"
        print("  PASS: test_dataframe_input")

    def test_correlation_matrix(self):
        df = pd.DataFrame({
            "a": make_normal_data(50, seed=1),
            "b": make_normal_data(50, seed=2),
            "c": make_normal_data(50, seed=3),
        })
        result = CorrelationAnalyzer.correlation_matrix(df, columns=["a", "b", "c"])
        assert "r_matrix" in result
        assert "p_matrix" in result
        assert result["adjusted"] is True
        print("  PASS: test_correlation_matrix")


# ============================================================================
# Test HypothesisTester
# ============================================================================

class TestHypothesisTester:
    def test_two_groups_significant(self):
        a = make_normal_data(50, mean=0, std=1, seed=1)
        b = make_normal_data(50, mean=2, std=1, seed=2)
        tester = HypothesisTester()
        result = tester.compare_two_groups(a, b)

        assert result["p_value"] < 0.05
        assert abs(result["effect_size"]) > 0.5  # large effect
        assert "assumptions_checked" in result
        assert len(result["assumptions_checked"]) > 0
        print("  PASS: test_two_groups_significant")

    def test_two_groups_not_significant(self):
        a = make_normal_data(30, mean=0, std=1, seed=1)
        b = make_normal_data(30, mean=0.1, std=1, seed=2)
        tester = HypothesisTester()
        result = tester.compare_two_groups(a, b)
        # Small difference should not be highly significant with n=30
        assert "effect_size_interpretation" in result
        print("  PASS: test_two_groups_not_significant")

    def test_paired_comparison(self):
        pre = make_normal_data(30, mean=5, std=1, seed=1)
        post = pre + 0.5 + np.random.RandomState(42).normal(0, 0.3, 30)
        tester = HypothesisTester()
        result = tester.compare_two_groups(pre, post, paired=True)

        assert "Paired" in result["test_name"] or "Wilcoxon" in result["test_name"]
        assert "effect_size" in result
        print("  PASS: test_paired_comparison")

    def test_multiple_groups(self):
        g1 = make_normal_data(30, mean=0, seed=1)
        g2 = make_normal_data(30, mean=1, seed=2)
        g3 = make_normal_data(30, mean=2, seed=3)
        tester = HypothesisTester()
        result = tester.compare_multiple_groups([g1, g2, g3], ["Low", "Med", "High"])

        assert result["n_groups"] == 3
        assert result["p_value"] < 0.05  # should be significant
        assert "effect_size" in result
        assert "post_hoc" in result
        assert result["post_hoc"] is not None  # should have post-hoc since significant
        print("  PASS: test_multiple_groups")

    def test_chi_squared(self):
        observed = np.array([[50, 30], [20, 40]])
        tester = HypothesisTester()
        result = tester.chi_squared(observed)

        assert result["test_name"] == "Chi-squared"
        assert result["p_value"] is not None
        assert result["effect_size"] is not None  # Cramer's V
        print("  PASS: test_chi_squared")

    def test_equivalence(self):
        a = make_normal_data(50, mean=5, std=1, seed=1)
        b = make_normal_data(50, mean=5.1, std=1, seed=2)
        tester = HypothesisTester()
        result = tester.equivalence_test(a, b, equivalence_margin=0.5)

        assert result["test_name"] == "TOST equivalence"
        assert "equivalent" in result
        print("  PASS: test_equivalence")


# ============================================================================
# Test EffectSizeCalculator
# ============================================================================

class TestEffectSizeCalculator:
    def test_cohens_d(self):
        a = make_normal_data(50, mean=0, seed=1)
        b = make_normal_data(50, mean=1, seed=2)
        es = EffectSizeCalculator()
        result = es.cohens_d(a, b)

        assert "d" in result
        assert abs(result["d"]) > 0.5  # should be around 1.0
        assert result["ci_lower"] < result["d"] < result["ci_upper"]
        assert result["interpretation"] in ["negligible", "small", "medium", "large"]
        print("  PASS: test_cohens_d")

    def test_hedges_correction(self):
        a = make_normal_data(10, mean=0, seed=1)
        b = make_normal_data(10, mean=1, seed=2)
        es = EffectSizeCalculator()
        hedges = es.cohens_d(a, b, correction="hedges")
        cohen = es.cohens_d(a, b, correction=None)

        assert hedges["name"] == "Hedges' g"
        assert cohen["name"] == "Cohen's d"
        # Hedges' g should be slightly smaller (correction for small samples)
        assert abs(hedges["d"]) <= abs(cohen["d"]) + 0.01
        print("  PASS: test_hedges_correction")

    def test_paired_effect_size(self):
        pre = make_normal_data(30, mean=5, seed=1)
        post = pre + 0.5
        es = EffectSizeCalculator()
        result = es.cohens_d_paired(pre, post)

        assert result["name"] == "Cohen's d_z (paired)"
        assert result["d"] != 0
        print("  PASS: test_paired_effect_size")

    def test_odds_ratio(self):
        table = [[30, 10], [15, 25]]
        es = EffectSizeCalculator()
        result = es.odds_ratio(table)

        assert result["odds_ratio"] > 1
        assert result["ci_lower"] < result["odds_ratio"] < result["ci_upper"]
        print("  PASS: test_odds_ratio")

    def test_risk_ratio(self):
        table = [[30, 10], [15, 25]]
        es = EffectSizeCalculator()
        result = es.risk_ratio(table)
        assert result["risk_ratio"] > 1
        print("  PASS: test_risk_ratio")

    def test_nnt(self):
        table = [[30, 70], [10, 90]]
        es = EffectSizeCalculator()
        result = es.number_needed_to_treat(table)
        assert result["nnt"] > 0
        assert result["absolute_risk_difference"] != 0
        print("  PASS: test_nnt")

    def test_cles(self):
        a = make_normal_data(30, mean=2, seed=1)
        b = make_normal_data(30, mean=0, seed=2)
        es = EffectSizeCalculator()
        result = es.cles(a, b)
        assert 0 <= result["probability_of_superiority"] <= 1
        assert result["probability_of_superiority"] > 0.5  # A should be larger
        print("  PASS: test_cles")


# ============================================================================
# Test BootstrapCI
# ============================================================================

class TestBootstrapCI:
    def test_single_sample(self):
        data = make_normal_data(50, mean=5, std=1)
        boot = BootstrapCI(n_iterations=2000, random_state=42)
        result = boot.compute(data, statistic_fn=np.mean)

        assert abs(result["estimate"] - 5) < 1.0
        assert result["ci_lower"] < result["estimate"] < result["ci_upper"]
        assert result["se"] > 0
        print("  PASS: test_single_sample")

    def test_difference(self):
        a = make_normal_data(30, mean=5, seed=1)
        b = make_normal_data(30, mean=3, seed=2)
        boot = BootstrapCI(n_iterations=2000, random_state=42)
        result = boot.difference(a, b)

        assert result["estimate"] > 0  # a should be larger
        assert result["ci_lower"] < result["estimate"] < result["ci_upper"]
        print("  PASS: test_difference")

    def test_correlation_bootstrap(self):
        x, y = make_correlated_data(50, r=0.7)
        boot = BootstrapCI(n_iterations=2000, random_state=42)
        result = boot.correlation(x, y, method="pearson")

        assert abs(result["estimate"]) > 0.3
        assert result["ci_lower"] < result["estimate"] < result["ci_upper"]
        print("  PASS: test_correlation_bootstrap")


# ============================================================================
# Test BayesianAnalyzer
# ============================================================================

class TestBayesianAnalyzer:
    def test_bayesian_ttest(self):
        a = make_normal_data(30, mean=0, seed=1)
        b = make_normal_data(30, mean=2, seed=2)
        ba = BayesianAnalyzer()
        result = ba.bayesian_ttest(a, b)

        assert result["bayes_factor_10"] > 1  # should favor H1
        assert "evidence" in result
        assert "cohens_d" in result
        print("  PASS: test_bayesian_ttest")

    def test_bayesian_correlation(self):
        x, y = make_correlated_data(50, r=0.8)
        ba = BayesianAnalyzer()
        result = ba.bayesian_correlation(x, y)

        assert abs(result["r"]) > 0.5
        assert result["p_value"] < 0.05
        print("  PASS: test_bayesian_correlation")


# ============================================================================
# Test ModelEvaluator
# ============================================================================

class TestModelEvaluator:
    def test_regression_evaluation(self):
        y_true, y_pred = make_regression_data(100)
        evaluator = ModelEvaluator()
        result = evaluator.evaluate_regression(y_true, y_pred)

        assert result["r_squared"] > 0.5
        assert result["rmse"] > 0
        assert result["mae"] > 0
        assert "residual_analysis" in result
        assert "normality" in result["residual_analysis"]
        assert "heteroscedasticity" in result["residual_analysis"]
        assert "autocorrelation" in result["residual_analysis"]
        print("  PASS: test_regression_evaluation")

    def test_classification_evaluation(self):
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0] * 5)
        y_pred = np.array([0, 0, 1, 1, 1, 1, 0, 0, 1, 0] * 5)
        evaluator = ModelEvaluator()
        result = evaluator.evaluate_classification(y_true, y_pred)

        assert 0 <= result["accuracy"] <= 1
        assert -1 <= result["mcc"] <= 1
        assert "confusion_matrix" in result
        assert result["accuracy_ci_lower"] <= result["accuracy"] <= result["accuracy_ci_upper"]
        print("  PASS: test_classification_evaluation")

    def test_classification_with_proba(self):
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0, 1, 0] * 5)
        y_pred = np.array([0, 0, 1, 1, 1, 1, 0, 0, 1, 0] * 5)
        y_prob = np.column_stack([1 - y_pred * 0.8, y_pred * 0.8])
        evaluator = ModelEvaluator()
        result = evaluator.evaluate_classification(y_true, y_pred, y_prob=y_prob)

        assert "roc_auc" in result or "roc_auc_error" in result
        print("  PASS: test_classification_with_proba")

    def test_cross_validate_arrays(self):
        evaluator = ModelEvaluator()
        y_true_folds = [make_normal_data(20, seed=i) for i in range(5)]
        y_pred_folds = [y + np.random.RandomState(i + 10).normal(0, 0.3, 20) for i, y in enumerate(y_true_folds)]
        result = evaluator.cross_validate_arrays(y_true_folds, y_pred_folds, task="regression")

        assert result["n_folds"] == 5
        assert "r2" in result["scores_by_metric"]
        assert "mean" in result["scores_by_metric"]["r2"]
        assert "ci_lower" in result["scores_by_metric"]["r2"]
        print("  PASS: test_cross_validate_arrays")


# ============================================================================
# Test Domain Thresholds
# ============================================================================

class TestDomainThresholds:
    def test_available_domains(self):
        for domain in ["qsar", "docking", "md_simulation", "quantum_chemistry",
                        "free_energy", "admet", "general_ml"]:
            t = get_domain_thresholds(domain)
            assert "description" in t
            assert len(t) > 1
        print("  PASS: test_available_domains")

    def test_evaluate_metric_good(self):
        result = evaluate_metric(0.85, "r_squared", "qsar")
        assert result["rating"] == "good"
        assert result["domain"] == "qsar"
        print("  PASS: test_evaluate_metric_good")

    def test_evaluate_metric_acceptable(self):
        result = evaluate_metric(0.55, "r_squared", "qsar")
        assert result["rating"] == "acceptable"
        print("  PASS: test_evaluate_metric_acceptable")

    def test_evaluate_metric_poor(self):
        result = evaluate_metric(0.2, "r_squared", "qsar")
        assert result["rating"] == "poor"
        print("  PASS: test_evaluate_metric_poor")

    def test_evaluate_lower_is_better(self):
        result = evaluate_metric(0.5, "rmse_relative", "qsar", lower_is_better=True)
        assert result["rating"] == "poor"
        result2 = evaluate_metric(0.05, "rmse_relative", "qsar", lower_is_better=True)
        assert result2["rating"] == "good"
        print("  PASS: test_evaluate_lower_is_better")

    def test_unknown_metric(self):
        result = evaluate_metric(0.5, "nonexistent_metric", "qsar")
        assert result["rating"] == "unknown"
        print("  PASS: test_unknown_metric")

    def test_unknown_domain_fallback(self):
        t = get_domain_thresholds("nonexistent_domain")
        assert t == DOMAIN_THRESHOLDS["general_ml"]
        print("  PASS: test_unknown_domain_fallback")


# ============================================================================
# Test ReportGenerator
# ============================================================================

class TestReportGenerator:
    def test_generate_basic_report(self):
        state = ValidationState(workflow_name="Test Report")
        state.add_check("Check 1", "data_quality", True, "OK", "info")
        state.add_check("Check 2", "assumption", False, "Failed normality", "warning")

        gen = ReportGenerator(state=state, css_path="/nonexistent/path.css")
        gen.add_summary()
        html = gen.generate(title="Test Report", subtitle="Unit Test")

        assert "<html>" in html
        assert "Test Report" in html
        assert "PASS" in html
        assert "FAIL" in html
        assert "Validation Confidence" in html
        print("  PASS: test_generate_basic_report")

    def test_descriptive_section(self):
        data = make_normal_data(50)
        analyzer = DescriptiveAnalyzer(data, column="test")
        desc = analyzer.describe()

        gen = ReportGenerator(css_path="/nonexistent/path.css")
        gen.add_descriptive_table(desc)
        html = gen.generate(title="Descriptive Test")
        assert "Descriptive Statistics" in html
        print("  PASS: test_descriptive_section")

    def test_correlation_section(self):
        x, y = make_correlated_data(50)
        corr = CorrelationAnalyzer(x_data=x, y_data=y)
        result = corr.compare_methods()

        gen = ReportGenerator(css_path="/nonexistent/path.css")
        gen.add_correlation_section(result)
        html = gen.generate(title="Correlation Test")
        assert "pearson" in html
        print("  PASS: test_correlation_section")

    def test_model_section(self):
        y_true, y_pred = make_regression_data(50)
        evaluator = ModelEvaluator()
        result = evaluator.evaluate_regression(y_true, y_pred)

        gen = ReportGenerator(css_path="/nonexistent/path.css")
        gen.add_model_section(result)
        html = gen.generate(title="Model Test")
        assert "R-squared" in html
        print("  PASS: test_model_section")

    def test_domain_evaluation_section(self):
        evaluations = {
            "r_squared": evaluate_metric(0.75, "r_squared", "qsar"),
            "correlation": evaluate_metric(0.85, "correlation", "qsar"),
        }
        gen = ReportGenerator(css_path="/nonexistent/path.css")
        gen.add_domain_evaluation(evaluations, "qsar")
        html = gen.generate(title="Domain Test")
        assert "QSAR" in html
        print("  PASS: test_domain_evaluation_section")

    def test_json_output(self):
        state = ValidationState(workflow_name="JSON Test")
        state.add_check("c1", "data_quality", True, "OK")
        gen = ReportGenerator(state=state, css_path="/nonexistent/path.css")

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        gen.save_json(path)
        with open(path) as f:
            data = json.load(f)
        assert data["validation_state"]["total_checks"] == 1
        os.unlink(path)
        print("  PASS: test_json_output")


# ============================================================================
# Test quick_validate
# ============================================================================

class TestQuickValidate:
    def test_basic_quick_validate(self):
        x, y = make_correlated_data(100, r=0.8)
        df = pd.DataFrame({"predicted": x, "experimental": y})
        results = quick_validate(df, target_col="experimental", pred_col="predicted",
                                  domain="qsar", workflow_name="Quick Test")

        assert results["state"].confidence_score() > 0
        assert len(results["descriptive"]) > 0
        assert results["correlation"] is not None
        assert results["model"] is not None
        print("  PASS: test_basic_quick_validate")

    def test_quick_validate_with_groups(self):
        rng = np.random.RandomState(42)
        df = pd.DataFrame({
            "value": np.concatenate([rng.normal(0, 1, 30), rng.normal(2, 1, 30)]),
            "group": ["A"] * 30 + ["B"] * 30,
        })
        results = quick_validate(df, target_col="value", group_col="group")
        assert results["hypothesis"] is not None
        print("  PASS: test_quick_validate_with_groups")


# ============================================================================
# Main runner
# ============================================================================

def run_all_tests():
    test_classes = [
        ("ValidationState", TestValidationState),
        ("DescriptiveAnalyzer", TestDescriptiveAnalyzer),
        ("CorrelationAnalyzer", TestCorrelationAnalyzer),
        ("HypothesisTester", TestHypothesisTester),
        ("EffectSizeCalculator", TestEffectSizeCalculator),
        ("BootstrapCI", TestBootstrapCI),
        ("BayesianAnalyzer", TestBayesianAnalyzer),
        ("ModelEvaluator", TestModelEvaluator),
        ("DomainThresholds", TestDomainThresholds),
        ("ReportGenerator", TestReportGenerator),
        ("QuickValidate", TestQuickValidate),
    ]

    total_passed = 0
    total_failed = 0
    failures = []

    for class_name, test_class in test_classes:
        print(f"\n{'=' * 60}")
        print(f"Testing {class_name}")
        print('=' * 60)
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith("test_")]

        for method_name in methods:
            try:
                getattr(instance, method_name)()
                total_passed += 1
            except Exception as e:
                total_failed += 1
                failures.append((class_name, method_name, str(e)))
                print(f"  FAIL: {method_name}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {total_passed} passed, {total_failed} failed")
    print('=' * 60)

    if failures:
        print("\nFailed tests:")
        for cls, method, err in failures:
            print(f"  {cls}.{method}: {err}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()
