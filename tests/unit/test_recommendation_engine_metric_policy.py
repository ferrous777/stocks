import pytest

from recommendations.recommendation_engine import RecommendationEngine


def test_generate_metric_recommendations_maps_actions_per_strategy():
    engine = RecommendationEngine()

    recommendations = engine.generate_metric_recommendations(
        {
            "trend": {
                "sharpe_ratio": 2.4,
                "calmar_ratio": 2.3,
                "max_drawdown": 0.1,
                "total_return": 0.25,
            },
            "mean_reversion": {
                "sharpe_ratio": -0.8,
                "calmar_ratio": -0.3,
                "max_drawdown": 0.4,
                "total_return": -0.1,
            },
        },
        risk_profile="moderate",
    )

    assert recommendations["trend"]["action"] == "buy"
    assert recommendations["mean_reversion"]["action"] == "short"


def test_generate_metric_recommendations_raises_on_missing_required_metrics():
    engine = RecommendationEngine()

    with pytest.raises(ValueError, match="Missing required metrics"):
        engine.generate_metric_recommendations(
            {
                "trend": {
                    "sharpe_ratio": 1.0,
                }
            }
        )
