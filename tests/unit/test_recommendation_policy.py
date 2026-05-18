import pytest

from recommendations.recommendation_policy import (
    RecommendationPolicy,
    RecommendationPolicyConfig,
    RiskThresholdOverride,
    evaluate_recommendation,
)


def test_buy_recommendation_for_strong_metrics():
    result = evaluate_recommendation(
        {
            "sharpe_ratio": 2.4,
            "calmar_ratio": 2.2,
            "max_drawdown": 0.12,
            "total_return": 0.28,
        },
        risk_profile="moderate",
    )
    assert result["action"] == "buy"


def test_short_recommendation_for_poor_metrics():
    result = evaluate_recommendation(
        {
            "sharpe_ratio": -0.8,
            "calmar_ratio": -0.3,
            "max_drawdown": 0.35,
            "total_return": -0.14,
        },
        risk_profile="moderate",
    )
    assert result["action"] == "short"


def test_hold_recommendation_for_mid_quality_metrics():
    result = evaluate_recommendation(
        {
            "sharpe_ratio": 0.9,
            "calmar_ratio": 1.0,
            "max_drawdown": 0.16,
            "total_return": 0.06,
        },
        risk_profile="moderate",
    )
    assert result["action"] == "hold"


def test_avoid_when_thresholds_not_met():
    result = evaluate_recommendation(
        {
            "sharpe_ratio": 0.1,
            "calmar_ratio": 0.2,
            "max_drawdown": 0.4,
            "total_return": 0.01,
        },
        risk_profile="moderate",
    )
    assert result["action"] == "avoid"


def test_unsupported_risk_profile_raises():
    with pytest.raises(ValueError):
        evaluate_recommendation({}, risk_profile="unsupported")


def test_strategy_specific_override_changes_thresholds():
    policy = RecommendationPolicy(
        RecommendationPolicyConfig(
            strategy_overrides={
                "momentum": RiskThresholdOverride(min_buy_sharpe=1.2, max_buy_drawdown=0.2)
            }
        )
    )

    thresholds = policy.get_thresholds(risk_profile="moderate", strategy_name="momentum")

    assert thresholds.min_buy_sharpe == 1.2
    assert thresholds.max_buy_drawdown == 0.2
    assert thresholds.min_buy_calmar == 2.0


def test_evaluate_recommendation_uses_override_policy():
    policy = RecommendationPolicy(
        RecommendationPolicyConfig(
            strategy_overrides={
                "trend": RiskThresholdOverride(min_buy_sharpe=1.0, min_buy_calmar=1.0, max_buy_drawdown=0.25)
            }
        )
    )

    result = evaluate_recommendation(
        {
            "sharpe_ratio": 1.1,
            "calmar_ratio": 1.05,
            "max_drawdown": 0.2,
            "total_return": 0.12,
        },
        risk_profile="moderate",
        strategy_name="trend",
        policy=policy,
    )

    assert result["action"] == "buy"
