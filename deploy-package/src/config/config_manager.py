"""
Configuration management for the stock analysis system
"""
import os
import json
import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

@dataclass
class SymbolConfig:
    """Configuration for a single symbol"""
    symbol: str
    enabled: bool = True
    sector: Optional[str] = None
    priority: int = 1  # 1=high, 2=medium, 3=low
    custom_params: Optional[Dict[str, Any]] = None

@dataclass
class StrategyConfig:
    """Configuration for a trading strategy"""
    name: str
    enabled: bool = True
    weight: float = 1.0
    parameters: Dict[str, Any] = None
    min_data_points: int = 30

@dataclass
class DatabaseConfig:
    """Database configuration"""
    db_path: str = "data/timeseries.db"
    backup_enabled: bool = True
    backup_frequency: str = "daily"  # daily, weekly, monthly
    retention_days: int = 365
    compression_enabled: bool = True

@dataclass
class SchedulingConfig:
    """Scheduling configuration"""
    enabled: bool = True
    market_data_time: str = "16:30"  # After market close
    analysis_time: str = "17:00"     # After data collection
    timezone: str = "US/Eastern"
    skip_weekends: bool = True
    skip_holidays: bool = True

@dataclass
class DataSourceConfig:
    """Data source configuration"""
    primary_source: str = "yahoo"  # yahoo, alpha_vantage, iex
    backup_sources: List[str] = None
    cache_enabled: bool = True
    cache_duration_hours: int = 24
    rate_limit_per_minute: int = 60

@dataclass
class NotificationConfig:
    """Notification settings"""
    enabled: bool = False
    email_enabled: bool = False
    email_recipients: List[str] = None
    alert_thresholds: Dict[str, float] = None
    summary_frequency: str = "daily"  # daily, weekly, monthly

@dataclass
class SystemConfig:
    """Main system configuration"""
    symbols: List[SymbolConfig]
    strategies: List[StrategyConfig]
    database: DatabaseConfig
    scheduling: SchedulingConfig
    data_source: DataSourceConfig
    notifications: NotificationConfig
    
    # Environment settings
    environment: str = "development"  # development, production
    debug_mode: bool = False
    log_level: str = "INFO"
    log_file: Optional[str] = "logs/system.log"

