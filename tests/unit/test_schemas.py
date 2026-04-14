"""Unit tests for domain Pydantic schemas."""
import pytest
from datetime import datetime
from pydantic import ValidationError

from app.domain.schemas import (
    TaskData,
    TaskCreate,
    Task,
    EventMessage,
    CallbackRequest,
    TaskResponse,
    CallbackResponse,
    ErrorResponse,
)


class TestTaskData:
    """Tests for TaskData schema."""

    def test_task_data_valid(self):
        """Test creating a valid TaskData."""
        task_data = TaskData(type="test_workflow", data={"key": "value"})
        assert task_data.type == "test_workflow"
        assert task_data.data == {"key": "value"}

    def test_task_data_missing_type(self):
        """Test TaskData validation fails when type is missing."""
        with pytest.raises(ValidationError) as exc_info:
            TaskData(data={"key": "value"})
        assert "type" in str(exc_info.value).lower()


class TestTaskCreate:
    """Tests for TaskCreate schema."""

    def test_task_create_valid(self):
        """Test creating a valid TaskCreate."""
        task_data = TaskData(type="workflow1")
        task_create = TaskCreate(user_id="user123", task=task_data)
        assert task_create.user_id == "user123"
        assert task_create.task.type == "workflow1"


class TestTask:
    """Tests for Task schema."""

    def test_task_valid(self):
        """Test creating a valid Task."""
        now = datetime.now()
        task = Task(
            id="task1",
            user_id="user123",
            type="workflow1",
            status="pending",
            data={"key": "value"},
            created_at=now,
            updated_at=now,
        )
        assert task.id == "task1"
        assert task.user_id == "user123"
        assert task.type == "workflow1"
        assert task.workflow_version == "v1"  # default value
        assert task.status == "pending"
        assert task.data == {"key": "value"}


class TestEventMessage:
    """Tests for EventMessage schema."""

    def test_event_message_valid(self):
        """Test creating a valid EventMessage."""
        event = EventMessage(
            event_id="event1",
            task_id="task1",
            task_type="workflow1",
            status="waiting_input",
            node_id="node1",
            required_params=["param1"],
            display_data={"title": "Please input"},
        )
        assert event.event_id == "event1"
        assert event.task_id == "task1"
        assert event.task_type == "workflow1"
        assert event.status == "waiting_input"
        assert event.node_id == "node1"
        assert event.required_params == ["param1"]
        assert event.display_data == {"title": "Please input"}


class TestCallbackRequest:
    """Tests for CallbackRequest schema."""

    def test_callback_request_valid(self):
        """Test creating a valid CallbackRequest."""
        request = CallbackRequest(
            event_id="event1",
            node_id="node1",
            user_input={"param1": "value1"},
        )
        assert request.event_id == "event1"
        assert request.node_id == "node1"
        assert request.user_input == {"param1": "value1"}

    def test_callback_request_missing_event_id(self):
        """Test CallbackRequest validation fails when event_id is missing."""
        with pytest.raises(ValidationError) as exc_info:
            CallbackRequest(node_id="node1", user_input={"param1": "value1"})
        assert "event_id" in str(exc_info.value).lower()

    def test_callback_request_missing_user_input(self):
        """Test CallbackRequest validation fails when user_input is missing."""
        with pytest.raises(ValidationError) as exc_info:
            CallbackRequest(event_id="event1", node_id="node1")
        assert "user_input" in str(exc_info.value).lower()


class TestTaskResponse:
    """Tests for TaskResponse schema."""

    def test_task_response_valid(self):
        """Test creating a valid TaskResponse."""
        now = datetime.now()
        task = Task(
            id="task1",
            user_id="user123",
            type="workflow1",
            status="pending",
            data={},
            created_at=now,
            updated_at=now,
        )
        response = TaskResponse(task=task)
        assert response.task.id == "task1"
        assert response.task.type == "workflow1"


class TestCallbackResponse:
    """Tests for CallbackResponse schema."""

    def test_callback_response_valid(self):
        """Test creating a valid CallbackResponse."""
        response = CallbackResponse(success=True, next_status="processing")
        assert response.success is True
        assert response.next_status == "processing"


class TestErrorResponse:
    """Tests for ErrorResponse schema."""

    def test_error_response_valid(self):
        """Test creating a valid ErrorResponse."""
        error = ErrorResponse(
            error={"code": "VALIDATION_ERROR", "message": "Invalid input", "details": {}}
        )
        assert error.error["code"] == "VALIDATION_ERROR"
        assert error.error["message"] == "Invalid input"
