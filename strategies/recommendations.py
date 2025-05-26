from typing import List

class Recommendations:
    def generate_recommendations(self, symbol: str, data: List[DataPoint]) -> dict:
        """Generate and save trading recommendations"""
        recommendations = {
            "current_price": self._calculate_current_price(data),
            # Technical Indicators
            "sma_signal": self._get_sma_signal(data),
            "sma_trend": self._get_sma_trend(data),
            "sma_strength": self._calculate_sma_strength(data),
            "sma20": self._calculate_sma(data, 20),
            "sma50": self._calculate_sma(data, 50),
            "sma200": self._calculate_sma(data, 200),
            
            "macd_signal": self._get_macd_signal(data),
            "macd_line": self._calculate_macd_line(data),
            "signal_line": self._calculate_signal_line(data),
            "macd_histogram": self._calculate_macd_histogram(data),
            "macd_trend": self._get_macd_trend(data),
            "macd_strength": self._calculate_macd_strength(data),
            
            "rsi_signal": self._get_rsi_signal(data),
            "rsi_value": self._calculate_rsi(data),
            "rsi_trend": self._get_rsi_trend(data),
            "rsi_strength": self._calculate_rsi_strength(data),
            
            "bollinger_signal": self._get_bollinger_signal(data),
            "upper_band": self._calculate_upper_band(data),
            "middle_band": self._calculate_middle_band(data),
            "lower_band": self._calculate_lower_band(data),
            "bollinger_bandwidth": self._calculate_bandwidth(data),
            "bollinger_percent_b": self._calculate_percent_b(data),
            
            # Volume Analysis
            "current_volume": data[-1].volume,
            "volume_10d_avg": self._calculate_volume_avg(data, 10),
            "volume_30d_avg": self._calculate_volume_avg(data, 30),
            "volume_trend": self._get_volume_trend(data),
            
            # Price Action
            "price_trend": self._get_price_trend(data),
            "support_levels": self._find_support_levels(data),
            "resistance_levels": self._find_resistance_levels(data),
            "year_high": self._calculate_52w_high(data),
            "year_low": self._calculate_52w_low(data),
            "distance_from_high": self._calculate_distance_from_high(data),
            "distance_from_low": self._calculate_distance_from_low(data),
            
            # Volatility
            "current_volatility": self._calculate_current_volatility(data),
            "avg_volatility": self._calculate_avg_volatility(data),
            "volatility_trend": self._get_volatility_trend(data),
            
            # Overall Analysis
            "overall_signal": self._generate_overall_signal(data),
            "confidence_score": self._calculate_confidence_score(data),
            "risk_level": self._assess_risk_level(data),
            "suggested_position_size": self._calculate_position_size(data),
            
            # Entry/Exit Points
            "aggressive_entry": self._calculate_aggressive_entry(data),
            "conservative_entry": self._calculate_conservative_entry(data),
            "stop_loss": self._calculate_stop_loss(data),
            "take_profit": self._calculate_take_profit(data),
            "suggested_time_horizon": self._suggest_time_horizon(data),
            
            # Risk Analysis
            "risk_reward_ratio": self._calculate_risk_reward_ratio(data),
            "max_loss_percent": self._calculate_max_loss(data),
            "volatility_risk": self._assess_volatility_risk(data),
            "liquidity_risk": self._assess_liquidity_risk(data),
            "overall_risk_score": self._calculate_overall_risk(data),
            
            # Market Context
            "market_condition": self._assess_market_condition(data),
            "sector_trend": self._get_sector_trend(data),
            "correlation_sp500": self._calculate_sp500_correlation(data),
            "relative_strength": self._calculate_relative_strength(data)
        }
        
        # Save recommendations to cache
        self.market_data.save_recommendations(symbol, recommendations)
        
        return recommendations 