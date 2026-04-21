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


# ---------------------------------------------------------------------------
# Normal flow: create → check_quotes → award → completed
# ---------------------------------------------------------------------------


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
        assert task["pending_callback"] is not None
        assert task["pending_callback"]["node_id"] == "check_quotes"
        assert task["pending_callback"]["event_id"] is not None

    @pytest.mark.asyncio
    async def test_award_completes_workflow(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Callback with award should complete the workflow."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]
        event_id = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]

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

        assert result["status"] == "completed"
        assert result["pending_callback"] is None

        final_task = await inquiry_service.get_task(task_id)
        assert final_task["status"] == "completed"


# ---------------------------------------------------------------------------
# Multi-round: new_round → check_quotes → award
# ---------------------------------------------------------------------------


class TestInquiryMultiRound:
    """Test multi-round inquiry flow: new_round → check_quotes → award."""

    @pytest.mark.asyncio
    async def test_new_round_loops_back_to_interrupt(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Callback with new_round should re-interrupt at check_quotes."""
        task = await inquiry_service.create_task(
            user_id="test_user",
            task_type="inquiry",
            data=MOCK_TASK_DATA,
        )
        task_id = task["id"]
        event_id = task["pending_callback"]["event_id"]
        node_id = task["pending_callback"]["node_id"]

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
        assert result["pending_callback"] is not None
        assert result["pending_callback"]["event_id"] != event_id

    @pytest.mark.asyncio
    async def test_two_rounds_then_award(
        self, db, inquiry_service, inquiry_workflow,
    ):
        """Full multi-round flow: create → new_round → award → completed."""
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

        # Round 2: award
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


# ---------------------------------------------------------------------------
# Event idempotency
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Callback validation
# ---------------------------------------------------------------------------


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
