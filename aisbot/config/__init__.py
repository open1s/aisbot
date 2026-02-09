"""Configuration module for aisbot."""

from aisbot.config.loader import load_config, get_config_path
from aisbot.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
