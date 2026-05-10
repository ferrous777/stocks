from utils.recommendation_contract import (
    normalize_recommendation_payload,
    validate_recommendation_payload,
)


def test_normalize_buy_payload_has_required_fields():
    payload = {
        "symbol": "AMD",
        "analysis_date": "20260509",
        "recommendations": {
            "action": "BUY",
            "confidence": 0.8,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "signals": [{"strategy": "momentum_strategy", "signal": "BUY", "confidence": 0.7}],
        },
    }

    normalized = normalize_recommendation_payload(payload, symbol="AMD", analysis_date="20260509")
    ok, errors = validate_recommendation_payload(normalized)

    assert ok, errors
    rec = normalized["recommendations"]
    assert rec["risk_level"] in {"LOW", "MEDIUM", "HIGH", "N/A"}
    assert isinstance(rec["signals"], list)
    assert "benchmark" in rec
    assert "metrics" in rec


def test_normalize_hold_payload_is_neutral_and_valid():
    payload = {
        "recommendations": {
            "action": "HOLD",
            "confidence": 0.2,
            "entry_price": 250.0,
            "signals": [],
        }
    }

    normalized = normalize_recommendation_payload(payload, symbol="AAPL", analysis_date="20260509")
    ok, errors = validate_recommendation_payload(normalized)

    assert ok, errors
    rec = normalized["recommendations"]
    assert rec["stop_loss"] == 250.0
    assert rec["take_profit"] == 250.0
    assert rec["risk_level"] == "N/A"


def test_invalid_action_falls_back_to_hold():
    payload = {
        "recommendations": {
            "action": "WHATEVER",
            "confidence": 0.5,
            "entry_price": 10,
        }
    }

    normalized = normalize_recommendation_payload(payload, symbol="TSLA", analysis_date="20260509")
    ok, errors = validate_recommendation_payload(normalized)

    assert ok, errors
    assert normalized["recommendations"]["action"] == "HOLD"
