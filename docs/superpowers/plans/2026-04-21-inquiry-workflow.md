# Inquiry Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the inquiry (询价) workflow with 1 interrupt node (check_quotes), 2 branches (new_round / push_erp), YAML config, unit tests (mocked action nodes), and integration tests (real SQLite DB).

**Architecture:** Follow existing patterns: YAML config → WorkflowBuilder → WorkflowExecutor. New YAML config in `app/workflow/config/inquiry.yml`. Action nodes (`create_inquiry`, `send_inquiry`, `push_to_erp`) are mocked in unit tests. Integration tests use real SQLite with mocked external dependencies (SMTP, Oracle EBS).

**Tech Stack:** Python, LangGraph (StateGraph), Pytest, SQLite, Pydantic

---

## File Structure

```
Files to create:
  app/workflow/config/inquiry.yml           — Workflow YAML config
  tests/unit/test_inquiry_workflow.py       — Unit tests (mock action nodes)
  tests/integration/test_inquiry_workflow.py — Integration tests (real SQLite)

Files to read (no modification):
  app/workflow/builder.py                   — WorkflowBuilder (load/build)
  app/workflow/executor.py                  — WorkflowExecutor (execute/resume)
  app/service/task_service.py               — TaskService (create/callback)
  tests/conftest.py                         — Shared fixtures (db, repos, service)
```

---

### Task 1: Create Inquiry YAML Config

**Files:**
- Create: `app/workflow/config/inquiry.yml`

- [ ] **Step 1: Write the YAML config**

```yaml
name: inquiry
display_name: 询价任务
description: 询价单从创建到ERP导入的完整工作流

nodes:
  - id: create_inquiry
    type: action
    display_name: 创建询价单
    description: 根据已确认的物料和供应商数据创建询价单
    next: send_inquiry

  - id: send_inquiry
    type: action
    display_name: 发送询价
    description: 通过SMTP向所有供应商发送询价邮件
    next: check_quotes

  - id: check_quotes
    type: interrupt
    display_name: 报价检查点
    description: 补录报价、查看对比表、决策继续询价或导入ERP
    transitions:
      - action: new_round
        label: 继续询价
        target_node: send_inquiry
        condition: action == "new_round"
        form_schema:
          type: object
          required: [new_deadline]
          properties:
            new_deadline:
              type: string
              format: date-time
              description: 新一轮报价截止时间，必须晚于当前时间
      - action: push_erp
        label: 导入ERP
        target_node: push_to_erp
        condition: action == "push_erp"
        form_schema:
          type: object
          required: [quotes, winners]
          properties:
            quotes:
              type: array
              description: 各供应商报价数据（含补录）
              items:
                type: object
                required: [supplier_id, items]
                properties:
                  supplier_id:
                    type: string
                    description: 供应商编码
                  items:
                    type: array
                    items:
                      type: object
                      required: [material_code, unit_price_tax_incl, tax_rate, currency]
                      properties:
                        material_code:
                          type: string
                          description: 物料编码
                        unit_price_tax_incl:
                          type: number
                          description: 含税单价
                        tax_rate:
                          type: number
                          description: 税率
                        currency:
                          type: string
                          description: 币种
                        delivery_period:
                          type: string
                          description: 交货期
                        remark:
                          type: string
                          description: 备注
            winners:
              type: array
              description: 中标供应商及对应物料（按物料维度，支持部分中标）
              items:
                type: object
                required: [supplier_id, material_code]
                properties:
                  supplier_id:
                    type: string
                    description: 中标供应商编码
                  material_code:
                    type: string
                    description: 中标物料编码

  - id: push_to_erp
    type: action
    display_name: 导入ERP
    description: 报价数据和中标结果导入Oracle EBS
    next: completed

  - id: completed
    type: terminal
    display_name: 已完成
    description: 询价单完成
    status: completed
```

- [ ] **Step 2: Verify config loads correctly**

Run: `python -c "from app.workflow.builder import WorkflowBuilder; c = WorkflowBuilder.load_config('inquiry'); print(c['name'], len(c['nodes']))"`
Expected: `inquiry 5`

- [ ] **Step 3: Commit**

```bash
git add app/workflow/config/inquiry.yml
git commit -m "feat(workflow): add inquiry workflow YAML config"
```

---

### Task 2: Unit Tests — Graph Structure

**Files:**
- Create: `tests/unit/test_inquiry_workflow.py`

- [ ] **Step 1: Write failing tests for graph structure**

