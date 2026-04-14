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
        # Arrange - Simple linear workflow
        config = {
            "name": "test_workflow",
            "display_name": "Test Workflow",
            "nodes": [
                {
                    "id": "start",
                    "type": "action",
                    "display_name": "Start Node",
                    "description": "Beginning of workflow",
                    "next": "middle"
                },
                {
                    "id": "middle",
                    "type": "action",
                    "display_name": "Middle Node",
                    "description": "Middle of workflow",
                    "next": "end"
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

        # Act - Build the workflow
        graph = WorkflowBuilder.build(config, version="v1")

        # Assert - Verify graph is a StateGraph
        assert isinstance(graph, StateGraph)

        # Assert - Verify graph structure by compiling
        compiled = graph.compile()
        assert compiled is not None

    def test_build_workflow_with_interrupt_nodes(self):
        """Test building a workflow with interrupt nodes."""
        # Arrange - Workflow with interrupt nodes and conditional edges
        config = {
            "name": "approval_workflow",
            "display_name": "Approval Workflow",
            "nodes": [
                {
                    "id": "submit",
                    "type": "action",
                    "display_name": "Submit Request",
                    "description": "User submits request",
                    "next": "review"
                },
                {
                    "id": "review",
                    "type": "interrupt",
                    "display_name": "Manager Review",
                    "description": "Manager reviews request",
                    "required_params": ["is_approved", "audit_opinion"],
                    "transitions": [
                        {"condition": "is_approved == true", "next": "approved"},
                        {"condition": "is_approved == false", "next": "rejected"}
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

        # Act - Build the workflow
        graph = WorkflowBuilder.build(config, version="v1")

        # Assert - Verify graph structure
        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_load_workflow_config(self):
        """Test loading workflow configuration from YAML file."""
        # Act - Load the purchase_request workflow config
        config = WorkflowBuilder.load_config("purchase_request")

        # Assert - Verify config structure
        assert config is not None
        assert config["name"] == "purchase_request"
        assert "nodes" in config
        assert len(config["nodes"]) == 5

        # Verify node types
        node_types = {node["type"] for node in config["nodes"]}
        assert "action" in node_types
        assert "interrupt" in node_types
        assert "terminal" in node_types

        # Verify interrupt node has transitions
        manager_audit = next(n for n in config["nodes"] if n["id"] == "manager_audit")
        assert manager_audit["type"] == "interrupt"
        assert "transitions" in manager_audit
        assert len(manager_audit["transitions"]) == 2

    def test_build_workflow_with_conditional_expressions(self):
        """Test building workflow with conditional expression parsing."""
        # Arrange - Workflow with conditional expressions
        config = {
            "name": "conditional_workflow",
            "display_name": "Conditional Workflow",
            "nodes": [
                {
                    "id": "start",
                    "type": "action",
                    "display_name": "Start",
                    "description": "Start node",
                    "next": "decision"
                },
                {
                    "id": "decision",
                    "type": "interrupt",
                    "display_name": "Decision",
                    "description": "Decision point",
                    "required_params": ["is_approved"],
                    "transitions": [
                        {"condition": "{{ is_approved == true }}", "next": "yes"},
                        {"condition": "{{ is_approved == false }}", "next": "no"}
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

        # Act - Build the workflow
        graph = WorkflowBuilder.build(config, version="v1")

        # Assert - Verify graph was built successfully
        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_build_workflow_sets_entry_point(self):
        """Test that workflow builder sets entry point to first node."""
        # Arrange
        config = {
            "name": "entry_point_test",
            "display_name": "Entry Point Test",
            "nodes": [
                {
                    "id": "first_node",
                    "type": "action",
                    "display_name": "First Node",
                    "description": "Should be entry point",
                    "next": "second_node"
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

        # Act - Build the workflow
        graph = WorkflowBuilder.build(config, version="v1")

        # Assert - Graph should be compilable with entry point set
        compiled = graph.compile()
        assert compiled is not None
