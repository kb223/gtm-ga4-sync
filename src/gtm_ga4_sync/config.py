"""events.yml loader + shape validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EventsConfig:
    """Parsed events.yml contents."""

    events: dict[str, list[str]]            # event_name -> [param1, param2, ...]
    metrics: list[str] = field(default_factory=list)
    display_names: dict[str, str] = field(default_factory=dict)

    @property
    def all_params(self) -> list[str]:
        """Unique parameter names across every event, preserving first-seen order."""
        seen: list[str] = []
        for params in self.events.values():
            for p in params:
                if p not in seen:
                    seen.append(p)
        return seen

    def dimension_params(self) -> list[str]:
        """Params that should become custom dimensions (string-valued)."""
        metrics_set = set(self.metrics)
        return [p for p in self.all_params if p not in metrics_set]

    def display_name(self, param: str) -> str:
        if param in self.display_names:
            return self.display_names[param]
        # Default: Title Case with underscores as spaces
        return param.replace("_", " ").title()


def load_config(path: Path) -> EventsConfig:
    """Load and validate an events.yml file."""
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}

    events_raw = data.get("events")
    if not isinstance(events_raw, dict) or not events_raw:
        raise ValueError(f"{path}: expected a non-empty 'events' mapping at the top level")

    events: dict[str, list[str]] = {}
    for event_name, event_def in events_raw.items():
        if not isinstance(event_name, str) or not event_name:
            raise ValueError(f"{path}: event names must be non-empty strings (got {event_name!r})")
        if isinstance(event_def, dict):
            params = event_def.get("params") or []
        elif isinstance(event_def, list):
            params = event_def
        elif event_def is None:
            params = []
        else:
            raise ValueError(
                f"{path}: event '{event_name}' must be a mapping with 'params', "
                f"a list of params, or null"
            )
        if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
            raise ValueError(f"{path}: event '{event_name}' params must be a list of strings")
        events[event_name] = params

    metrics = data.get("metrics") or []
    if not isinstance(metrics, list) or not all(isinstance(m, str) for m in metrics):
        raise ValueError(f"{path}: 'metrics' must be a list of parameter names")

    display_names = data.get("display_names") or {}
    if not isinstance(display_names, dict):
        raise ValueError(f"{path}: 'display_names' must be a mapping")

    return EventsConfig(events=events, metrics=list(metrics), display_names=dict(display_names))
