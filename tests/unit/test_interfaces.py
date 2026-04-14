"""Unit tests for domain interfaces.

Tests verify that interfaces are abstract classes with required methods.
"""
import asyncio
from abc import ABC
from typing import AsyncIterator

import pytest

from app.domain.interfaces import (
    ITaskRepository,
    IMessageBus,
    IEventStore,
    IWorkflowRepo,
)
from app.domain.schemas import Task, EventMessage


class TestITaskRepository:
    """Tests for ITaskRepository interface."""

    def test_is_abstract_base_class(self):
        """Verify ITaskRepository is an abstract base class."""
        assert issubclass(ITaskRepository, ABC)
        # Should not be instantiable
        with pytest.raises(TypeError):
            ITaskRepository()

    def test_has_create_method(self):
        """Verify ITaskRepository has async create method."""
        assert hasattr(ITaskRepository, "create")
        method = getattr(ITaskRepository, "create")
        # Check it's marked as async
        assert asyncio.iscoroutinefunction(method)

    def test_has_get_method(self):
        """Verify ITaskRepository has async get method."""
        assert hasattr(ITaskRepository, "get")
        method = getattr(ITaskRepository, "get")
        assert asyncio.iscoroutinefunction(method)

    def test_has_update_status_method(self):
        """Verify ITaskRepository has async update_status method."""
        assert hasattr(ITaskRepository, "update_status")
        method = getattr(ITaskRepository, "update_status")
        assert asyncio.iscoroutinefunction(method)


class TestIMessageBus:
    """Tests for IMessageBus interface."""

    def test_is_abstract_base_class(self):
        """Verify IMessageBus is an abstract base class."""
        assert issubclass(IMessageBus, ABC)
        with pytest.raises(TypeError):
            IMessageBus()

    def test_has_publish_method(self):
        """Verify IMessageBus has async publish method."""
        assert hasattr(IMessageBus, "publish")
        method = getattr(IMessageBus, "publish")
        assert asyncio.iscoroutinefunction(method)

    def test_has_subscribe_method(self):
        """Verify IMessageBus has async subscribe method."""
        assert hasattr(IMessageBus, "subscribe")
        method = getattr(IMessageBus, "subscribe")
        assert asyncio.iscoroutinefunction(method)

    def test_has_register_listener_method(self):
        """Verify IMessageBus has register_listener method."""
        assert hasattr(IMessageBus, "register_listener")
        # This is a regular method, not async
        method = getattr(IMessageBus, "register_listener")
        assert not asyncio.iscoroutinefunction(method)

    def test_has_unregister_listener_method(self):
        """Verify IMessageBus has unregister_listener method."""
        assert hasattr(IMessageBus, "unregister_listener")
        method = getattr(IMessageBus, "unregister_listener")
        assert not asyncio.iscoroutinefunction(method)


class TestIEventStore:
    """Tests for IEventStore interface."""

    def test_is_abstract_base_class(self):
        """Verify IEventStore is an abstract base class."""
        assert issubclass(IEventStore, ABC)
        with pytest.raises(TypeError):
            IEventStore()

    def test_has_mark_consumed_method(self):
        """Verify IEventStore has async mark_consumed method."""
        assert hasattr(IEventStore, "mark_consumed")
        method = getattr(IEventStore, "mark_consumed")
        assert asyncio.iscoroutinefunction(method)

    def test_has_is_consumed_method(self):
        """Verify IEventStore has async is_consumed method."""
        assert hasattr(IEventStore, "is_consumed")
        method = getattr(IEventStore, "is_consumed")
        assert asyncio.iscoroutinefunction(method)


class TestIWorkflowRepo:
    """Tests for IWorkflowRepo interface."""

    def test_is_abstract_base_class(self):
        """Verify IWorkflowRepo is an abstract base class."""
        assert issubclass(IWorkflowRepo, ABC)
        with pytest.raises(TypeError):
            IWorkflowRepo()

    def test_has_get_active_method(self):
        """Verify IWorkflowRepo has async get_active method."""
        assert hasattr(IWorkflowRepo, "get_active")
        method = getattr(IWorkflowRepo, "get_active")
        assert asyncio.iscoroutinefunction(method)

    def test_has_get_by_version_method(self):
        """Verify IWorkflowRepo has async get_by_version method."""
        assert hasattr(IWorkflowRepo, "get_by_version")
        method = getattr(IWorkflowRepo, "get_by_version")
        assert asyncio.iscoroutinefunction(method)

    def test_has_save_version_method(self):
        """Verify IWorkflowRepo has async save_version method."""
        assert hasattr(IWorkflowRepo, "save_version")
        method = getattr(IWorkflowRepo, "save_version")
        assert asyncio.iscoroutinefunction(method)
