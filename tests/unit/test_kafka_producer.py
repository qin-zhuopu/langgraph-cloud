"""Unit tests for Kafka producer utilities."""
import pytest

from app.infrastructure.kafka_producer import map_status_to_client, event_to_kafka_payload
from app.domain.schemas import EventMessage


class TestMapStatusToClient:
    """Tests for status mapping to client-expected values."""

    def test_awaiting_check_quotes(self):
        assert map_status_to_client("awaiting_check_quotes") == "awaiting_human_review"

    def test_awaiting_manager_audit(self):
        assert map_status_to_client("awaiting_manager_audit") == "awaiting_human_review"

    def test_any_awaiting_prefix(self):
        assert map_status_to_client("awaiting_anything") == "awaiting_human_review"

    def test_completed(self):
        assert map_status_to_client("completed") == "completed"

    def test_error(self):
        assert map_status_to_client("error") == "error"

    def test_interrupted(self):
        assert map_status_to_client("interrupted") == "awaiting_human_review"


class TestEventToKafkaPayload:
    """Tests for EventMessage → Kafka payload conversion."""

    def test_interrupt_event_has_callback_context(self):
        event = EventMessage(
            event_id="evt_001",
            task_id="task_001",
            task_type="inquiry",
            status="interrupted",
            node_id="check_quotes",
            required_params=["new_deadline", "supplier_codes"],
            display_data={"display_name": "报价检查点"},
        )
        payload = event_to_kafka_payload(event)

        assert payload["header"]["event_id"] == "evt_001"
        assert payload["header"]["thread_id"] == "task_001"
        assert payload["header"]["status"] == "awaiting_human_review"
        assert isinstance(payload["header"]["timestamp"], int)
        assert payload["result"] == {"display_name": "报价检查点"}
        assert payload["callback_context"]["node_id"] == "check_quotes"
        assert payload["callback_context"]["required_params"] == ["new_deadline", "supplier_codes"]

    def test_completed_event_no_callback_context(self):
        event = EventMessage(
            event_id="evt_002",
            task_id="task_001",
            task_type="inquiry",
            status="completed",
            node_id="",
            required_params=[],
            display_data={},
        )
        payload = event_to_kafka_payload(event)

        assert payload["header"]["status"] == "completed"
        assert "callback_context" not in payload

    def test_awaiting_status_has_callback_context(self):
        event = EventMessage(
            event_id="evt_003",
            task_id="task_002",
            task_type="inquiry",
            status="awaiting_check_quotes",
            node_id="check_quotes",
            required_params=["winners"],
            display_data={},
        )
        payload = event_to_kafka_payload(event)

        assert payload["header"]["status"] == "awaiting_human_review"
        assert payload["callback_context"]["node_id"] == "check_quotes"
