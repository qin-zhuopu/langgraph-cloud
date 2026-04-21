"""Application configuration loaded from environment variables."""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppConfig:
    """Application configuration.

    Kafka is optional — if kafka_brokers is empty, Kafka publishing is disabled
    and the system falls back to SQLite MessageBus only.
    """

    db_path: str = "langgraph_cloud.db"
    kafka_brokers: list[str] = field(default_factory=list)
    kafka_topic: str = "financial_audit_notify"
    host: str = "127.0.0.1"
    port: int = 9999


def load_config() -> AppConfig:
    """Load configuration from environment variables.

    Environment variables:
        DB_PATH: SQLite database path (default: langgraph_cloud.db)
        KAFKA_BROKERS: Comma-separated broker list (default: empty = disabled)
        KAFKA_TOPIC: Kafka topic name (default: financial_audit_notify)
        HOST: Server bind host (default: 127.0.0.1)
        PORT: Server bind port (default: 9999)
    """
    brokers_str = os.environ.get("KAFKA_BROKERS", "")
    brokers = [b.strip() for b in brokers_str.split(",") if b.strip()] if brokers_str else []

    return AppConfig(
        db_path=os.environ.get("DB_PATH", "langgraph_cloud.db"),
        kafka_brokers=brokers,
        kafka_topic=os.environ.get("KAFKA_TOPIC", "financial_audit_notify"),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "9999")),
    )
