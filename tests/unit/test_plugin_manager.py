import pytest

from strategies.plugin_manager import StrategyPluginManager


def test_discover_and_load_plugins_from_package(tmp_path, monkeypatch):
    package_name = "test_plugins"
    package_dir = tmp_path / package_name
    package_dir.mkdir()

    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "demo_plugin.py").write_text(
        "\n".join(
            [
                "from strategies.plugin_contract import StrategyMetadata, StrategyPlugin",
                "",
                "class DemoPlugin(StrategyPlugin):",
                "    metadata = StrategyMetadata(",
                "        name='demo',",
                "        version='1.0.0',",
                "        supported_asset_classes=('equity',),",
                "        holding_horizon='medium',",
                "    )",
                "",
                "    def prepare_data(self, raw_data):",
                "        return dict(raw_data)",
                "",
                "    def run_backtest(self, prepared_data):",
                "        return {'trades': []}",
                "",
                "    def compute_metrics(self, backtest_output):",
                "        return {'sharpe_ratio': 1.0, 'max_drawdown': 0.1}",
                "",
                "    def generate_recommendation(self, metrics, risk_profile='moderate'):",
                "        return {'action': 'hold'}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    manager = StrategyPluginManager(package=package_name)
    classes = manager.discover_plugin_classes(path=[str(package_dir)])
    assert "demo" in classes

    loaded = manager.load_plugins(path=[str(package_dir)])
    assert "demo" in loaded.loaded
    assert loaded.failures == {}


def test_missing_metadata_name_raises(tmp_path, monkeypatch):
    package_name = "bad_plugins"
    package_dir = tmp_path / package_name
    package_dir.mkdir()

    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "bad_plugin.py").write_text(
        "\n".join(
            [
                "from strategies.plugin_contract import StrategyMetadata, StrategyPlugin",
                "",
                "class BadPlugin(StrategyPlugin):",
                "    metadata = StrategyMetadata(",
                "        name='',",
                "        version='1.0.0',",
                "        supported_asset_classes=('equity',),",
                "        holding_horizon='long',",
                "    )",
                "",
                "    def prepare_data(self, raw_data):",
                "        return {}",
                "",
                "    def run_backtest(self, prepared_data):",
                "        return {}",
                "",
                "    def compute_metrics(self, backtest_output):",
                "        return {}",
                "",
                "    def generate_recommendation(self, metrics, risk_profile='moderate'):",
                "        return {'action': 'avoid'}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    manager = StrategyPluginManager(package=package_name)

    try:
        manager.discover_plugin_classes(path=[str(package_dir)])
        assert False, "Expected ValueError for missing metadata.name"
    except ValueError as exc:
        assert "missing metadata.name" in str(exc)


def test_duplicate_plugin_name_raises(tmp_path, monkeypatch):
    package_name = "dupe_plugins"
    package_dir = tmp_path / package_name
    package_dir.mkdir()

    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "plugin_one.py").write_text(
        "\n".join(
            [
                "from strategies.plugin_contract import StrategyMetadata, StrategyPlugin",
                "",
                "class PluginOne(StrategyPlugin):",
                "    metadata = StrategyMetadata('shared', '1.0.0', ('equity',), 'medium')",
                "    def prepare_data(self, raw_data): return {}",
                "    def run_backtest(self, prepared_data): return {}",
                "    def compute_metrics(self, backtest_output): return {}",
                "    def generate_recommendation(self, metrics, risk_profile='moderate'): return {'action': 'hold'}",
            ]
        ),
        encoding="utf-8",
    )
    (package_dir / "plugin_two.py").write_text(
        "\n".join(
            [
                "from strategies.plugin_contract import StrategyMetadata, StrategyPlugin",
                "",
                "class PluginTwo(StrategyPlugin):",
                "    metadata = StrategyMetadata('shared', '2.0.0', ('equity',), 'long')",
                "    def prepare_data(self, raw_data): return {}",
                "    def run_backtest(self, prepared_data): return {}",
                "    def compute_metrics(self, backtest_output): return {}",
                "    def generate_recommendation(self, metrics, risk_profile='moderate'): return {'action': 'hold'}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    manager = StrategyPluginManager(package=package_name)

    with pytest.raises(ValueError, match="Duplicate plugin metadata.name"):
        manager.discover_plugin_classes(path=[str(package_dir)])
