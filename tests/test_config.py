"""Configuration validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from internship_bot.config import AppConfig, load_config


def test_shipped_config_loads() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert config.require_india_eligibility
    assert config.email.recipient == "anugrahapaul26@gmail.com"
    assert "backend engineer" in config.target_roles


def test_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {"target_roles": ["backend"], "email": {"recipient": "user@example.com"}, "typo": 1}
        )
