from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Type

from strategies.plugin_contract import StrategyPlugin


@dataclass
class PluginLoadResult:
    loaded: Dict[str, StrategyPlugin] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)


class StrategyPluginManager:
    """Discovers and instantiates strategy plug-ins by package scanning."""

    def __init__(self, package: str = "strategies"):
        self.package = package

    def discover_plugin_classes(self, path: Optional[Iterable[str]] = None) -> Dict[str, Type[StrategyPlugin]]:
        discovered: Dict[str, Type[StrategyPlugin]] = {}

        if path is None:
            package_module = importlib.import_module(self.package)
            path = getattr(package_module, "__path__", None)
            if path is None:
                raise ValueError(f"Package '{self.package}' is not a package or has no __path__")

        for module_info in pkgutil.iter_modules(path):
            if module_info.name.startswith("_"):
                continue

            module_name = f"{self.package}.{module_info.name}"
            module = importlib.import_module(module_name)

            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if not issubclass(candidate, StrategyPlugin) or candidate is StrategyPlugin:
                    continue
                metadata = getattr(candidate, "metadata", None)
                if metadata is None or not getattr(metadata, "name", ""):
                    raise ValueError(
                        f"Plugin class {candidate.__name__} in {module_name} is missing metadata.name"
                    )

                existing = discovered.get(metadata.name)
                if existing is not None and existing is not candidate:
                    raise ValueError(
                        f"Duplicate plugin metadata.name '{metadata.name}' found in {module_name} "
                        f"and {existing.__module__}"
                    )
                discovered[metadata.name] = candidate

        return discovered

    def load_plugins(self, path: Optional[Iterable[str]] = None) -> PluginLoadResult:
        result = PluginLoadResult()

        if path is None:
            package_module = importlib.import_module(self.package)
            path = getattr(package_module, "__path__", None)
            if path is None:
                raise ValueError(f"Package '{self.package}' is not a package or has no __path__")

        discovered_classes: Dict[str, Type[StrategyPlugin]] = {}

        for module_info in pkgutil.iter_modules(path):
            if module_info.name.startswith("_"):
                continue

            module_name = f"{self.package}.{module_info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                result.failures[module_name] = str(exc)
                continue

            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if not issubclass(candidate, StrategyPlugin) or candidate is StrategyPlugin:
                    continue

                metadata = getattr(candidate, "metadata", None)
                if metadata is None or not getattr(metadata, "name", ""):
                    result.failures[f"{module_name}.{candidate.__name__}"] = "missing metadata.name"
                    continue

                existing = discovered_classes.get(metadata.name)
                if existing is not None and existing is not candidate:
                    result.failures[metadata.name] = (
                        f"Duplicate plugin metadata.name '{metadata.name}' found in {module_name} "
                        f"and {existing.__module__}"
                    )
                    continue

                discovered_classes[metadata.name] = candidate

        for name, plugin_class in discovered_classes.items():
            try:
                result.loaded[name] = plugin_class()
            except Exception as exc:
                result.failures[name] = str(exc)

        return result
