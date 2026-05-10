from recommendations.recommendation_engine import RecommendationEngine


def test_weighted_consensus_prefers_stronger_bullish_side_on_tie():
    engine = RecommendationEngine()
    engine.min_confidence = 0.0

    symbol = "AMD"
    analysis_results = {
        "trend_following": {
            symbol: {
                "signal": "long",
                "confidence": 0.9,
                "details": "strong trend",
                "metrics": {"close": 100.0, "trend_strength": 0.8, "volatility": 0.02},
            }
        },
        "momentum": {
            symbol: {
                "signal": "long",
                "confidence": 0.8,
                "details": "strong momentum",
                "metrics": {"close": 100.0, "trend_strength": 0.7, "volatility": 0.02},
            }
        },
        "mean_reversion": {
            symbol: {
                "signal": "short",
                "confidence": 0.4,
                "details": "weak counter-signal",
                "metrics": {"close": 100.0, "trend_strength": 0.2, "volatility": 0.02},
            }
        },
        "bollinger": {
            symbol: {
                "signal": "short",
                "confidence": 0.4,
                "details": "weak counter-signal",
                "metrics": {"close": 100.0, "trend_strength": 0.2, "volatility": 0.02},
            }
        },
    }

    backtest_results = {}
    recommendations = engine.generate_recommendations([symbol], analysis_results, backtest_results)

    assert recommendations[symbol]["action"] == "BUY"
    assert recommendations[symbol]["supporting_strategies"] == ["trend_following", "momentum"]
