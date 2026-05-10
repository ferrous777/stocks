"""
Tests for recommendation generation consistency.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import generate_recommendations_from_strategies


class TestRecommendationGeneration(unittest.TestCase):
    def test_hold_recommendation_has_neutral_target_levels(self):
        strategy_results = {
            "trend_following": {"signal": "HOLD", "confidence": 0.2},
            "momentum": {"signal": "HOLD", "confidence": 0.3},
            "mean_reversion": {"signal": "HOLD", "confidence": 0.1},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "AAPL_historical.json")
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {
                        "symbol": "AAPL",
                        "data_points": [
                            {"date": "2026-05-08", "close": 293.32}
                        ],
                    },
                    cache_file,
                )

            with patch("app.CACHE_DIR", temp_dir):
                rec = generate_recommendations_from_strategies("AAPL", strategy_results, "20260509")

        self.assertIsNotNone(rec)
        self.assertEqual(rec["action"], "HOLD")
        self.assertEqual(rec["entry_price"], rec["stop_loss"])
        self.assertEqual(rec["entry_price"], rec["take_profit"])
        self.assertIsNone(rec["time_estimate"])


if __name__ == "__main__":
    unittest.main()