```python
"""Unit tests for inquiry workflow graph structure."""
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
        assert targets["push_erp"] == "push_to_erp"

    def test_interrupt_node_ids(self):
        """Test get_interrupt_node_ids returns check_quotes."""
        config = WorkflowBuilder.load_config("inquiry")
        interrupt_ids = WorkflowBuilder.get_interrupt_node_ids(config)

        assert interrupt_ids == ["check_quotes"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_inquiry_workflow.py -v`
Expected: FAIL (file does not exist yet)

- [ ] **Step 3: Tests should pass (no implementation needed, just config)**

Run: `pytest tests/unit/test_inquiry_workflow.py -v`
Expected: ALL PASS (config is already created in Task 1)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_inquiry_workflow.py
git commit -m "test(unit): add inquiry workflow graph structure tests"
```

---

### Task 3: Unit Tests — Condition Routing

**Files:**
- Modify: `tests/unit/test_inquiry_workflow.py`

- [ ] **Step 1: Add condition routing tests**

Append to `TestInquiryWorkflowBuild`:

```python
    def test_condition_routing_new_round(self):
        """Test action=='new_round' routes to send_inquiry."""
        config = WorkflowBuilder.load_config("inquiry")
        result = WorkflowBuilder._evaluate_condition(
            "action == \"new_round\"", {"action": "new_round"}
        )
        assert result is True

    def test_condition_routing_push_erp(self):
        """Test action=='push_erp' routes to push_to_erp."""
        config = WorkflowBuilder.load_config("inquiry")
        result = WorkflowBuilder._evaluate_condition(
            "action == \"push_erp\"", {"action": "push_erp"}
        )
        assert result is True

    def test_condition_routing_unknown_action(self):
        """Test unknown action defaults to False."""
        result = WorkflowBuilder._evaluate_condition(
            "action == \"new_round\"", {"action": "unknown"}
        )
        assert result is False
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_inquiry_workflow.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_inquiry_workflow.py
git commit -m "test(unit): add inquiry workflow condition routing tests"
```

---

### Task 4: Unit Tests — Form Schema Validation

**Files:**
- Modify: `tests/unit/test_inquiry_workflow.py`

- [ ] **Step 1: Add form_schema extraction and validation tests**

Append a new class:

```python
class TestInquiryFormSchema:
    """Tests for interrupt node form_schema correctness."""

    def test_new_round_schema_requires_deadline(self):
        """Test new_round form_schema requires new_deadline."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        new_round = next(
            t for t in check_quotes["transitions"] if t["action"] == "new_round"
        )
        schema = new_round["form_schema"]

        assert "new_deadline" in schema["required"]

    def test_push_erp_schema_requires_quotes_and_winners(self):
        """Test push_erp form_schema requires quotes and winners."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        push_erp = next(
            t for t in check_quotes["transitions"] if t["action"] == "push_erp"
        )
        schema = push_erp["form_schema"]

        assert "quotes" in schema["required"]
        assert "winners" in schema["required"]

    def test_push_erp_quotes_schema_structure(self):
        """Test push_erp quotes has correct nested structure."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        push_erp = next(
            t for t in check_quotes["transitions"] if t["action"] == "push_erp"
        )
        quotes_prop = push_erp["form_schema"]["properties"]["quotes"]

        assert quotes_prop["type"] == "array"
        item_props = quotes_prop["items"]["properties"]
        assert "supplier_id" in item_props
        assert "items" in item_props
        material_props = item_props["items"]["items"]["properties"]
        assert "material_code" in material_props
        assert "unit_price_tax_incl" in material_props
        assert "tax_rate" in material_props
        assert "currency" in material_props

    def test_push_erp_winners_schema_structure(self):
        """Test push_erp winners has supplier_id and material_code."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        push_erp = next(
            t for t in check_quotes["transitions"] if t["action"] == "push_erp"
        )
        winner_props = push_erp["form_schema"]["properties"]["winners"]

        assert winner_props["type"] == "array"
        assert "supplier_id" in winner_props["items"]["required"]
        assert "material_code" in winner_props["items"]["required"]

    def test_validate_new_round_with_valid_data(self):
        """Test new_round form accepts valid data against JSON Schema."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        new_round = next(
            t for t in check_quotes["transitions"] if t["action"] == "new_round"
        )
        schema = new_round["form_schema"]

        valid_data = {"new_deadline": "2026-05-01T18:00:00"}
        jsonschema.validate(valid_data, schema)  # Should not raise

    def test_validate_new_round_missing_deadline(self):
        """Test new_round form rejects missing new_deadline."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        new_round = next(
            t for t in check_quotes["transitions"] if t["action"] == "new_round"
        )
        schema = new_round["form_schema"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, schema)

    def test_validate_push_erp_with_valid_data(self):
        """Test push_erp form accepts valid data against JSON Schema."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        push_erp = next(
            t for t in check_quotes["transitions"] if t["action"] == "push_erp"
        )
        schema = push_erp["form_schema"]

        valid_data = {
            "quotes": [
                {
                    "supplier_id": "SUP_001",
                    "items": [
                        {
                            "material_code": "MAT_001",
                            "unit_price_tax_incl": 1050.0,
                            "tax_rate": 0.13,
                            "currency": "CNY"
                        }
                    ]
                }
            ],
            "winners": [
                {"supplier_id": "SUP_001", "material_code": "MAT_001"}
            ]
        }
        jsonschema.validate(valid_data, schema)  # Should not raise

    def test_validate_push_erp_missing_quotes(self):
        """Test push_erp form rejects missing quotes."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        push_erp = next(
            t for t in check_quotes["transitions"] if t["action"] == "push_erp"
        )
        schema = push_erp["form_schema"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"winners": []}, schema)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_inquiry_workflow.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_inquiry_workflow.py
