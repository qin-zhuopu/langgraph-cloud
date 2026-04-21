"""Async Kafka producer for publishing workflow events.

This module provides a thin wrapper around aiokafka that converts
internal EventMessage objects into the Kafka payload format expected
by the JerehPilot client.
"""
import json
import time
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaProducer

from app.domain.schemas import EventMessage


def map_status_to_client(status: str) -> str:
    """Map internal workflow status to client-expected status.

    The JerehPilot client only recognises three statuses:
    - awaiting_human_review
    - completed
    - error

    All ``awaiting_*`` statuses are collapsed to ``awaiting_human_review``.
    """
    if status.startswith("awaiting_"):
        return "awaiting_human_review"
    if status in ("completed", "error"):
        return status
    # interrupted is the raw executor status before _derive_status
    if status == "interrupted":
        return "awaiting_human_review"
    return status


def event_to_kafka_payload(event: EventMessage) -> Dict[str, Any]:
    """Convert an internal EventMessage to the Kafka payload format.

    The format matches what the JerehPilot client expects::

        {
          "header": { "event_id", "thread_id", "status", "timestamp" },
          "result": { ... display_data ... },
          "callback_context": { ... } | null
        }
    """
    payload: Dict[str, Any] = {
        "header": {
            "event_id": event.event_id,
            "thread_id": event.task_id,
            "status": map_status_to_client(event.status),
            "timestamp": int(time.time()),
        },
        "result": event.display_data,
    }

    # Only include callback_context for interrupt messages
    if event.status == "interrupted" or event.status.startswith("awaiting_"):
        payload["callback_context"] = {
            "required_action": "human_decision",
            "node_id": event.node_id,
            "required_params": event.required_params,
        }

    return payload


class KafkaEventProducer:
    """Async Kafka producer for workflow events.

    Usage::

        producer = KafkaEventProducer()
        await producer.start(["kafka01:9092"])
        await producer.send("my_topic", event)
        await producer.stop()
    """

    def __init__(self) -> None:
        self._producer: Optional[AIOKafkaProducer] = None

    async def start(self, brokers: list[str]) -> None:
        """Connect to Kafka brokers."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=",".join(brokers),
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._producer.start()

    async def send(self, topic: str, event: EventMessage) -> None:
        """Publish an EventMessage to a Kafka topic.

        The message key is set to ``event.task_id`` (== thread_id).
        """
        if self._producer is None:
            return
        payload = event_to_kafka_payload(event)
        await self._producer.send_and_wait(
            topic,
            value=payload,
            key=event.task_id,
        )

    async def stop(self) -> None:
        """Disconnect from Kafka."""
        if self._producer:
            await self._producer.stop()
            self._producer = None

    @property
    def is_started(self) -> bool:
        return self._producer is not None
