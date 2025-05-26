"""
SVM-based Time Estimator

Uses Support Vector Regression to predict time-to-target
based on technical features. Requires training data.
"""

from typing import List, Optional, Tuple
from .base import TimeEstimator, TimeEstimate
import math


class SVMTimeEstimator(TimeEstimator):
    """
    Estimates time-to-target using Support Vector Regression.
    
    This is a simplified SVM implementation that doesn't require sklearn.
    For production, consider using sklearn.svm.SVR.
    
    Features used:
    - Volatility (ATR-based)
    - Momentum (ROC)
    - Trend strength
    - Distance to target (%)
    - RSI
    - Volume ratio
    """
    
    def __init__(self):
        super().__init__(
            name="SVM Time Estimator",
            description="Machine learning model for time prediction"
        )
        # Pre-trained coefficients (simplified linear model)
        # In production, these would be learned from historical data
        self.coefficients = {
            'intercept': 15.0,        # Base days
            'volatility': -50.0,      # Higher vol = fewer days
            'momentum_aligned': -5.0,  # Aligned momentum = fewer days
            'trend_strength': -20.0,   # Stronger trend = fewer days
            'distance_pct': 100.0,     # Larger distance = more days
            'rsi_extreme': -3.0,       # Extreme RSI = fewer days (mean reversion)
            'volume_spike': -2.0,      # High volume = fewer days
        }
        self.is_trained = False  # Track if model has been fitted
        self.training_samples = []
    
    def get_min_data_points(self) -> int:
        return 30
    
    def _extract_features(
        self,
        current_price: float,
        target_price: float,
        data_points: List[dict],
        direction: str
    ) -> dict:
        """Extract features for prediction"""
        sorted_data = sorted(data_points, key=lambda x: x['date'], reverse=True)
        
        features = {}
        
        # 1. Volatility (ATR-based, normalized)
        atr = self._calculate_atr(sorted_data, 14)
        features['volatility'] = atr / current_price if current_price > 0 else 0
        
        # 2. Momentum alignment
        roc = self._calculate_roc(sorted_data, 10)
        if direction == "long":
            features['momentum_aligned'] = 1 if roc > 0 else 0
        else:
            features['momentum_aligned'] = 1 if roc < 0 else 0
        
        # 3. Trend strength (absolute)
        trend = self._calculate_trend_strength(sorted_data, 20)
        features['trend_strength'] = abs(trend)
        
        # 4. Distance to target
        distance = self.calculate_price_distance(current_price, target_price, direction)
        features['distance_pct'] = abs(distance)
        
        # 5. RSI extremity (how far from 50)
        rsi = self._calculate_rsi(sorted_data, 14)
        features['rsi_extreme'] = abs(rsi - 50) / 50
        
        # 6. Volume spike
        vol_ratio = self._calculate_volume_ratio(sorted_data)
        features['volume_spike'] = 1 if vol_ratio > 1.5 else 0
        
        return features
    
    def _calculate_atr(self, data_points: List[dict], period: int) -> float:
        """Calculate ATR"""
        if len(data_points) < period + 1:
            return 0
        
        true_ranges = []
        for i in range(1, period + 1):
            high = data_points[i]['high']
            low = data_points[i]['low']
            prev_close = data_points[i-1]['close']
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0
    
    def _calculate_roc(self, data_points: List[dict], period: int) -> float:
        """Calculate Rate of Change"""
        if len(data_points) <= period:
            return 0
        current = data_points[0]['close']
        past = data_points[period]['close']
        return (current - past) / past if past > 0 else 0
    
    def _calculate_trend_strength(self, data_points: List[dict], period: int) -> float:
        """Calculate trend strength via slope"""
        if len(data_points) < period:
            return 0
        
        closes = [p['close'] for p in data_points[:period]]
        closes.reverse()
        
        n = len(closes)
        x_mean = (n - 1) / 2
        y_mean = sum(closes) / n
        
        numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0 or y_mean == 0:
            return 0
        
        slope = numerator / denominator
        return slope / y_mean
    
    def _calculate_rsi(self, data_points: List[dict], period: int) -> float:
        """Calculate RSI"""
        if len(data_points) < period + 1:
            return 50
        
        gains, losses = [], []
        for i in range(1, period + 1):
            change = data_points[i-1]['close'] - data_points[i]['close']
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_volume_ratio(self, data_points: List[dict]) -> float:
        """Calculate current volume vs average"""
        if len(data_points) < 21:
            return 1.0
        
        current_vol = data_points[0].get('volume', 0)
        avg_vol = sum(p.get('volume', 0) for p in data_points[1:21]) / 20
        
        return current_vol / avg_vol if avg_vol > 0 else 1.0
    
    def _predict(self, features: dict) -> float:
        """Make prediction using linear model"""
        prediction = self.coefficients['intercept']
        
        prediction += self.coefficients['volatility'] * features['volatility']
        prediction += self.coefficients['momentum_aligned'] * features['momentum_aligned']
        prediction += self.coefficients['trend_strength'] * features['trend_strength']
        prediction += self.coefficients['distance_pct'] * features['distance_pct']
        prediction += self.coefficients['rsi_extreme'] * features['rsi_extreme']
        prediction += self.coefficients['volume_spike'] * features['volume_spike']
        
        return max(1, prediction)  # Minimum 1 day
    
    def train(self, training_data: List[Tuple[dict, float]]):
        """
        Train the model on historical data.
        
        Args:
            training_data: List of (features_dict, actual_days) tuples
        """
        if len(training_data) < 10:
            return  # Not enough data
        
        self.training_samples = training_data
        
        # Simple gradient descent to fit coefficients
        learning_rate = 0.01
        iterations = 100
        
        for _ in range(iterations):
            total_error = 0
            gradients = {k: 0 for k in self.coefficients}
            
            for features, actual_days in training_data:
                predicted = self._predict(features)
                error = predicted - actual_days
                total_error += error ** 2
                
                # Calculate gradients
                gradients['intercept'] += error
                for key in features:
                    if key in self.coefficients:
                        gradients[key] += error * features[key]
            
            # Update coefficients
            n = len(training_data)
            for key in self.coefficients:
                self.coefficients[key] -= learning_rate * gradients[key] / n
        
        self.is_trained = True
    
    def estimate(
        self,
        current_price: float,
        target_price: float,
        stop_price: float,
        data_points: List[dict],
        direction: str = "long"
    ) -> Optional[TimeEstimate]:
        
        if not self.validate_inputs(current_price, target_price, stop_price, data_points):
            return None
        
        # Extract features
        features = self._extract_features(current_price, target_price, data_points, direction)
        
        # Make prediction
        days_to_target = self._predict(features)
        
        # Estimate stop timing (typically faster)
        stop_distance = self.calculate_price_distance(current_price, stop_price,
                                                       "short" if direction == "long" else "long")
        target_distance = features['distance_pct']
        
        if target_distance > 0:
            days_to_stop = days_to_target * (abs(stop_distance) / target_distance)
        else:
            days_to_stop = days_to_target * 0.5
        
        # Estimate uncertainty
        base_uncertainty = 0.3 if self.is_trained else 0.5
        range_low = days_to_target * (1 - base_uncertainty)
        range_high = days_to_target * (1 + base_uncertainty * 2)
        
        # Confidence based on training and feature quality
        confidence = 0.6 if self.is_trained else 0.4
        if features['momentum_aligned']:
            confidence += 0.1
        if features['trend_strength'] > 0.001:
            confidence += 0.1
        
        confidence = min(0.85, confidence)
        
        return TimeEstimate(
            estimator_name=self.name,
            days_to_target=days_to_target,
            days_to_stop=max(1, days_to_stop),
            confidence=round(confidence, 2),
            range_low=max(1, range_low),
            range_high=range_high,
            methodology=f"SVM features: vol={features['volatility']:.4f}, dist={features['distance_pct']:.3f}, trained={self.is_trained}"
        )