git commit -m "test(unit): add inquiry form_schema validation tests"
```

---

### Task 5: Integration Tests — Normal Flow (push_erp)

**Files:**
- Create: `tests/integration/test_inquiry_workflow.py`

- [ ] **Step 1: Write integration test for direct push_erp flow**

```python
"""Integration tests for inquiry workflow with real SQLite database."""
import pytest

from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder


@pytest.fixture
def inquiry_service(task_service):
    """TaskService instance for inquiry workflow tests."""
    return task_service


@pytest.fixture
def inquiry_config():
    """Load inquiry workflow config."""
    return WorkflowBuilder.load_config("inquiry")


class TestInquiryNormalFlow:
    """Test the normal inquiry flow: create → check_quotes → push_erp → completed."""

    @pytest.mark.asyncio
    async def test_create_inquiry_task_interrupts_at_check_quotes(
        self, inquiry_service, inquiry_config
    ):
        """Creating an inquiry task should interrupt at check_quotes node."""
        task = await inquiry_service.create(
            user_id="test_user",
            task_type="inquiry",
            data={"materials": ["MAT_001"], "suppliers": ["SUP_001"]},
        )

        assert task["id"] is not None
        assert task["status"] == "interrupted"

        # Verify pending_callback points to check_quotes
        assert task["data"]["pending_callback"]["node_id"] == "check_quotes"
        assert task["data"]["pending_callback"]["event_id"] is not None

    @pytest.mark.asyncio
    async def test_push_erp_completes_workflow(
        self, inquiry_service, inquiry_config
    ):
        """Callback with push_erp should complete the workflow."""
        # Create task (interrupts at check_quotes)
        task = await inquiry_service.create(
            user_id="test_user",
            task_type="inquiry",
            data={"materials": ["MAT_001"], "suppliers": ["SUP_001"]},
        )
        task_id = task["id"]
        event_id = task["data"]["pending_callback"]["event_id"]
        node_id = task["data"]["pending_callback"]["node_id"]

        # Callback with push_erp branch
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            user_input={
                "action": "push_erp",
                "quotes": [
                    {
                        "supplier_id": "SUP_001",
                        "items": [
                            {
                                "material_code": "MAT_001",
                                "unit_price_tax_incl": 1050.0,
                                "tax_rate": 0.13,
                                "currency": "CNY",
                            }
                        ],
                    }
                ],
                "winners": [
                    {"supplier_id": "SUP_001", "material_code": "MAT_001"}
                ],
            },
        )

        # Verify workflow completed
        assert result["status"] == "completed"

        # Verify final task state in DB
        final_task = await inquiry_service.get_task(task_id)
        assert final_task["status"] == "completed"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/integration/test_inquiry_workflow.py::TestInquiryNormalFlow -v`
Expected: Tests may need fixture adjustments based on conftest.py

- [ ] **Step 3: Fix any fixture or import issues, re-run until green**

Run: `pytest tests/integration/test_inquiry_workflow.py::TestInquiryNormalFlow -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_inquiry_workflow.py
git commit -m "test(integration): add inquiry normal flow tests"
```

---

### Task 6: Integration Tests — Multi-Round Inquiry

**Files:**
- Modify: `tests/integration/test_inquiry_workflow.py`

- [ ] **Step 1: Add multi-round test**

```python
class TestInquiryMultiRound:
    """Test multi-round inquiry flow: new_round → check_quotes → push_erp."""

    @pytest.mark.asyncio
    async def test_new_round_loops_back_to_interrupt(
        self, inquiry_service, inquiry_config
    ):
        """Callback with new_round should re-interrupt at check_quotes."""
        # Create task
        task = await inquiry_service.create(
            user_id="test_user",
            task_type="inquiry",
            data={"materials": ["MAT_001"], "suppliers": ["SUP_001"]},
        )
        task_id = task["id"]
        event_id = task["data"]["pending_callback"]["event_id"]
        node_id = task["data"]["pending_callback"]["node_id"]

        # First callback: new_round
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            user_input={
                "action": "new_round",
                "new_deadline": "2026-06-01T18:00:00",
            },
        )

        assert result["status"] == "interrupted"

        # Verify new event_id (different from first)
        new_event_id = result["data"]["pending_callback"]["event_id"]
        assert new_event_id != event_id

    @pytest.mark.asyncio
    async def test_two_rounds_then_push_erp(
        self, inquiry_service, inquiry_config
    ):
        """Full multi-round flow: create → new_round → push_erp → completed."""
        # Create task
        task = await inquiry_service.create(
            user_id="test_user",
            task_type="inquiry",
            data={"materials": ["MAT_001"], "suppliers": ["SUP_001"]},
        )
        task_id = task["id"]

        # Round 1: new_round
        event_id_1 = task["data"]["pending_callback"]["event_id"]
        node_id = task["data"]["pending_callback"]["node_id"]
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id_1,
            node_id=node_id,
            user_input={
                "action": "new_round",
                "new_deadline": "2026-06-01T18:00:00",
            },
        )
        assert result["status"] == "interrupted"

        # Round 2: push_erp
        event_id_2 = result["data"]["pending_callback"]["event_id"]
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id_2,
            node_id=node_id,
            user_input={
                "action": "push_erp",
                "quotes": [
                    {
                        "supplier_id": "SUP_001",
                        "items": [
                            {
                                "material_code": "MAT_001",
                                "unit_price_tax_incl": 1000.0,
                                "tax_rate": 0.13,
                                "currency": "CNY",
                            }
                        ],
                    }
                ],
                "winners": [
                    {"supplier_id": "SUP_001", "material_code": "MAT_001"}
                ],
            },
        )

        assert result["status"] == "completed"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/integration/test_inquiry_workflow.py::TestInquiryMultiRound -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_inquiry_workflow.py
