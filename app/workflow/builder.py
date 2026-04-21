"""Workflow builder for constructing LangGraph graphs from YAML configuration."""

import re
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import StateGraph, END

from app.workflow.config import load_workflow_config


class WorkflowBuilder:
    """
    Builds LangGraph StateGraph instances from workflow YAML configurations.

    This class handles:
    - Loading workflow configurations from YAML files
    - Creating nodes for different types (action, interrupt, terminal)
    - Building edges between nodes (direct and conditional)
    - Setting entry points
    """

    @staticmethod
    def load_config(workflow_name: str) -> Dict[str, Any]:
        """
        Load workflow configuration from YAML file.

        Args:
            workflow_name: Name of the workflow to load (without .yml extension)

        Returns:
            Dict containing the workflow configuration

        Raises:
            FileNotFoundError: If the workflow configuration file does not exist
        """
        return load_workflow_config(workflow_name)

    @staticmethod
    def build(config: Dict[str, Any], version: str) -> StateGraph:
        """
        Build a LangGraph StateGraph from workflow configuration.

        The returned StateGraph is *not* compiled yet. Call
        ``WorkflowBuilder.compile(graph, config)`` to get a runnable graph
        with interrupt support and an optional checkpointer.

        Args:
            config: Workflow configuration dictionary
            version: Version identifier for the workflow

        Returns:
            Un-compiled StateGraph instance.
        """
        from typing import TypedDict

        # Define a simple state schema
        class WorkflowState(TypedDict):
            """State schema for workflow execution."""
            input: Any
            action: Optional[str]
            is_approved: Optional[bool]
            audit_opinion: Optional[str]
            approver: Optional[str]

        # Create the StateGraph
        graph = StateGraph(WorkflowState)

        # Build a mapping of node IDs to their configurations
        nodes_by_id = {node["id"]: node for node in config["nodes"]}

        # Add all nodes to the graph
        for node in config["nodes"]:
            WorkflowBuilder._add_node(graph, node)

        # Set entry point to first node
        first_node = config["nodes"][0]["id"]
        graph.set_entry_point(first_node)

        # Add edges between nodes
        for node in config["nodes"]:
            WorkflowBuilder._add_edges(graph, node, nodes_by_id)

        return graph

    @staticmethod
    def get_interrupt_node_ids(config: Dict[str, Any]) -> List[str]:
        """Return the IDs of all interrupt-type nodes in the config.

        Args:
            config: Workflow configuration dictionary.

        Returns:
            List of node IDs whose type is ``interrupt``.
        """
        return [
            node["id"]
            for node in config.get("nodes", [])
            if node.get("type") == "interrupt"
        ]

    @staticmethod
    def get_node_config(config: Dict[str, Any], node_id: str) -> Optional[Dict[str, Any]]:
        """Return the configuration dict for a specific node.

        Args:
            config: Workflow configuration dictionary.
            node_id: The node identifier.

        Returns:
            The node configuration dict, or None if not found.
        """
        for node in config.get("nodes", []):
            if node["id"] == node_id:
                return node
        return None

    @staticmethod
    def _add_node(graph: StateGraph, node: Dict[str, Any]) -> None:
        """
        Add a node to the graph.

        Args:
            graph: The StateGraph instance
            node: Node configuration dictionary
        """
        node_id = node["id"]
        node_type = node["type"]

        # Create node function based on type
        if node_type == "action":
            node_fn = WorkflowBuilder._create_action_node(node)
        elif node_type == "interrupt":
            node_fn = WorkflowBuilder._create_interrupt_node(node)
        elif node_type == "terminal":
            node_fn = WorkflowBuilder._create_terminal_node(node)
        else:
            raise ValueError(f"Unknown node type: {node_type}")

        graph.add_node(node_id, node_fn)

    @staticmethod
    def _create_action_node(node: Dict[str, Any]) -> Callable:
        """Create an action node function."""
        def action_node(state: Dict[str, Any]) -> Dict[str, Any]:
            """Action node that processes input and returns updated state."""
            # Simple pass-through for action nodes
            # In production, this would execute the action logic
            return state
        return action_node

    @staticmethod
    def _create_interrupt_node(node: Dict[str, Any]) -> Callable:
        """Create an interrupt node function."""
        def interrupt_node(state: Dict[str, Any]) -> Dict[str, Any]:
            """Interrupt node that waits for human input."""
            # Mark that we're waiting for human input
            # The actual interrupt handling happens at runtime
            return state
        return interrupt_node

    @staticmethod
    def _create_terminal_node(node: Dict[str, Any]) -> Callable:
        """Create a terminal node function."""
        status = node.get("status", "completed")

        def terminal_node(state: Dict[str, Any]) -> Dict[str, Any]:
            """Terminal node that marks workflow completion."""
            result = state.copy()
            result["status"] = status
            return result
        return terminal_node

    @staticmethod
    def _add_edges(
        graph: StateGraph,
        node: Dict[str, Any],
        nodes_by_id: Dict[str, Dict[str, Any]]
    ) -> None:
        """
        Add edges from a node to its successors.

        Args:
            graph: The StateGraph instance
            node: Source node configuration
            nodes_by_id: Mapping of all node IDs to their configurations
        """
        node_id = node["id"]
        node_type = node["type"]

        # Handle transitions for interrupt nodes
        if node_type == "interrupt" and "transitions" in node:
            transitions = node["transitions"]

            if len(transitions) == 1:
                # Single transition - use direct edge
                next_node = transitions[0]["target_node"]
                if WorkflowBuilder._is_terminal_node(nodes_by_id.get(next_node, {})):
                    graph.add_edge(node_id, END)
                else:
                    graph.add_edge(node_id, next_node)
            else:
                # Multiple transitions - use conditional edges
                def route_function(state: Dict[str, Any]) -> str:
                    """Route to next node based on state."""
                    for transition in transitions:
                        condition = transition.get("condition", "")
                        if WorkflowBuilder._evaluate_condition(condition, state):
                            return transition["target_node"]
                    # Default to first transition if no condition matches
                    return transitions[0]["target_node"]

                # Build path map for conditional edges
                path_map = {}
                for transition in transitions:
                    next_node = transition["target_node"]
                    if WorkflowBuilder._is_terminal_node(nodes_by_id.get(next_node, {})):
                        path_map[next_node] = END
                    else:
                        path_map[next_node] = next_node

                graph.add_conditional_edges(
                    node_id,
                    route_function,
                    path_map
                )

        # Handle direct 'target_node' for action nodes
        elif "target_node" in node:
            next_node = node["target_node"]
            if WorkflowBuilder._is_terminal_node(nodes_by_id.get(next_node, {})):
                graph.add_edge(node_id, END)
            else:
                graph.add_edge(node_id, next_node)

    @staticmethod
    def _is_terminal_node(node: Dict[str, Any]) -> bool:
        """Check if a node is a terminal node."""
        return node.get("type") == "terminal"

    @staticmethod
    def _evaluate_condition(condition: str, state: Dict[str, Any]) -> bool:
        """
        Evaluate a conditional expression against the state.

        Args:
            condition: Condition string (e.g., "is_approved == true" or "{{ is_approved == true }}")
            state: Current state dictionary

        Returns:
            True if condition evaluates to True, False otherwise
        """
        # Remove template braces if present
        condition = condition.strip()
        if condition.startswith("{{") and condition.endswith("}}"):
            condition = condition[2:-2].strip()

        # Simple evaluation for common conditions
        # Parse conditions like "is_approved == true"
        match = re.match(r'(\w+)\s*==\s*(true|false|\d+|"[^"]*")', condition)
        if match:
            var_name = match.group(1)
            value_str = match.group(2)

            if var_name in state:
                state_value = state[var_name]

                # Handle boolean values
                if value_str == "true":
                    return state_value is True
                elif value_str == "false":
                    return state_value is False
                # Handle numeric values
                elif value_str.isdigit():
                    return state_value == int(value_str)
                # Handle string values
                elif value_str.startswith('"') and value_str.endswith('"'):
                    return str(state_value) == value_str[1:-1]

        # Default to False for complex conditions
        # In production, this would use a safer expression evaluator
        return False
