"""Unit tests for WorkflowBuilder."""
import pytest
from typing import TypedDict
from langgraph.graph import StateGraph, END

from app.workflow.builder import WorkflowBuilder


class MockState(TypedDict):
    """Mock state type for testing."""
    input: str
    is_approved: bool
    audit_opinion: str


class TestWorkflowBuilder:
    """Tests for WorkflowBuilder implementation."""

    def test_build_workflow_from_config(self):
        """Test building a workflow graph from configuration dict."""
        config = {
            "name": "test_workflow",
            "display_name": "Test Workflow",
            "nodes": [
                {
                    "id": "start",
                    "type": "action",
                    "display_name": "Start Node",
                    "description": "Beginning of workflow",
                    "target_node": "middle"
                },
                {
                    "id": "middle",
                    "type": "action",
                    "display_name": "Middle Node",
                    "description": "Middle of workflow",
                    "target_node": "end"
                },
                {
                    "id": "end",
                    "type": "terminal",
                    "display_name": "End Node",
                    "description": "End of workflow",
                    "status": "completed"
                }
            ]
        }

        graph = WorkflowBuilder.build(config, version="v1")
        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_build_workflow_with_interrupt_nodes(self):
        """Test building a workflow with interrupt nodes."""
        config = {
            "name": "approval_workflow",
            "display_name": "Approval Workflow",
            "nodes": [
                {
                    "id": "submit",
                    "type": "action",
                    "display_name": "Submit Request",
                    "description": "User submits request",
                    "target_node": "review"
                },
                {
                    "id": "review",
                    "type": "interrupt",
                    "display_name": "Manager Review",
                    "description": "Manager reviews request",
                    "transitions": [
                        {
                            "action": "approve",
                            "label": "Approve",
                            "target_node": "approved",
                            "condition": "is_approved == true",
                            "form_schema": {
                                "type": "object",
                                "required": ["is_approved", "audit_opinion"],
                                "properties": {
                                    "is_approved": {"type": "boolean", "const": True},
                                    "audit_opinion": {"type": "string"},
                                }
                            }
                        },
                        {
                            "action": "reject",
                            "label": "Reject",
                            "target_node": "rejected",
                            "condition": "is_approved == false",
                            "form_schema": {
                                "type": "object",
                                "required": ["is_approved", "audit_opinion"],
                                "properties": {
                                    "is_approved": {"type": "boolean", "const": False},
                                    "audit_opinion": {"type": "string"},
                                }
                            }
                        }
                    ]
                },
                {
                    "id": "approved",
                    "type": "terminal",
                    "display_name": "Approved",
                    "description": "Request approved",
                    "status": "completed"
                },
                {
                    "id": "rejected",
                    "type": "terminal",
                    "display_name": "Rejected",
                    "description": "Request rejected",
                    "status": "rejected"
                }
            ]
        }

        graph = WorkflowBuilder.build(config, version="v1")
        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_load_workflow_config(self):
        """Test loading workflow configuration from YAML file."""
        config = WorkflowBuilder.load_config("purchase_request")

        assert config is not None
        assert config["name"] == "purchase_request"
        assert "nodes" in config
        assert len(config["nodes"]) == 5

        node_types = {node["type"] for node in config["nodes"]}
        assert "action" in node_types
        assert "interrupt" in node_types
        assert "terminal" in node_types

        manager_audit = next(n for n in config["nodes"] if n["id"] == "manager_audit")
        assert manager_audit["type"] == "interrupt"
        assert "transitions" in manager_audit
        assert len(manager_audit["transitions"]) == 2
        # Verify new fields
        assert manager_audit["transitions"][0]["action"] == "approve"
        assert "form_schema" in manager_audit["transitions"][0]

    def test_build_workflow_with_conditional_expressions(self):
        """Test building workflow with conditional expression parsing."""
        config = {
            "name": "conditional_workflow",
            "display_name": "Conditional Workflow",
            "nodes": [
                {
                    "id": "start",
                    "type": "action",
                    "display_name": "Start",
                    "description": "Start node",
                    "target_node": "decision"
                },
                {
                    "id": "decision",
                    "type": "interrupt",
                    "display_name": "Decision",
                    "description": "Decision point",
                    "transitions": [
                        {
                            "action": "yes",
                            "label": "Yes",
                            "target_node": "yes",
                            "condition": "{{ is_approved == true }}",
                            "form_schema": {"type": "object", "required": ["is_approved"]}
                        },
                        {
                            "action": "no",
                            "label": "No",
                            "target_node": "no",
                            "condition": "{{ is_approved == false }}",
                            "form_schema": {"type": "object", "required": ["is_approved"]}
                        }
                    ]
                },
                {
                    "id": "yes",
                    "type": "terminal",
                    "display_name": "Yes",
                    "description": "Approved path",
                    "status": "completed"
                },
                {
                    "id": "no",
                    "type": "terminal",
                    "display_name": "No",
                    "description": "Rejected path",
                    "status": "rejected"
                }
            ]
        }

        graph = WorkflowBuilder.build(config, version="v1")
        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_build_workflow_sets_entry_point(self):
        """Test that workflow builder sets entry point to first node."""
        config = {
            "name": "entry_point_test",
            "display_name": "Entry Point Test",
            "nodes": [
                {
                    "id": "first_node",
                    "type": "action",
                    "display_name": "First Node",
                    "description": "Should be entry point",
                    "target_node": "second_node"
                },
                {
                    "id": "second_node",
                    "type": "terminal",
                    "display_name": "Second Node",
                    "description": "Second node",
                    "status": "completed"
                }
            ]
        }

        graph = WorkflowBuilder.build(config, version="v1")
        compiled = graph.compile()
        assert compiled is not None
