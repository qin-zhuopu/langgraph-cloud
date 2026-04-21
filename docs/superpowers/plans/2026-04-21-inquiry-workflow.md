# Inquiry Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the inquiry (询价) workflow with 1 interrupt node (check_quotes), 2 branches (new_round / award), YAML config, unit tests (mocked action nodes), and integration tests (real SQLite DB).

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
    target_node: send_inquiry

  - id: send_inquiry
    type: action
    display_name: 发送询价
    description: 通过SMTP向所有供应商发送询价邮件
    target_node: check_quotes

  - id: check_quotes
    type: interrupt
    display_name: 报价检查点
    description: 补录报价、查看对比表、决策继续询价或定标
    transitions:
      - action: new_round
        label: 继续询价
        target_node: send_inquiry
        condition: action == "new_round"
        form_schema:
          type: object
          required: [new_deadline, supplier_codes]
          properties:
            new_deadline:
              type: string
              format: date-time
              description: 新一轮报价截止时间，必须晚于当前时间
            supplier_codes:
              type: array
              items:
                type: string
              minItems: 1
              description: 参与下一轮询价的供应商编码列表
      - action: award
        label: 定标
        target_node: push_to_erp
        condition: action == "award"
        form_schema:
          type: object
          required: [winners]
          properties:
            winners:
              type: array
              minItems: 1
              description: 中标结果（物料×供应商×价格）
              items:
                type: object
                required: [material_code, supplier_code, awarded_price]
                properties:
                  material_code:
                    type: string
                    description: 物料编码
                  supplier_code:
                    type: string
                    description: 中标供应商编码
                  awarded_price:
                    type: number
                    description: 中标价格

  - id: push_to_erp
    type: action
    display_name: 导入ERP
    description: 报价数据和中标结果导入Oracle EBS
    target_node: completed

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
        assert targets["award"] == "push_to_erp"

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

    def test_condition_routing_award(self):
        """Test action=='award' routes to push_to_erp."""
        config = WorkflowBuilder.load_config("inquiry")
        result = WorkflowBuilder._evaluate_condition(
            "action == \"award\"", {"action": "award"}
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

    def test_new_round_schema_requires_deadline_and_suppliers(self):
        """Test new_round form_schema requires new_deadline and supplier_codes."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        new_round = next(
            t for t in check_quotes["transitions"] if t["action"] == "new_round"
        )
        schema = new_round["form_schema"]

        assert "new_deadline" in schema["required"]
        assert "supplier_codes" in schema["required"]

    def test_award_schema_requires_winners(self):
        """Test award form_schema requires winners."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        award = next(
            t for t in check_quotes["transitions"] if t["action"] == "award"
        )
        schema = award["form_schema"]

        assert "winners" in schema["required"]

    def test_award_winners_schema_structure(self):
        """Test award winners requires material_code, supplier_code, awarded_price."""
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        award = next(
            t for t in check_quotes["transitions"] if t["action"] == "award"
        )
        winner_schema = award["form_schema"]["properties"]["winners"]["items"]

        assert "material_code" in winner_schema["required"]
        assert "supplier_code" in winner_schema["required"]
        assert "awarded_price" in winner_schema["required"]

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

        valid_data = {
            "new_deadline": "2026-05-15T18:00:00",
            "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN", "SUP_SHIYI", "SUP_TONGZHOU"],
        }
        jsonschema.validate(valid_data, schema)  # Should not raise

    def test_validate_new_round_missing_supplier_codes(self):
        """Test new_round form rejects missing supplier_codes."""
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
            jsonschema.validate({"new_deadline": "2026-05-15T18:00:00"}, schema)

    def test_validate_new_round_empty_supplier_codes(self):
        """Test new_round form rejects empty supplier_codes array."""
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
            jsonschema.validate({"new_deadline": "2026-05-15T18:00:00", "supplier_codes": []}, schema)

    def test_validate_award_with_valid_data(self):
        """Test award form accepts valid data against JSON Schema."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        award = next(
            t for t in check_quotes["transitions"] if t["action"] == "award"
        )
        schema = award["form_schema"]

        valid_data = {
            "winners": [
                {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                {"material_code": "C050086211", "supplier_code": "SUP_DEXIN", "awarded_price": 2200.0},
                {"material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.0},
            ]
        }
        jsonschema.validate(valid_data, schema)  # Should not raise

    def test_validate_award_missing_winners(self):
        """Test award form rejects missing winners."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        award = next(
            t for t in check_quotes["transitions"] if t["action"] == "award"
        )
        schema = award["form_schema"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, schema)

    def test_validate_award_winner_missing_price(self):
        """Test award form rejects winner without awarded_price."""
        import jsonschema
        config = WorkflowBuilder.load_config("inquiry")
        check_quotes = next(
            n for n in config["nodes"] if n["id"] == "check_quotes"
        )
        award = next(
            t for t in check_quotes["transitions"] if t["action"] == "award"
        )
        schema = award["form_schema"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({
                "winners": [{"material_code": "C050066547", "supplier_code": "SUP_JINGLIN"}]
            }, schema)
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

### Task 5: Integration Tests — Normal Flow (award)

**Files:**
- Create: `tests/integration/test_inquiry_workflow.py`

- [ ] **Step 1: Write integration test for direct award flow**

```python
"""Integration tests for inquiry workflow with real SQLite database."""
import pytest

from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder


@pytest.fixture
def inquiry_config():
    """Load inquiry workflow config."""
    return WorkflowBuilder.load_config("inquiry")


@pytest.fixture
async def inquiry_workflow(db, workflow_repo: SQLiteWorkflowRepo, inquiry_config):
    """Register inquiry workflow config in the database."""
    await workflow_repo.save_version("v1", "inquiry", inquiry_config, active=True)
    yield "inquiry"


@pytest.fixture
def inquiry_service(
    task_repo, message_bus, event_store, workflow_repo,
) -> TaskService:
    """TaskService instance for inquiry workflow tests."""
    from app.workflow.executor import WorkflowExecutor
    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)
    return TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )


MOCK_TASK_DATA = {
    "title": "自动化控制设备采购询价",
    "business_entity": "杰瑞集团",
    "deadline": "2026-05-01T18:00:00",
    "template_id": "TPL_AUTO_CTRL",
    "is_annual": False,
    "materials": [
        {"material_code": "C050066547", "material_desc": "8路模拟量输出模块", "quantity": 10, "unit": "个", "need_date": "2026-05-15", "category_l4": "自动化控制"},
        {"material_code": "C050086211", "material_desc": "高速计数模块", "quantity": 5, "unit": "个", "need_date": "2026-05-15", "category_l4": "自动化控制"},
        {"material_code": "C050099301", "material_desc": "工业以太网交换机", "quantity": 20, "unit": "台", "need_date": "2026-05-20", "category_l4": "网络设备"},
    ],
    "suppliers": [
        {"supplier_code": "SUP_JINGLIN", "supplier_name": "河北京霖拖链技术有限公司", "contact_name": "王经理", "email": "wang@jinglin.com", "source": "group_match"},
        {"supplier_code": "SUP_DEXIN", "supplier_name": "河南德信安全科技有限公司", "contact_name": "李工", "email": "li@dexin.com", "source": "group_match"},
        {"supplier_code": "SUP_SHIYI", "supplier_name": "山东拾一科技服务有限公司", "contact_name": "张总", "email": "zhang@shiyi.com", "source": "manual"},
        {"supplier_code": "SUP_TONGZHOU", "supplier_name": "北京同洲维普科技有限公司", "contact_name": "赵经理", "email": "zhao@tongzhou.com", "source": "ai_recommend"},
        {"supplier_code": "SUP_WANSHAN", "supplier_name": "深圳市万山文创有限公司", "contact_name": "陈总", "email": "chen@wanshan.com", "source": "ai_recommend"},
    ],
}


class TestInquiryNormalFlow:
    """Test the normal inquiry flow: create → check_quotes → award → completed."""

    @pytest.mark.asyncio
    async def test_create_inquiry_task_interrupts_at_check_quotes(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Creating an inquiry task should interrupt at check_quotes node."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )

        assert task["id"] is not None
        assert task["status"] == "awaiting_check_quotes"

        # pending_callback is a top-level field on the task dict
        assert task["pending_callback"] is not None
        assert task["pending_callback"]["node_id"] == "check_quotes"
        assert task["pending_callback"]["event_id"] is not None

    @pytest.mark.asyncio
    async def test_award_completes_workflow(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Callback with award should complete the workflow."""
        # Create task (interrupts at check_quotes)
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]
        event_id = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]

        # Callback with award branch
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            action="award",
            user_input={
                "winners": [
                    {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                    {"material_code": "C050086211", "supplier_code": "SUP_DEXIN", "awarded_price": 2200.0},
                    {"material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.0},
                ],
            },
        )

        # Verify workflow completed
        assert result["status"] == "completed"
        assert result["pending_callback"] is None

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
    """Test multi-round inquiry flow: new_round → check_quotes → award."""

    @pytest.mark.asyncio
    async def test_new_round_loops_back_to_interrupt(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Callback with new_round should re-interrupt at check_quotes."""
        # Create task
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]
        event_id = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]

        # First callback: new_round — eliminate 万山, keep 4 suppliers
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            action="new_round",
            user_input={
                "new_deadline": "2026-05-15T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN", "SUP_SHIYI", "SUP_TONGZHOU"],
            },
        )

        assert result["status"] == "awaiting_check_quotes"

        # Verify new pending_callback with different event_id
        assert result["pending_callback"] is not None
        new_event_id = result["pending_callback"]["event_id"]
        assert new_event_id != event_id

    @pytest.mark.asyncio
    async def test_two_rounds_then_award(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Full multi-round flow: create → new_round → award → completed."""
        # Create task with 5 suppliers
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]

        # Round 1: new_round — eliminate 万山
        event_id_1 = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id_1,
            node_id=node_id,
            action="new_round",
            user_input={
                "new_deadline": "2026-05-15T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN", "SUP_SHIYI", "SUP_TONGZHOU"],
            },
        )
        assert result["status"] == "awaiting_check_quotes"

        # Round 2: award — select winners per material
        event_id_2 = result["pending_callback"]["event_id"]
        result = await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id_2,
            node_id=node_id,
            action="award",
            user_input={
                "winners": [
                    {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                    {"material_code": "C050086211", "supplier_code": "SUP_DEXIN", "awarded_price": 2200.0},
                    {"material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.0},
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

### Task 7: Integration Tests — Event Idempotency & Validation

**Files:**
- Modify: `tests/integration/test_inquiry_workflow.py`

- [ ] **Step 1: Add event replay protection tests**

```python
class TestInquiryEventIdempotency:
    """Test event_id replay protection for inquiry workflow."""

    @pytest.mark.asyncio
    async def test_duplicate_callback_rejected(self, db, inquiry_service, inquiry_workflow):
        """Second callback with same event_id should fail."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]
        event_id = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]

        # First callback succeeds
        await inquiry_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id=node_id,
            action="new_round",
            user_input={
                "new_deadline": "2026-06-01T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN"],
            },
        )

        # Second callback with same event_id should raise
        with pytest.raises(ValueError, match="already consumed"):
            await inquiry_service.callback(
                task_id=task_id,
                event_id=event_id,
                node_id=node_id,
                action="award",
                user_input={
                    "winners": [
                        {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                    ],
                },
            )
```

- [ ] **Step 2: Add callback validation tests**

```python
class TestInquiryCallbackValidation:
    """Test callback action and form_schema validation at service level."""

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, db, inquiry_service, inquiry_workflow):
        """Callback with unknown action should raise ValueError."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        event_id = task["pending_callback"]["event_id"]

        with pytest.raises(ValueError, match="Invalid action"):
            await inquiry_service.callback(
                task_id=task["id"],
                event_id=event_id,
                node_id="check_quotes",
                action="cancel",
                user_input={},
            )

    @pytest.mark.asyncio
    async def test_new_round_missing_supplier_codes_rejected(self, db, inquiry_service, inquiry_workflow):
        """new_round callback without supplier_codes should raise ValueError."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        event_id = task["pending_callback"]["event_id"]

        with pytest.raises(ValueError, match="validation failed"):
            await inquiry_service.callback(
                task_id=task["id"],
                event_id=event_id,
                node_id="check_quotes",
                action="new_round",
                user_input={"new_deadline": "2026-06-01T18:00:00"},
            )

    @pytest.mark.asyncio
    async def test_award_missing_winners_rejected(self, db, inquiry_service, inquiry_workflow):
        """award callback without winners should raise ValueError."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        event_id = task["pending_callback"]["event_id"]

        with pytest.raises(ValueError, match="validation failed"):
            await inquiry_service.callback(
                task_id=task["id"],
                event_id=event_id,
                node_id="check_quotes",
                action="award",
                user_input={},
            )

    @pytest.mark.asyncio
    async def test_award_winner_missing_price_rejected(self, db, inquiry_service, inquiry_workflow):
        """award callback with winner missing awarded_price should raise ValueError."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        event_id = task["pending_callback"]["event_id"]

        with pytest.raises(ValueError, match="validation failed"):
            await inquiry_service.callback(
                task_id=task["id"],
                event_id=event_id,
                node_id="check_quotes",
                action="award",
                user_input={
                    "winners": [{"material_code": "C050066547", "supplier_code": "SUP_JINGLIN"}],
                },
            )

    @pytest.mark.asyncio
    async def test_workflow_not_found_rejected(self, db, inquiry_service):
        """Creating task with unknown workflow type should raise ValueError."""
        with pytest.raises(ValueError, match="Workflow not found"):
            await inquiry_service.create_task(
                user_id="test_user",
                task_type="nonexistent_workflow",
                data={},
            )
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/integration/test_inquiry_workflow.py::TestInquiryEventIdempotency tests/integration/test_inquiry_workflow.py::TestInquiryCallbackValidation -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_inquiry_workflow.py
git commit -m "test(integration): add inquiry idempotency and validation tests"
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