class ConfigManager:
    """Manage system configuration"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        self.config_file = self.config_dir / "system_config.yaml"
        self._config: Optional[SystemConfig] = None
    
    def get_config(self) -> SystemConfig:
        """Get current configuration, loading if necessary"""
        if self._config is None:
            self._config = self.load_config()
        return self._config
    
    def load_config(self) -> SystemConfig:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = yaml.safe_load(f)
                return self._dict_to_config(data)
            except Exception as e:
                print(f"Error loading config: {e}")
                print("Using default configuration")
        
        # Return default configuration
        return self.get_default_config()
    
    def save_config(self, config: SystemConfig = None):
        """Save configuration to file"""
        if config is None:
            config = self.get_config()
        
        config_dict = asdict(config)
        
        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            print(f"Configuration saved to {self.config_file}")
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def get_default_config(self) -> SystemConfig:
        """Get default configuration"""
        # Default symbol list (current stocks we're tracking)
        default_symbols = [
            SymbolConfig("AAPL", enabled=True, sector="Technology", priority=1),
            SymbolConfig("NVDA", enabled=True, sector="Technology", priority=1),
            SymbolConfig("GOOGL", enabled=True, sector="Technology", priority=1),
            SymbolConfig("MSFT", enabled=True, sector="Technology", priority=1),
            SymbolConfig("AMZN", enabled=True, sector="Technology", priority=1),
            SymbolConfig("ADBE", enabled=True, sector="Technology", priority=2),
            SymbolConfig("CRM", enabled=True, sector="Technology", priority=2),
            SymbolConfig("NOW", enabled=True, sector="Technology", priority=2),
            SymbolConfig("AMD", enabled=True, sector="Technology", priority=2),
            SymbolConfig("AVGO", enabled=True, sector="Technology", priority=2),
            SymbolConfig("ACN", enabled=True, sector="Technology", priority=2),
            SymbolConfig("IBM", enabled=True, sector="Technology", priority=3),
            SymbolConfig("COST", enabled=True, sector="Consumer", priority=2),
            SymbolConfig("ET", enabled=True, sector="Energy", priority=3),
        ]
        
        # Default strategies
        default_strategies = [
            StrategyConfig(
                name="moving_average_crossover",
                enabled=True,
                weight=1.0,
                parameters={"short_period": 20, "long_period": 50},
                min_data_points=60
            ),
            StrategyConfig(
                name="rsi_divergence",
                enabled=True,
                weight=0.8,
                parameters={"period": 14, "oversold": 30, "overbought": 70},
                min_data_points=30
            ),
            StrategyConfig(
                name="macd",
                enabled=True,
                weight=0.9,
                parameters={"fast": 12, "slow": 26, "signal": 9},
                min_data_points=35
            ),
            StrategyConfig(
                name="volume_price",
                enabled=True,
                weight=0.7,
                parameters={"volume_threshold": 2.0, "price_threshold": 0.02},
                min_data_points=20
            ),
        ]
        
        return SystemConfig(
            symbols=default_symbols,
            strategies=default_strategies,
            database=DatabaseConfig(),
            scheduling=SchedulingConfig(),
            data_source=DataSourceConfig(backup_sources=["alpha_vantage"]),
            notifications=NotificationConfig(
                alert_thresholds={
                    "confidence_threshold": 0.8,
                    "price_change_threshold": 0.05
                }
            )
        )
    
    def _dict_to_config(self, data: Dict[str, Any]) -> SystemConfig:
        """Convert dictionary to SystemConfig object"""
        # Convert symbols
        symbols = []
        for sym_data in data.get('symbols', []):
            symbols.append(SymbolConfig(**sym_data))
        
        # Convert strategies
        strategies = []
        for strat_data in data.get('strategies', []):
            strategies.append(StrategyConfig(**strat_data))
        
        # Convert other configs
        database = DatabaseConfig(**data.get('database', {}))
        scheduling = SchedulingConfig(**data.get('scheduling', {}))
        data_source = DataSourceConfig(**data.get('data_source', {}))
        notifications = NotificationConfig(**data.get('notifications', {}))
        
        return SystemConfig(
            symbols=symbols,
            strategies=strategies,
            database=database,
            scheduling=scheduling,
            data_source=data_source,
            notifications=notifications,
            environment=data.get('environment', 'development'),
            debug_mode=data.get('debug_mode', False),
            log_level=data.get('log_level', 'INFO'),
            log_file=data.get('log_file')
        )
    
    def clear_symbols(self):
        """Remove all symbols from configuration"""
        config = self.get_config()
        config.symbols = []
        self.save_config(config)
        print("Cleared all symbols from configuration")
        return True

    def add_symbol(self, symbol: str, sector: str = None, priority: int = 2):
        """Add a new symbol to track"""
        config = self.get_config()
        
        # Check if symbol already exists
        existing = next((s for s in config.symbols if s.symbol == symbol), None)
        if existing:
            print(f"Symbol {symbol} already exists")
            return False
        
        config.symbols.append(SymbolConfig(
            symbol=symbol,
            enabled=True,
            sector=sector,
            priority=priority
        ))
        
        self.save_config(config)
        print(f"Added symbol {symbol}")
        return True
    
    def remove_symbol(self, symbol: str):
        """Remove a symbol from tracking"""
        config = self.get_config()
        original_count = len(config.symbols)
        config.symbols = [s for s in config.symbols if s.symbol != symbol]
        
        if len(config.symbols) < original_count:
            self.save_config(config)
            print(f"Removed symbol {symbol}")
            return True
        else:
            print(f"Symbol {symbol} not found")
            return False
    
    def enable_symbol(self, symbol: str, enabled: bool = True):
        """Enable or disable a symbol"""
        config = self.get_config()
        
        for sym_config in config.symbols:
            if sym_config.symbol == symbol:
                sym_config.enabled = enabled
                self.save_config(config)
                status = "enabled" if enabled else "disabled"
                print(f"Symbol {symbol} {status}")
                return True
        
        print(f"Symbol {symbol} not found")
        return False
    
    def get_enabled_symbols(self) -> List[str]:
        """Get list of enabled symbols"""
        config = self.get_config()
        return [s.symbol for s in config.symbols if s.enabled]
    
    def get_enabled_strategies(self) -> List[StrategyConfig]:
        """Get list of enabled strategies"""
        config = self.get_config()
        return [s for s in config.strategies if s.enabled]
    
    def update_strategy_weight(self, strategy_name: str, weight: float):
        """Update strategy weight"""
        config = self.get_config()
        
        for strategy in config.strategies:
            if strategy.name == strategy_name:
                strategy.weight = weight
                self.save_config(config)
                print(f"Updated {strategy_name} weight to {weight}")
                return True
        
        print(f"Strategy {strategy_name} not found")
        return False

# Singleton instance
_config_manager = None

def get_config_manager() -> ConfigManager:
    """Get global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

def get_config() -> SystemConfig:
    """Get current system configuration"""
    return get_config_manager().get_config()
