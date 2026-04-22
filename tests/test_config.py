"""Config parser tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from gtm_ga4_sync.config import load_config


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "events.yml"
    p.write_text(content)
    return p


def test_minimal_config(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  cta_click:
    params: [cta_name]
"""))
    assert cfg.events == {"cta_click": ["cta_name"]}
    assert cfg.metrics == []
    assert cfg.all_params == ["cta_name"]
    assert cfg.dimension_params() == ["cta_name"]


def test_metrics_excluded_from_dimensions(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  search:
    params: [search_term, results_count]
metrics:
  - results_count
"""))
    assert cfg.dimension_params() == ["search_term"]
    assert cfg.metrics == ["results_count"]


def test_params_deduplicated_across_events(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  cta_click:
    params: [cta_name, cta_location]
  nav_click:
    params: [cta_name, nav_item]
"""))
    # First-seen order preserved, no duplicates
    assert cfg.all_params == ["cta_name", "cta_location", "nav_item"]


def test_empty_params_allowed(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  chat_opened:
    params: []
  heartbeat:
"""))
    assert cfg.events == {"chat_opened": [], "heartbeat": []}


def test_display_name_default_is_title_case(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  x:
    params: [some_snake_case_name]
"""))
    assert cfg.display_name("some_snake_case_name") == "Some Snake Case Name"


def test_display_name_override(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, """
events:
  x:
    params: [cta_name]
display_names:
  cta_name: "CTA Name"
"""))
    assert cfg.display_name("cta_name") == "CTA Name"


def test_missing_events_key_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="events"):
        load_config(_write(tmp_path, "other: stuff\n"))


def test_invalid_params_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="params"):
        load_config(_write(tmp_path, """
events:
  bad_event:
    params: [123, "ok"]
"""))


def test_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yml")


def test_example_config_parses() -> None:
    """The shipped events.example.yml must always parse."""
    example = Path(__file__).parent.parent / "events.example.yml"
    cfg = load_config(example)
    assert len(cfg.events) >= 5
    assert "virtual_page_view" in cfg.events
    assert "cta_click" in cfg.events
    assert cfg.metrics, "example should demonstrate at least one metric"
