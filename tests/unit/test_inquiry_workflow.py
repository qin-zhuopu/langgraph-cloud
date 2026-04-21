"""Unit tests for inquiry workflow graph structure, condition routing, and form_schema."""
import pytest
from langgraph.graph import StateGraph

from app.workflow.builder import WorkflowBuilder


class TestInquiryWorkflowBuild:
    """Tests for building the inquiry workflow graph."""

    def test_load_inquiry_config(self):
        """Test loading inquiry YAML config."""
        config = WorkflowBuilder.load_config("inquiry")

        assert config is not None
        assert config["name"] == "inquiry"
        assert len(config["nodes"]) == 5

    def test_build_inquiry_graph(self):
        """Test building inquiry workflow produces a valid StateGraph."""
        config = WorkflowBuilder.load_config("inquiry")
        graph = WorkflowBuilder.build(config, version="v1")

        assert isinstance(graph, StateGraph)
        compiled = graph.compile()
        assert compiled is not None

    def test_node_types(self):
        """Test inquiry workflow has correct node types."""
        config = WorkflowBuilder.load_config("inquiry")
        node_types = {node["id"]: node["type"] for node in config["nodes"]}

        assert node_types["create_inquiry"] == "action"
        assert node_types["send_inquiry"] == "action"
        assert node_types["check_quotes"] == "interrupt"
        assert node_types["push_to_erp"] == "action"
        assert node_types["completed"] == "terminal"

    def test_interrupt_node_has_two_branches(self):
        """Test check_quotes interrupt node has exactly 2 transitions."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )

        assert check_quotes["type"] == "interrupt"
        assert len(check_quotes["transitions"]) == 2

    def test_branches_have_form_schema(self):
        """Test each branch transition includes a form_schema."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )

        for transition in check_quotes["transitions"]:
            assert "form_schema" in transition
            assert "action" in transition
            assert "label" in transition
            assert "target_node" in transition
            assert "condition" in transition

    def test_branch_targets(self):
        """Test branch target nodes are correct."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        targets = {t["action"]: t["target_node"] for t in check_quotes["transitions"]}

        assert targets["new_round"] == "send_inquiry"
        assert targets["award"] == "push_to_erp"

    def test_interrupt_node_ids(self):
        """Test get_interrupt_node_ids returns check_quotes."""
        config = WorkflowBuilder.load_config("inquiry")
        interrupt_ids = WorkflowBuilder.get_interrupt_node_ids(config)

        assert interrupt_ids == ["check_quotes"]

    # --- Condition routing ---

    def test_condition_routing_new_round(self):
        """Test action=='new_round' evaluates to True."""
        result = WorkflowBuilder._evaluate_condition(
            'action == "new_round"', {"action": "new_round"}
        )
        assert result is True

    def test_condition_routing_award(self):
        """Test action=='award' evaluates to True."""
        result = WorkflowBuilder._evaluate_condition(
            'action == "award"', {"action": "award"}
        )
        assert result is True

    def test_condition_routing_unknown_action(self):
        """Test unknown action defaults to False."""
        result = WorkflowBuilder._evaluate_condition(
            'action == "new_round"', {"action": "unknown"}
        )
        assert result is False


class TestInquiryFormSchema:
    """Tests for interrupt node form_schema correctness."""

    def test_new_round_schema_requires_deadline_and_suppliers(self):
        """Test new_round form_schema requires new_deadline and supplier_codes."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        new_round = next(t for t in check_quotes["transitions"] if t["action"] == "new_round")
        schema = new_round["form_schema"]

        assert "new_deadline" in schema["required"]
        assert "supplier_codes" in schema["required"]

    def test_award_schema_requires_winners(self):
        """Test award form_schema requires winners."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        award = next(t for t in check_quotes["transitions"] if t["action"] == "award")
        schema = award["form_schema"]

        assert "winners" in schema["required"]

    def test_award_winners_schema_structure(self):
        """Test award winners requires material_code, supplier_code, awarded_price."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        award = next(t for t in check_quotes["transitions"] if t["action"] == "award")
        winner_schema = award["form_schema"]["properties"]["winners"]["items"]

        assert "material_code" in winner_schema["required"]
        assert "supplier_code" in winner_schema["required"]
        assert "awarded_price" in winner_schema["required"]

    def test_validate_new_round_with_valid_data(self):
        """Test new_round form accepts valid data."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        new_round = next(t for t in check_quotes["transitions"] if t["action"] == "new_round")

        valid_data = {
            "new_deadline": "2026-05-15T18:00:00",
            "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN", "SUP_SHIYI", "SUP_TONGZHOU"],
        }
        jsonschema.validate(valid_data, new_round["form_schema"])

    def test_validate_new_round_missing_supplier_codes(self):
        """Test new_round form rejects missing supplier_codes."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        new_round = next(t for t in check_quotes["transitions"] if t["action"] == "new_round")

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"new_deadline": "2026-05-15T18:00:00"}, new_round["form_schema"])

    def test_validate_new_round_empty_supplier_codes(self):
        """Test new_round form rejects empty supplier_codes array."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        new_round = next(t for t in check_quotes["transitions"] if t["action"] == "new_round")

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"new_deadline": "2026-05-15T18:00:00", "supplier_codes": []},
                new_round["form_schema"],
            )

    def test_validate_award_with_valid_data(self):
        """Test award form accepts valid data."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        award = next(t for t in check_quotes["transitions"] if t["action"] == "award")

        valid_data = {
            "winners": [
                {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                {"material_code": "C050086211", "supplier_code": "SUP_DEXIN", "awarded_price": 2200.0},
                {"material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.0},
            ]
        }
        jsonschema.validate(valid_data, award["form_schema"])

    def test_validate_award_missing_winners(self):
        """Test award form rejects missing winners."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        award = next(t for t in check_quotes["transitions"] if t["action"] == "award")

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, award["form_schema"])

    def test_validate_award_winner_missing_price(self):
        """Test award form rejects winner without awarded_price."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(n for n in config["nodes"] if n["id"] == "check_quotes")
        award = next(t for t in check_quotes["transitions"] if t["action"] == "award")

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"winners": [{"material_code": "C050066547", "supplier_code": "SUP_JINGLIN"}]},
                award["form_schema"],
            )
