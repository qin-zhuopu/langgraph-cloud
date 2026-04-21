"""Unit tests for application configuration."""
import os
import pytest

from app.config import load_config, AppConfig


class TestLoadConfig:
    """Tests for load_config from environment variables."""

    def test_defaults(self, monkeypatch):
        """Default config has no Kafka brokers."""
        monkeypatch.delenv("KAFKA_BROKERS", raising=False)
        monkeypatch.delenv("KAFKA_TOPIC", raising=False)
        monkeypatch.delenv("DB_PATH", raising=False)

        config = load_config()
        assert config.kafka_brokers == []
        assert config.kafka_topic == "financial_audit_notify"
        assert config.db_path == "langgraph_cloud.db"

    def test_kafka_brokers_from_env(self, monkeypatch):
        """Kafka brokers parsed from comma-separated env var."""
        monkeypatch.setenv("KAFKA_BROKERS", "broker1:9092,broker2:9092,broker3:9092")

        config = load_config()
        assert config.kafka_brokers == ["broker1:9092", "broker2:9092", "broker3:9092"]

    def test_kafka_brokers_empty_string(self, monkeypatch):
        """Empty KAFKA_BROKERS results in empty list."""
        monkeypatch.setenv("KAFKA_BROKERS", "")

        config = load_config()
        assert config.kafka_brokers == []

    def test_custom_topic(self, monkeypatch):
        monkeypatch.setenv("KAFKA_TOPIC", "my_custom_topic")

        config = load_config()
        assert config.kafka_topic == "my_custom_topic"

    def test_custom_port(self, monkeypatch):
        monkeypatch.setenv("PORT", "8888")

        config = load_config()
        assert config.port == 8888
