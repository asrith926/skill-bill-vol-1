"""Tests for API key management."""
import json
import pytest
from pathlib import Path
from web.services.api_keys import load_api_key, save_api_key, clear_api_key


class TestApiKeyStorage:
    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-ant-test-123", config_path)
        provider, key = load_api_key(config_path)
        assert provider == "anthropic"
        assert key == "sk-ant-test-123"

    def test_load_missing_file(self, tmp_path):
        config_path = tmp_path / ".config.json"
        provider, key = load_api_key(config_path)
        assert provider == ""
        assert key == ""

    def test_clear(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-test", config_path)
        clear_api_key(config_path)
        provider, key = load_api_key(config_path)
        assert provider == ""
        assert key == ""

    def test_overwrite_existing(self, tmp_path):
        config_path = tmp_path / ".config.json"
        save_api_key("anthropic", "sk-old", config_path)
        save_api_key("anthropic", "sk-new", config_path)
        _, key = load_api_key(config_path)
        assert key == "sk-new"