git commit -m "test(integration): add multi-round inquiry tests"
```

---

### Task 7: Integration Tests — Event Idempotency

**Files:**
- Modify: `tests/integration/test_inquiry_workflow.py`

- [ ] **Step 1: Add event replay protection tests**

```python
class TestInquiryEventIdempotency:
    """Test event_id replay protection for inquiry workflow."""

    @pytest.mark.asyncio
    async def test_duplicate_callback_rejected(self, inquiry_service):
        """Second callback with same event_id should fail."""
        task = await inquiry_service.create(
            user_id="test_user",
            task_type="inquiry",
            data={"materials": ["MAT_001"], "suppliers": ["SUP_001"]},
        )
        task_id = task["id"]
        event_id = task["data"]["pending_callback"]["event_id"]
        node_id = task["data"]["pending_callback"]["node_id"]

        # First callback succeeds
        await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            user_input={
                "action": "new_round",
                "new_deadline": "2026-06-01T18:00:00",
            },
        )

        # Second callback with same event_id should raise
        with pytest.raises(ValueError, match="already consumed"):
            await inquiry_service.callback(
                task_id=task_id,
                event_id=event_id,
                node_id=node_id,
                user_input={
                    "action": "push_erp",
                    "quotes": [],
                    "winners": [],
                },
            )
```

- [ ] **Step 2: Run test**

Run: `pytest tests/integration/test_inquiry_workflow.py::TestInquiryEventIdempotency -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_inquiry_workflow.py
git commit -m "test(integration): add inquiry event idempotency test"
```

---

### Task 8: Run Full Test Suite

- [ ] **Step 1: Run all unit tests**

Run: `pytest tests/unit/ -v`
Expected: ALL PASS (existing + new inquiry tests)

- [ ] **Step 2: Run all integration tests**

Run: `pytest tests/integration/ -v`
Expected: ALL PASS (existing + new inquiry tests)

- [ ] **Step 3: Run full test suite with coverage**

Run: `pytest --cov=app --cov-report=term-missing -v`
Expected: No regressions in existing tests
