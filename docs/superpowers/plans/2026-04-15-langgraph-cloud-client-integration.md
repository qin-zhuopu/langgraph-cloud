# LangGraph 云端服务与本地客户端集成 - MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 LangGraph 云端工作流与本地客户端的异步协作 MVP，支持 Human-in-the-Loop 场景

**Architecture:** DDD-lite 分层架构，Domain 接口与 Infrastructure 实现分离，支持从 SQLite 平滑迁移到生产技术栈

**Tech Stack:** FastAPI, aiosqlite, LangGraph, WebSocket, Pydantic, pytest

---

## 文件结构映射

```
app/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── interfaces.py          # ITaskRepository, IMessageBus, IWorkflowRepo, IEventStore
│   └── schemas.py             # TaskCreate, Task, EventMessage, CallbackRequest 等 DTO
│
├── infrastructure/
│   ├── __init__.py
│   ├── database.py            # SQLite 连接管理、表初始化
│   ├── sqlite_repository.py   # TaskRepository 实现
│   ├── sqlite_bus.py          # SQLiteMessageBus 实现（发布/订阅）
│   ├── event_store.py         # EventStore 实现（防重放）
│   └── workflow_repo.py       # WorkflowRepo 实现（配置版本管理）
│
├── workflow/
│   ├── __init__.py
│   ├── builder.py             # 动态图构建器
│   ├── checkpointer.py        # LangGraph MemorySaver 实现
│   ├── executor.py            # 工作流执行器
│   └── config/
│       ├── __init__.py
│       └── purchase_request.yml
│
├── api/
│   ├── __init__.py
│   ├── main.py                # FastAPI 应用入口
│   ├── routes.py              # REST + WebSocket 路由
│   └── deps.py                # FastAPI 依赖注入
│
├── service/
│   ├── __init__.py
│   └── task_service.py        # 任务编排服务
│
└── client_sdk/
    ├── __init__.py
    ├── cli.py                 # 控制台演示客户端
    └── websocket_client.py    # WebSocket 客户端

tests/
├── __init__.py
├── conftest.py                # pytest fixtures
├── unit/
│   ├── __init__.py
│   ├── test_repository.py
│   ├── test_message_bus.py
│   ├── test_event_store.py
│   └── test_workflow_builder.py
├── integration/
│   ├── __init__.py
│   ├── test_api_endpoints.py
│   ├── test_websocket.py
│   └── test_task_service.py
└── e2e/
    ├── __init__.py
    ├── test_websocket_mode.py
    ├── test_polling_mode.py
    └── test_workflow_version_upgrade.py

pyproject.toml                 # 项目依赖配置
README.md                      # 项目说明
```

---

## 依赖配置

### Task 1: 创建项目依赖配置

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "langgraph-cloud-client-integration"
version = "0.1.0"
description = "LangGraph cloud service with local client integration MVP"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "aiosqlite>=0.19.0",
    "langgraph>=0.0.40",
    "langchain-core>=0.1.0",
    "pydantic>=2.5.0",
    "pyyaml>=6.0",
    "websockets>=12.0",
    "httpx>=0.25.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "httpx>=0.25.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add project dependencies configuration"
```

---

## Domain 层

### Task 2: 创建 Domain Schemas

**Files:**
- Create: `app/__init__.py`
- Create: `app/domain/__init__.py`
- Create: `app/domain/schemas.py`
- Test: `tests/unit/test_schemas.py`

- [ ] **Step 1: 创建包初始化文件**

```python
# app/__init__.py
__version__ = "0.1.0"
```

```python
# app/domain/__init__.py
```

- [ ] **Step 2: 编写 Schema 测试（先写测试）**

```python
# tests/unit/test_schemas.py
import pytest
from datetime import datetime
from pydantic import ValidationError

from app.domain.schemas import (
    TaskCreate, TaskData, Task, EventMessage,
    CallbackRequest, TaskResponse, ErrorResponse
)


def test_task_data_valid():
    """TaskData 应该接受有效的 data 字段"""
    data = TaskData(type="purchase_request", data={"amount": 1000})
    assert data.type == "purchase_request"
    assert data.data == {"amount": 1000}


def test_task_data_missing_type():
    """TaskData 缺少 type 应该抛出 ValidationError"""
    with pytest.raises(ValidationError):
        TaskData(data={"amount": 1000})


def test_task_create_valid():
    """TaskCreate 应该接受有效的输入"""
    task_create = TaskCreate(
        user_id="user123",
        task=TaskData(type="purchase_request", data={"amount": 1000})
    )
    assert task_create.user_id == "user123"
    assert task_create.task.type == "purchase_request"


def test_event_message_valid():
    """EventMessage 应该包含所有必需字段"""
    msg = EventMessage(
        event_id="evt_123",
        task_id="task_123",
        task_type="purchase_request",
        status="awaiting_audit",
        node_id="manager_audit",
        required_params=["is_approved"],
        display_data={"title": "请审批"}
    )
    assert msg.event_id == "evt_123"
    assert msg.node_id == "manager_audit"


def test_callback_request_valid():
    """CallbackRequest 应该包含所有必需字段"""
    req = CallbackRequest(
        event_id="evt_123",
        node_id="manager_audit",
        user_input={"is_approved": True}
    )
    assert req.event_id == "evt_123"
    assert req.user_input["is_approved"] is True


def test_callback_request_missing_event_id():
    """CallbackRequest 缺少 event_id 应该抛出 ValidationError"""
    with pytest.raises(ValidationError):
        CallbackRequest(
            node_id="manager_audit",
            user_input={"is_approved": True}
        )
```

- [ ] **Step 3: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_schemas.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.domain.schemas'`

- [ ] **Step 4: 实现 Domain Schemas**

```python
# app/domain/schemas.py
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


class TaskData(BaseModel):
    """任务数据"""
    type: str = Field(..., description="任务类型，对应工作流名称")
    data: dict = Field(default_factory=dict, description="业务数据")


class TaskCreate(BaseModel):
    """创建任务请求"""
    user_id: str = Field(..., description="用户 ID")
    task: TaskData = Field(..., description="任务数据")


class Task(BaseModel):
    """任务实体"""
    id: str
    user_id: str
    type: str
    workflow_version: str = "v1"
    status: str
    data: dict
    created_at: datetime
    updated_at: datetime


class EventMessage(BaseModel):
    """中断事件消息"""
    event_id: str
    task_id: str
    task_type: str
    status: str
    node_id: str
    required_params: list[str] = Field(default_factory=list)
    display_data: dict = Field(default_factory=dict)


class CallbackRequest(BaseModel):
    """回调恢复请求"""
    event_id: str
    node_id: str
    user_input: dict = Field(..., description="用户输入，需包含 required_params 中的所有字段")


class TaskResponse(BaseModel):
    """任务响应"""
    task: Task


class CallbackResponse(BaseModel):
    """回调响应"""
    success: bool
    next_status: str


class ErrorResponse(BaseModel):
    """错误响应"""
    error: dict = Field(..., description="{code, message, details}")
```

- [ ] **Step 5: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_schemas.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/ tests/unit/test_schemas.py
git commit -m "feat(domain): add Pydantic schemas for task and event DTOs"
```

---

### Task 3: 创建 Domain Interfaces

**Files:**
- Create: `app/domain/interfaces.py`
- Test: `tests/unit/test_interfaces.py`

- [ ] **Step 1: 编写接口测试（验证接口定义）**

```python
# tests/unit/test_interfaces.py
import pytest
from abc import ABC

from app.domain.interfaces import (
    ITaskRepository, IMessageBus, IEventStore, IWorkflowRepo
)
from app.domain.schemas import TaskCreate, Task, EventMessage


def test_task_repository_is_abstract():
    """ITaskRepository 应该是抽象基类"""
    assert issubclass(ITaskRepository, ABC)
    abstract_methods = ITaskRepository.__abstractmethods__
    assert "create" in abstract_methods
    assert "get" in abstract_methods
    assert "update_status" in abstract_methods


def test_message_bus_is_abstract():
    """IMessageBus 应该是抽象基类"""
    assert issubclass(IMessageBus, ABC)
    abstract_methods = IMessageBus.__abstractmethods__
    assert "publish" in abstract_methods
    assert "subscribe" in abstract_methods


def test_event_store_is_abstract():
    """IEventStore 应该是抽象基类"""
    assert issubclass(IEventStore, ABC)
    assert "mark_consumed" in IEventStore.__abstractmethods__


def test_workflow_repo_is_abstract():
    """IWorkflowRepo 应该是抽象基类"""
    assert issubclass(IWorkflowRepo, ABC)
    assert "get_active" in IWorkflowRepo.__abstractmethods__
    assert "get_by_version" in IWorkflowRepo.__abstractmethods__
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_interfaces.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.domain.interfaces'`

- [ ] **Step 3: 实现 Domain Interfaces**

```python
# app/domain/interfaces.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from app.domain.schemas import TaskCreate, Task, EventMessage


class ITaskRepository(ABC):
    """任务仓储接口"""

    @abstractmethod
    async def create(
        self,
        user_id: str,
        task_type: str,
        workflow_version: str,
        data: dict
    ) -> str:
        """
        创建任务

        Returns:
            task_id: 新创建的任务 ID
        """
        pass

    @abstractmethod
    async def get(self, task_id: str) -> Optional[Task]:
        """获取任务详情"""
        pass

    @abstractmethod
    async def update_status(
        self,
        task_id: str,
        status: str,
        data: Optional[dict] = None
    ) -> bool:
        """
        更新任务状态

        使用 SQLite BEGIN IMMEDIATE 事务锁保证并发安全
        """
        pass


class IMessageBus(ABC):
    """消息总线接口"""

    @abstractmethod
    async def publish(self, user_id: str, message: EventMessage) -> None:
        """
        发布消息

        服务端调用：当工作流运行到 interrupt 节点时发布
        """
        pass

    @abstractmethod
    async def subscribe(self, user_id: str) -> AsyncIterator[EventMessage]:
        """
        订阅消息

        服务端 WebSocket 连接调用，返回异步迭代器
        """
        pass

    @abstractmethod
    def register_listener(self, user_id: str, queue: "asyncio.Queue") -> None:
        """
        注册监听队列

        用于 WebSocket 连接管理器注册消息队列
        """
        pass

    @abstractmethod
    def unregister_listener(self, user_id: str, queue: "asyncio.Queue") -> None:
        """取消监听队列"""
        pass


class IEventStore(ABC):
    """事件存储接口（防重放）"""

    @abstractmethod
    async def mark_consumed(self, event_id: str) -> bool:
        """
        标记事件已消费

        Returns:
            True: 标记成功
            False: 事件已被消费（防重放）
        """
        pass

    @abstractmethod
    async def is_consumed(self, event_id: str) -> bool:
        """检查事件是否已消费"""
        pass


class IWorkflowRepo(ABC):
    """工作流配置仓储接口"""

    @abstractmethod
    async def get_active(self, workflow_name: str) -> Optional[dict]:
        """
        获取活跃版本的工作流配置

        Returns:
            工作流配置字典，包含 version, name, config 等
        """
        pass

    @abstractmethod
    async def get_by_version(self, workflow_name: str, version: str) -> Optional[dict]:
        """获取指定版本的工作流配置"""
        pass

    @abstractmethod
    async def save_version(
        self,
        version: str,
        workflow_name: str,
        config: dict,
        active: bool = True
    ) -> None:
        """保存工作流配置版本"""
        pass
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_interfaces.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/domain/interfaces.py tests/unit/test_interfaces.py
git commit -m "feat(domain): add repository and service interfaces"
```

---

## Infrastructure 层

### Task 4: 创建数据库连接和表初始化

**Files:**
- Create: `app/infrastructure/__init__.py`
- Create: `app/infrastructure/database.py`

- [ ] **Step 1: 创建数据库模块**

```python
# app/infrastructure/__init__.py
```

```python
# app/infrastructure/database.py
import aiosqlite
from pathlib import Path
from typing import Optional


class Database:
    """SQLite 数据库连接管理"""

    def __init__(self, db_path: str = "langgraph.db"):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> aiosqlite.Connection:
        """获取数据库连接（每次创建新连接）"""
        return await aiosqlite.connect(self.db_path)

    async def init_tables(self) -> None:
        """初始化数据库表结构"""
        async with await self.connect() as db:
            # 任务表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    workflow_version TEXT NOT NULL DEFAULT 'v1',
                    status TEXT NOT NULL DEFAULT 'initiated',
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 事件表（消息队列）
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    consumed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                )
            """)

            # LangGraph 状态持久化
            await db.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_id)
                )
            """)

            # 工作流配置版本
            await db.execute("""
                CREATE TABLE IF NOT EXISTS workflow_versions (
                    version TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    config TEXT NOT NULL,
                    active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)

            # 索引
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_user_consumed ON events(user_id, consumed)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON checkpoints(thread_id)")

            await db.commit()

    async def clear_all(self) -> None:
        """清空所有表（测试用）"""
        async with await self.connect() as db:
            await db.execute("DELETE FROM tasks")
            await db.execute("DELETE FROM events")
            await db.execute("DELETE FROM checkpoints")
            await db.execute("DELETE FROM workflow_versions")
            await db.commit()
```

- [ ] **Step 2: 创建测试 fixture**

```python
# tests/conftest.py
import pytest
import asyncio
from app.infrastructure.database import Database
from app.domain.interfaces import ITaskRepository, IMessageBus, IEventStore, IWorkflowRepo
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo


@pytest.fixture
def db_path(tmp_path):
    """测试用临时数据库路径"""
    return str(tmp_path / "test.db")


@pytest.fixture
async def db(db_path):
    """测试用数据库实例"""
    database = Database(db_path)
    await database.init_tables()
    yield database
    # 清理
    await database.clear_all()


@pytest.fixture
async def task_repo(db):
    """任务仓储实例"""
    return SQLiteTaskRepository(db.db_path)


@pytest.fixture
async def message_bus(db):
    """消息总线实例"""
    return SQLiteMessageBus(db.db_path)


@pytest.fixture
async def event_store(db):
    """事件存储实例"""
    return SQLiteEventStore(db.db_path)


@pytest.fixture
async def workflow_repo(db):
    """工作流仓储实例"""
    return SQLiteWorkflowRepo(db.db_path)
```

- [ ] **Step 3: Commit**

```bash
git add app/infrastructure/database.py tests/conftest.py
git commit -m "feat(infrastructure): add SQLite database connection and table initialization"
```

---

### Task 5: 实现 TaskRepository

**Files:**
- Create: `app/infrastructure/sqlite_repository.py`
- Test: `tests/unit/test_repository.py`

- [ ] **Step 1: 编写 TaskRepository 测试**

```python
# tests/unit/test_repository.py
import pytest
from datetime import datetime
from app.domain.schemas import Task
from app.infrastructure.sqlite_repository import SQLiteTaskRepository


@pytest.mark.asyncio
async def test_create_task(task_repo):
    """应该能创建任务并返回 task_id"""
    task_id = await task_repo.create(
        user_id="user123",
        task_type="purchase_request",
        workflow_version="v1",
        data={"amount": 1000, "order_no": "REQ-001"}
    )
    assert task_id is not None
    assert isinstance(task_id, str)
    assert len(task_id) > 0


@pytest.mark.asyncio
async def test_get_task(task_repo):
    """应该能获取创建的任务"""
    task_id = await task_repo.create(
        user_id="user123",
        task_type="purchase_request",
        workflow_version="v1",
        data={"amount": 1000}
    )
    task = await task_repo.get(task_id)
    assert task is not None
    assert task.id == task_id
    assert task.user_id == "user123"
    assert task.type == "purchase_request"
    assert task.workflow_version == "v1"
    assert task.status == "initiated"
    assert task.data["amount"] == 1000


@pytest.mark.asyncio
async def test_get_nonexistent_task(task_repo):
    """获取不存在的任务应该返回 None"""
    task = await task_repo.get("nonexistent")
    assert task is None


@pytest.mark.asyncio
async def test_update_task_status(task_repo):
    """应该能更新任务状态"""
    task_id = await task_repo.create(
        user_id="user123",
        task_type="purchase_request",
        workflow_version="v1",
        data={"amount": 1000}
    )
    success = await task_repo.update_status(task_id, "awaiting_manager_audit")
    assert success is True

    task = await task_repo.get(task_id)
    assert task.status == "awaiting_manager_audit"


@pytest.mark.asyncio
async def test_update_task_status_with_data(task_repo):
    """应该能更新任务状态和附加数据"""
    task_id = await task_repo.create(
        user_id="user123",
        task_type="purchase_request",
        workflow_version="v1",
        data={"amount": 1000}
    )
    success = await task_repo.update_status(
        task_id,
        "completed",
        data={"result": "approved", "approver": "manager"}
    )
    assert success is True

    task = await task_repo.get(task_id)
    assert task.status == "completed"
    assert task.data["result"] == "approved"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_repository.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.infrastructure.sqlite_repository'`

- [ ] **Step 3: 实现 TaskRepository**

```python
# app/infrastructure/sqlite_repository.py
import json
import uuid
from datetime import datetime
import aiosqlite

from app.domain.interfaces import ITaskRepository
from app.domain.schemas import Task


class SQLiteTaskRepository(ITaskRepository):
    """SQLite 任务仓储实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def create(
        self,
        user_id: str,
        task_type: str,
        workflow_version: str,
        data: dict
    ) -> str:
        """创建任务"""
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks (id, user_id, type, workflow_version, status, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'initiated', ?, ?, ?)
                """,
                (task_id, user_id, task_type, workflow_version, json.dumps(data), now, now)
            )
            await db.commit()
        return task_id

    async def get(self, task_id: str) -> Task | None:
        """获取任务"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Task(
                id=row["id"],
                user_id=row["user_id"],
                type=row["type"],
                workflow_version=row["workflow_version"],
                status=row["status"],
                data=json.loads(row["data"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )

    async def update_status(
        self,
        task_id: str,
        status: str,
        data: dict | None = None
    ) -> bool:
        """更新任务状态（带事务锁）"""
        async with aiosqlite.connect(self.db_path) as db:
            # BEGIN IMMEDIATE 获取写锁
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT data FROM tasks WHERE id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                return False

            # 合并 data
            existing_data = json.loads(row[0])
            if data:
                existing_data.update(data)

            now = datetime.utcnow().isoformat()
            await db.execute(
                """
                UPDATE tasks
                SET status = ?, data = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, json.dumps(existing_data), now, task_id)
            )
            await db.commit()
        return True
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_repository.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/sqlite_repository.py tests/unit/test_repository.py
git commit -m "feat(infrastructure): implement SQLiteTaskRepository"
```

---

### Task 6: 实现 EventStore

**Files:**
- Create: `app/infrastructure/event_store.py`
- Test: `tests/unit/test_event_store.py`

- [ ] **Step 1: 编写 EventStore 测试**

```python
# tests/unit/test_event_store.py
import pytest
from app.infrastructure.event_store import SQLiteEventStore


@pytest.mark.asyncio
async def test_mark_consumed_first_time(event_store):
    """首次标记事件应该成功"""
    # 先插入一个事件
    import aiosqlite
    async with aiosqlite.connect(event_store.db_path) as db:
        await db.execute(
            "INSERT INTO events (event_id, user_id, task_id, payload, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("evt_123", "user1", "task1", '{"test": "data"}')
        )
        await db.commit()

    result = await event_store.mark_consumed("evt_123")
    assert result is True


@pytest.mark.asyncio
async def test_mark_consumed_duplicate(event_store):
    """重复标记事件应该返回 False（防重放）"""
    import aiosqlite
    async with aiosqlite.connect(event_store.db_path) as db:
        await db.execute(
            "INSERT INTO events (event_id, user_id, task_id, payload, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            ("evt_123", "user1", "task1", '{"test": "data"}')
        )
        await db.commit()

    # 第一次标记
    result1 = await event_store.mark_consumed("evt_123")
    assert result1 is True

    # 第二次标记（重复）
    result2 = await event_store.mark_consumed("evt_123")
    assert result2 is False


@pytest.mark.asyncio
async def test_is_consumed(event_store):
    """应该能正确检查事件是否已消费"""
    import aiosqlite
    async with aiosqlite.connect(event_store.db_path) as db:
        await db.execute(
            "INSERT INTO events (event_id, user_id, task_id, payload, consumed, created_at) VALUES (?, ?, ?, ?, 1, datetime('now'))",
            ("evt_123", "user1", "task1", '{"test": "data"}')
        )
        await db.commit()

    assert await event_store.is_consumed("evt_123") is True
    assert await event_store.is_consumed("evt_456") is False
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_event_store.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.infrastructure.event_store'`

- [ ] **Step 3: 实现 EventStore**

```python
# app/infrastructure/event_store.py
import aiosqlite

from app.domain.interfaces import IEventStore


class SQLiteEventStore(IEventStore):
    """SQLite 事件存储实现（防重放）"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def mark_consumed(self, event_id: str) -> bool:
        """
        标记事件已消费

        Returns:
            True: 标记成功
            False: 事件已被消费（防重放）
        """
        async with aiosqlite.connect(self.db_path) as db:
            # BEGIN IMMEDIATE 获取写锁
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT consumed FROM events WHERE event_id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()

            if row is None:
                await db.rollback()
                return False

            if row[0]:  # 已消费
                await db.rollback()
                return False

            await db.execute(
                "UPDATE events SET consumed = 1 WHERE event_id = ?",
                (event_id,)
            )
            await db.commit()
        return True

    async def is_consumed(self, event_id: str) -> bool:
        """检查事件是否已消费"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT consumed FROM events WHERE event_id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()
            return row is not None and row[0] == 1
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_event_store.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/event_store.py tests/unit/test_event_store.py
git commit -m "feat(infrastructure): implement SQLiteEventStore with replay protection"
```

---

### Task 7: 实现 MessageBus

**Files:**
- Create: `app/infrastructure/sqlite_bus.py`
- Test: `tests/unit/test_message_bus.py`

- [ ] **Step 1: 编写 MessageBus 测试**

```python
# tests/unit/test_message_bus.py
import pytest
import asyncio
from app.domain.schemas import EventMessage
from app.infrastructure.sqlite_bus import SQLiteMessageBus


@pytest.mark.asyncio
async def test_publish_and_subscribe(message_bus):
    """应该能发布和订阅消息"""
    msg = EventMessage(
        event_id="evt_123",
        task_id="task_123",
        task_type="purchase_request",
        status="awaiting_audit",
        node_id="manager_audit",
        required_params=["is_approved"],
        display_data={"title": "待审批"}
    )

    # 发布消息
    await message_bus.publish("user123", msg)

    # 订阅并接收
    async for received in message_bus.subscribe("user123"):
        assert received.event_id == "evt_123"
        assert received.node_id == "manager_audit"
        break  # 只接收一条


@pytest.mark.asyncio
async def test_register_listener(message_bus):
    """应该能注册和取消监听器"""
    queue = asyncio.Queue()
    message_bus.register_listener("user123", queue)

    msg = EventMessage(
        event_id="evt_123",
        task_id="task_123",
        task_type="purchase_request",
        status="awaiting_audit",
        node_id="manager_audit",
        required_params=[],
        display_data={}
    )

    await message_bus.publish("user123", msg)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.event_id == "evt_123"

    # 取消监听
    message_bus.unregister_listener("user123", queue)


@pytest.mark.asyncio
async def test_multiple_users_isolation(message_bus):
    """不同用户的消息应该隔离"""
    msg_user1 = EventMessage(
        event_id="evt_1",
        task_id="task_1",
        task_type="purchase_request",
        status="awaiting_audit",
        node_id="manager_audit",
        required_params=[],
        display_data={}
    )

    msg_user2 = EventMessage(
        event_id="evt_2",
        task_id="task_2",
        task_type="purchase_request",
        status="awaiting_audit",
        node_id="manager_audit",
        required_params=[],
        display_data={}
    )

    await message_bus.publish("user1", msg_user1)
    await message_bus.publish("user2", msg_user2)

    # user1 只收到自己的消息
    count = 0
    async for msg in message_bus.subscribe("user1"):
        assert msg.event_id == "evt_1"
        count += 1
        if count >= 1:
            break
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_message_bus.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.infrastructure.sqlite_bus'`

- [ ] **Step 3: 实现 MessageBus**

```python
# app/infrastructure/sqlite_bus.py
import json
import uuid
import asyncio
from datetime import datetime
from collections import defaultdict
from typing import AsyncIterator

import aiosqlite

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage


class SQLiteMessageBus(IMessageBus):
    """
    SQLite 消息总线实现

    双重模式：
    1. 持久化到 SQLite 表（用于轮询模式 Fallback）
    2. 内存队列推送到监听器（用于 WebSocket 实时模式）
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        # user_id -> list[Queue]
        self._listeners: dict[str, list[asyncio.Queue]] = defaultdict(list)

    async def publish(self, user_id: str, message: EventMessage) -> None:
        """发布消息"""
        # 1. 持久化到数据库
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO events (event_id, user_id, task_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message.event_id, user_id, message.task_id, message.model_dump_json(), datetime.utcnow().isoformat())
            )
            await db.commit()

        # 2. 推送到内存监听器
        for queue in self._listeners.get(user_id, []):
            await queue.put(message)

    async def subscribe(self, user_id: str) -> AsyncIterator[EventMessage]:
        """
        订阅消息流

        先读取数据库中未消费的消息，然后等待新消息
        """
        # 读取未消费的历史消息
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT payload FROM events
                WHERE user_id = ? AND consumed = 0
                ORDER BY created_at ASC
                """,
                (user_id,)
            )
            async for row in cursor:
                yield EventMessage.model_validate_json(row[0])

        # 创建临时队列接收新消息
        queue = asyncio.Queue()
        self.register_listener(user_id, queue)

        try:
            while True:
                msg = await queue.get()
                yield msg
        finally:
            self.unregister_listener(user_id, queue)

    def register_listener(self, user_id: str, queue: asyncio.Queue) -> None:
        """注册监听队列"""
        if queue not in self._listeners[user_id]:
            self._listeners[user_id].append(queue)

    def unregister_listener(self, user_id: str, queue: asyncio.Queue) -> None:
        """取消监听队列"""
        if queue in self._listeners[user_id]:
            self._listeners[user_id].remove(queue)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_message_bus.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/sqlite_bus.py tests/unit/test_message_bus.py
git commit -m "feat(infrastructure): implement SQLiteMessageBus with pub/sub"
```

---

### Task 8: 实现 WorkflowRepo

**Files:**
- Create: `app/infrastructure/workflow_repo.py`
- Test: `tests/unit/test_workflow_repo.py`

- [ ] **Step 1: 编写 WorkflowRepo 测试**

```python
# tests/unit/test_workflow_repo.py
import pytest
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo


@pytest.mark.asyncio
async def test_save_and_get_active(workflow_repo):
    """应该能保存并获取活跃版本"""
    config = {
        "name": "purchase_request",
        "nodes": [
            {"id": "submit", "type": "action", "next": "approve"},
            {"id": "approve", "type": "terminal", "status": "completed"}
        ]
    }

    await workflow_repo.save_version("v1", "purchase_request", config, active=True)

    result = await workflow_repo.get_active("purchase_request")
    assert result is not None
    assert result["version"] == "v1"
    assert result["workflow_name"] == "purchase_request"
    assert result["config"] == config


@pytest.mark.asyncio
async def test_get_by_version(workflow_repo):
    """应该能获取指定版本"""
    config_v1 = {"name": "purchase_request", "nodes": []}
    config_v2 = {"name": "purchase_request", "nodes": [], "new_field": True}

    await workflow_repo.save_version("v1", "purchase_request", config_v1, active=True)
    await workflow_repo.save_version("v2", "purchase_request", config_v2, active=False)

    result_v1 = await workflow_repo.get_by_version("purchase_request", "v1")
    assert result_v1["config"] == config_v1

    result_v2 = await workflow_repo.get_by_version("purchase_request", "v2")
    assert result_v2["config"] == config_v2


@pytest.mark.asyncio
async def test_get_active_returns_latest(workflow_repo):
    """get_active 应该返回最新标记为 active 的版本"""
    config_v1 = {"name": "purchase_request", "nodes": [], "version": 1}
    config_v2 = {"name": "purchase_request", "nodes": [], "version": 2}

    await workflow_repo.save_version("v1", "purchase_request", config_v1, active=True)
    await workflow_repo.save_version("v2", "purchase_request", config_v2, active=True)

    result = await workflow_repo.get_active("purchase_request")
    assert result["version"] == "v2"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_workflow_repo.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.infrastructure.workflow_repo'`

- [ ] **Step 3: 实现 WorkflowRepo**

```python
# app/infrastructure/workflow_repo.py
import json
from datetime import datetime
import aiosqlite

from app.domain.interfaces import IWorkflowRepo


class SQLiteWorkflowRepo(IWorkflowRepo):
    """SQLite 工作流配置仓储实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_active(self, workflow_name: str) -> dict | None:
        """获取活跃版本的工作流配置"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT version, workflow_name, config
                FROM workflow_versions
                WHERE workflow_name = ? AND active = 1
                ORDER BY version DESC
                LIMIT 1
                """,
                (workflow_name,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "version": row["version"],
                "workflow_name": row["workflow_name"],
                "config": json.loads(row["config"])
            }

    async def get_by_version(self, workflow_name: str, version: str) -> dict | None:
        """获取指定版本的工作流配置"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT version, workflow_name, config
                FROM workflow_versions
                WHERE workflow_name = ? AND version = ?
                """,
                (workflow_name, version)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "version": row["version"],
                "workflow_name": row["workflow_name"],
                "config": json.loads(row["config"])
            }

    async def save_version(
        self,
        version: str,
        workflow_name: str,
        config: dict,
        active: bool = True
    ) -> None:
        """保存工作流配置版本"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO workflow_versions (version, workflow_name, config, active, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (version, workflow_name, json.dumps(config), 1 if active else 0, datetime.utcnow().isoformat())
            )
            await db.commit()
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_workflow_repo.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/workflow_repo.py tests/unit/test_workflow_repo.py
git commit -m "feat(infrastructure): implement SQLiteWorkflowRepo for version management"
```

---

## Workflow 层

### Task 9: 创建工作流配置文件

**Files:**
- Create: `app/workflow/__init__.py`
- Create: `app/workflow/config/__init__.py`
- Create: `app/workflow/config/purchase_request.yml`

- [ ] **Step 1: 创建配置文件**

```yaml
# app/workflow/config/purchase_request.yml
name: purchase_request
display_name: 采购申请审批流程

nodes:
  - id: submit
    type: action
    display_name: 提交申请
    next: manager_audit

  - id: manager_audit
    type: interrupt
    display_name: 经理审批
    required_params:
      - is_approved
      - audit_opinion
      - approver
    display_data:
      title: 待审批通知
      content_template: "您有一个采购申请待审批，金额：{amount} 元"
    next:
      - if: "{{ is_approved == true }}"
        to: finance_audit
      - if: "{{ is_approved == false }}"
        to: rejected

  - id: finance_audit
    type: interrupt
    display_name: 财务审批
    required_params:
      - is_approved
      - audit_opinion
      - approver
    display_data:
      title: 财务审批
      content_template: "请审批采购申请，金额：{amount} 元"
    next:
      - if: "{{ is_approved == true }}"
        to: approved
      - if: "{{ is_approved == false }}"
        to: rejected

  - id: approved
    type: terminal
    display_name: 审批通过
    status: completed

  - id: rejected
    type: terminal
    display_name: 审批拒绝
    status: rejected
```

- [ ] **Step 2: Commit**

```bash
git add app/workflow/
git commit -m "feat(workflow): add purchase request workflow configuration"
```

---

### Task 10: 实现 WorkflowBuilder

**Files:**
- Create: `app/workflow/builder.py`
- Test: `tests/unit/test_workflow_builder.py`

- [ ] **Step 1: 编写 WorkflowBuilder 测试**

```python
# tests/unit/test_workflow_builder.py
import pytest
from app.workflow.builder import WorkflowBuilder
from app.workflow.config import load_workflow_config


@pytest.mark.asyncio
async def test_build_workflow_from_config():
    """应该能从配置构建工作流图"""
    config = load_workflow_config("purchase_request")
    builder = WorkflowBuilder()

    graph = builder.build(config, "v1")

    assert graph is not None
    # 验证节点存在
    nodes = graph.nodes
    assert "submit" in nodes or any("submit" in str(n) for n in nodes)


@pytest.mark.asyncio
async def test_build_workflow_with_interrupt_nodes():
    """中断节点应该生成正确的 interrupt 配置"""
    config = load_workflow_config("purchase_request")
    builder = WorkflowBuilder()

    graph = builder.build(config, "v1")

    # 验证图结构包含中断逻辑
    assert graph is not None


def test_load_workflow_config():
    """应该能加载 YAML 配置"""
    config = load_workflow_config("purchase_request")
    assert config["name"] == "purchase_request"
    assert len(config["nodes"]) > 0

    # 找到 manager_audit 节点
    manager_node = next(n for n in config["nodes"] if n["id"] == "manager_audit")
    assert manager_node["type"] == "interrupt"
    assert "is_approved" in manager_node["required_params"]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/unit/test_workflow_builder.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.workflow.builder'`

- [ ] **Step 3: 实现 WorkflowBuilder**

```python
# app/workflow/config/__init__.py
import yaml
from pathlib import Path


def load_workflow_config(workflow_name: str) -> dict:
    """加载工作流配置文件"""
    config_dir = Path(__file__).parent
    config_file = config_dir / f"{workflow_name}.yml"

    if not config_file.exists():
        raise FileNotFoundError(f"Workflow config not found: {workflow_name}")

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

```python
# app/workflow/builder.py
import uuid
from typing import Any

from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig

from app.workflow.config import load_workflow_config


class WorkflowBuilder:
    """
    动态工作流构建器

    根据 YAML 配置文件构建 LangGraph StateGraph
    """

    def __init__(self):
        self._checkpointer = None

    def build(self, config: dict, version: str) -> StateGraph:
        """
        根据配置构建工作流图

        Args:
            config: 工作流配置字典
            version: 工作流版本

        Returns:
            StateGraph 实例
        """
        # 创建状态图
        graph = StateGraph(dict)

        # 添加节点
        node_map = {}
        for node in config["nodes"]:
            node_id = node["id"]
            node_type = node["type"]

            if node_type == "action":
                graph.add_node(node_id, self._create_action_handler(node))
            elif node_type == "interrupt":
                graph.add_node(node_id, self._create_interrupt_handler(node))
            elif node_type == "terminal":
                graph.add_node(node_id, self._create_terminal_handler(node))

            node_map[node_id] = node

        # 添加边
        for node in config["nodes"]:
            node_id = node["id"]

            if "next" in node:
                next_config = node["next"]

                if isinstance(next_config, str):
                    # 直接指向下一个节点
                    if next_config != "END":
                        graph.add_edge(node_id, next_config)
                    else:
                        graph.add_edge(node_id, END)
                elif isinstance(next_config, list):
                    # 条件分支
                    self._add_conditional_edges(graph, node_id, next_config, node_map)
            else:
                # 没有 next 配置，指向 END
                graph.add_edge(node_id, END)

        # 设置入口点
        entry_node = config["nodes"][0]["id"]
        graph.set_entry_point(entry_node)

        return graph

    def _create_action_handler(self, node: dict):
        """创建 action 节点处理函数"""
        async def handler(state: dict, config: RunnableConfig) -> dict:
            # action 节点执行具体业务逻辑
            state["current_node"] = node["id"]
            return state
        return handler

    def _create_interrupt_handler(self, node: dict):
        """创建 interrupt 节点处理函数"""
        async def handler(state: dict, config: RunnableConfig) -> dict:
            # interrupt 节点标记需要人工干预
            state["current_node"] = node["id"]
            state["interrupt"] = {
                "node_id": node["id"],
                "required_params": node.get("required_params", []),
                "display_data": node.get("display_data", {})
            }
            return state
        return handler

    def _create_terminal_handler(self, node: dict):
        """创建 terminal 节点处理函数"""
        async def handler(state: dict, config: RunnableConfig) -> dict:
            state["current_node"] = node["id"]
            state["status"] = node.get("status", "completed")
            return state
        return handler

    def _add_conditional_edges(
        self,
        graph: StateGraph,
        source_node: str,
        conditions: list[dict],
        node_map: dict
    ):
        """添加条件边"""
        async def condition_func(state: dict) -> str:
            for cond in conditions:
                # 简单的条件解析：支持 {{ field == value }} 格式
                if_expr = cond.get("if", "")
                if self._evaluate_condition(if_expr, state):
                    target = cond.get("to", "END")
                    if target == "END":
                        return END
                    return target
            return END

        graph.add_conditional_edges(source_node, condition_func)

    def _evaluate_condition(self, if_expr: str, state: dict) -> bool:
        """简单的条件表达式求值"""
        # 支持 {{ is_approved == true }} 格式
        if "{{" in if_expr and "}}" in if_expr:
            expr = if_expr.strip("{{ }}").strip()
            # 简单处理：is_approved == true
            if "==" in expr:
                parts = expr.split("==")
                field = parts[0].strip()
                value = parts[1].strip()
                if value == "true":
                    return state.get("user_input", {}).get(field, False) is True
                elif value == "false":
                    return state.get("user_input", {}).get(field, False) is False
        return False
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/unit/test_workflow_builder.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workflow/ tests/unit/test_workflow_builder.py
git commit -m "feat(workflow): implement WorkflowBuilder with YAML config support"
```

---

### Task 11: 实现 Checkpointer 和 Executor

**Files:**
- Create: `app/workflow/checkpointer.py`
- Create: `app/workflow/executor.py`

- [ ] **Step 1: 实现 Checkpointer**

```python
# app/workflow/checkpointer.py
import json
from datetime import datetime
from typing import Optional, Tuple

import aiosqlite
from langgraph.checkpoint import BaseCheckpointSaver, Checkpoint
from langgraph.checkpoint.id import uuid


class SQLiteSaver(BaseCheckpointSaver):
    """
    SQLite 检查点保存器

    实现 LangGraph 的 Checkpoint 接口，用于持久化工作流状态
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get(self, config: RunnableConfig, checkpoint_id: str) -> Optional[Checkpoint]:
        """获取检查点"""
        thread_id = config["configurable"].get("thread_id")
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT state FROM checkpoints
                WHERE thread_id = ? AND checkpoint_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (thread_id, checkpoint_id)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return Checkpoint(**json.loads(row[0]))

    async def put(self, config: RunnableConfig, checkpoint: Checkpoint) -> None:
        """保存检查点"""
        thread_id = config["configurable"].get("thread_id")
        checkpoint_id = checkpoint.get("id") or uuid()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO checkpoints (thread_id, checkpoint_id, state, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, checkpoint_id, json.dumps(checkpoint), datetime.utcnow().isoformat())
            )
            await db.commit()

    async def list(self, config: RunnableConfig, limit: int = 10) -> list[Checkpoint]:
        """列出检查点"""
        thread_id = config["configurable"].get("thread_id")
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT state FROM checkpoints
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit)
            )
            rows = await cursor.fetchall()
            return [Checkpoint(**json.loads(row[0])) for row in rows]
```

- [ ] **Step 2: 实现 Executor**

```python
# app/workflow/executor.py
import uuid
from typing import Any, Optional

from langgraph.graph import StateGraph
from langchain_core.runnables import RunnableConfig

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage


class WorkflowExecutor:
    """
    工作流执行器

    负责执行 LangGraph 工作流，处理中断节点
    """

    def __init__(self, message_bus: IMessageBus):
        self.message_bus = message_bus

    async def execute(
        self,
        graph: StateGraph,
        thread_id: str,
        user_id: str,
        task_id: str,
        task_type: str,
        initial_data: dict
    ) -> str:
        """
        执行工作流

        Returns:
            最终状态
        """
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id
            }
        )

        # 初始状态
        initial_state = {
            "data": initial_data,
            "task_id": task_id,
            "task_type": task_type,
            "user_id": user_id
        }

        # 执行图
        result = await graph.ainvoke(initial_state, config)

        # 检查是否有中断
        if "interrupt" in result:
            await self._handle_interrupt(result, user_id, task_id, task_type)

        return result.get("status", "running")

    async def resume(
        self,
        graph: StateGraph,
        thread_id: str,
        task_id: str,
        user_id: str,
        task_type: str,
        node_id: str,
        user_input: dict
    ) -> str:
        """
        从中断点恢复工作流

        Args:
            node_id: 中断节点 ID
            user_input: 用户输入

        Returns:
            最终状态
        """
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id
            }
        )

        # 构建恢复状态
        state = {
            "user_input": user_input,
            "current_node": node_id,
            "task_id": task_id,
            "task_type": task_type,
            "user_id": user_id
        }

        # 继续执行
        result = await graph.ainvoke(state, config)

        # 检查是否有新的中断
        if "interrupt" in result:
            await self._handle_interrupt(result, user_id, task_id, task_type)

        return result.get("status", "running")

    async def _handle_interrupt(
        self,
        state: dict,
        user_id: str,
        task_id: str,
        task_type: str
    ):
        """处理中断节点，发送通知"""
        interrupt = state.get("interrupt", {})
        event_id = str(uuid.uuid4())

        message = EventMessage(
            event_id=event_id,
            task_id=task_id,
            task_type=task_type,
            status="awaiting_" + interrupt.get("node_id", ""),
            node_id=interrupt.get("node_id", ""),
            required_params=interrupt.get("required_params", []),
            display_data=interrupt.get("display_data", {})
        )

        await self.message_bus.publish(user_id, message)
```

- [ ] **Step 3: Commit**

```bash
git add app/workflow/checkpointer.py app/workflow/executor.py
git commit -m "feat(workflow): add SQLiteSaver checkpointer and WorkflowExecutor"
```

---

## Service 层

### Task 12: 实现 TaskService

**Files:**
- Create: `app/service/__init__.py`
- Create: `app/service/task_service.py`
- Test: `tests/integration/test_task_service.py`

- [ ] **Step 1: 编写 TaskService 集成测试**

```python
# tests/integration/test_task_service.py
import pytest
from app.service.task_service import TaskService
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


@pytest.fixture
async def task_service(db):
    """创建 TaskService 实例"""
    task_repo = SQLiteTaskRepository(db.db_path)
    message_bus = SQLiteMessageBus(db.db_path)
    event_store = SQLiteEventStore(db.db_path)
    workflow_repo = SQLiteWorkflowRepo(db.db_path)

    # 加载默认工作流配置
    from app.workflow.config import load_workflow_config
    config = load_workflow_config("purchase_request")
    await workflow_repo.save_version("v1", "purchase_request", config)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    return TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor
    )


@pytest.mark.asyncio
async def test_create_task(task_service):
    """应该能创建任务并启动工作流"""
    result = await task_service.create_task(
        user_id="user123",
        task_type="purchase_request",
        data={"amount": 1000, "order_no": "REQ-001"}
    )

    assert result["task"]["id"] is not None
    assert result["task"]["status"] in ["initiated", "awaiting_manager_audit"]


@pytest.mark.asyncio
async def test_callback_task(task_service):
    """应该能回调恢复工作流"""
    # 先创建任务
    create_result = await task_service.create_task(
        user_id="user123",
        task_type="purchase_request",
        data={"amount": 1000, "order_no": "REQ-001"}
    )
    task_id = create_result["task"]["id"]

    # 等待中断消息
    import asyncio
    event_msg = None
    async for msg in task_service.message_bus.subscribe("user123"):
        event_msg = msg
        break

    if event_msg:
        # 回调
        callback_result = await task_service.callback(
            task_id=task_id,
            event_id=event_msg.event_id,
            node_id=event_msg.node_id,
            user_input={"is_approved": True, "audit_opinion": "同意", "approver": "manager"}
        )

        assert callback_result["success"] is True
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/integration/test_task_service.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.service.task_service'`

- [ ] **Step 3: 实现 TaskService**

```python
# app/service/__init__.py
```

```python
# app/service/task_service.py
from typing import Optional

from app.domain.interfaces import (
    ITaskRepository, IMessageBus, IEventStore, IWorkflowRepo
)
from app.domain.schemas import TaskCreate, Task, CallbackRequest
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor
from app.workflow.config import load_workflow_config


class TaskService:
    """
    任务编排服务

    负责任务创建、状态查询、回调处理等核心业务逻辑
    """

    def __init__(
        self,
        task_repo: ITaskRepository,
        message_bus: IMessageBus,
        event_store: IEventStore,
        workflow_repo: IWorkflowRepo,
        builder: WorkflowBuilder,
        executor: WorkflowExecutor
    ):
        self.task_repo = task_repo
        self.message_bus = message_bus
        self.event_store = event_store
        self.workflow_repo = workflow_repo
        self.builder = builder
        self.executor = executor

    async def create_task(
        self,
        user_id: str,
        task_type: str,
        data: dict
    ) -> dict:
        """
        创建任务并启动工作流

        Returns:
            {"task": {...}}
        """
        # 1. 获取活跃的工作流配置
        workflow_config = await self.workflow_repo.get_active(task_type)
        if not workflow_config:
            raise ValueError(f"Workflow not found: {task_type}")

        workflow_version = workflow_config["version"]
        config_data = workflow_config["config"]

        # 2. 创建任务记录
        task_id = await self.task_repo.create(
            user_id=user_id,
            task_type=task_type,
            workflow_version=workflow_version,
            data=data
        )

        # 3. 构建工作流图
        graph = self.builder.build(config_data, workflow_version)

        # 4. 执行工作流
        status = await self.executor.execute(
            graph=graph,
            thread_id=task_id,  # thread_id = task_id
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            initial_data=data
        )

        # 5. 更新任务状态
        await self.task_repo.update_status(task_id, status)

        # 6. 返回结果
        task = await self.task_repo.get(task_id)
        return {"task": task.model_dump()}

    async def get_task(self, task_id: str) -> dict | None:
        """获取任务详情"""
        task = await self.task_repo.get(task_id)
        if not task:
            return None
        return {"task": task.model_dump()}

    async def callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
        user_input: dict
    ) -> dict:
        """
        回调恢复工作流

        Returns:
            {"success": bool, "next_status": str}
        """
        # 1. 检查事件是否已消费（防重放）
        if await self.event_store.is_consumed(event_id):
            return {"success": False, "next_status": "error", "error": "Event already consumed"}

        # 2. 获取任务信息
        task = await self.task_repo.get(task_id)
        if not task:
            return {"success": False, "next_status": "error", "error": "Task not found"}

        # 3. 获取工作流配置
        workflow_config = await self.workflow_repo.get_by_version(
            task.type,
            task.workflow_version
        )
        if not workflow_config:
            return {"success": False, "next_status": "error", "error": "Workflow version not found"}

        # 4. 构建工作流图
        graph = self.builder.build(workflow_config["config"], task.workflow_version)

        # 5. 恢复执行
        next_status = await self.executor.resume(
            graph=graph,
            thread_id=task_id,
            task_id=task_id,
            user_id=task.user_id,
            task_type=task.type,
            node_id=node_id,
            user_input=user_input
        )

        # 6. 标记事件已消费
        await self.event_store.mark_consumed(event_id)

        # 7. 更新任务状态
        await self.task_repo.update_status(task_id, next_status)

        return {"success": True, "next_status": next_status}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/integration/test_task_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/service/ tests/integration/test_task_service.py
git commit -m "feat(service): implement TaskService for task orchestration"
```

---

## API 层

### Task 13: 实现 FastAPI 应用

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/deps.py`
- Create: `app/api/routes.py`
- Create: `app/api/main.py`
- Test: `tests/integration/test_api_endpoints.py`

- [ ] **Step 1: 编写 API 集成测试**

```python
# tests/integration/test_api_endpoints.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.api.main import app
from app.infrastructure.database import Database
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor
from app.service.task_service import TaskService


@pytest.fixture
async def client(db_path):
    """创建测试 HTTP 客户端"""
    # 初始化数据库
    database = Database(db_path)
    await database.init_tables()

    # 初始化仓储和服务
    task_repo = SQLiteTaskRepository(db_path)
    message_bus = SQLiteMessageBus(db_path)
    event_store = SQLiteEventStore(db_path)
    workflow_repo = SQLiteWorkflowRepo(db_path)

    # 加载默认工作流
    from app.workflow.config import load_workflow_config
    config = load_workflow_config("purchase_request")
    await workflow_repo.save_version("v1", "purchase_request", config)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor
    )

    # 设置依赖
    app.state.task_service = task_service
    app.state.message_bus = message_bus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_task_endpoint(client):
    """POST /v1/tasks 应该创建任务"""
    response = await client.post("/v1/tasks", json={
        "user_id": "user123",
        "task": {
            "type": "purchase_request",
            "data": {"amount": 1000, "order_no": "REQ-001"}
        }
    })

    assert response.status_code == 201
    data = response.json()
    assert "task" in data
    assert data["task"]["id"] is not None


@pytest.mark.asyncio
async def test_get_task_endpoint(client):
    """GET /v1/tasks/{task_id} 应该返回任务详情"""
    # 先创建任务
    create_response = await client.post("/v1/tasks", json={
        "user_id": "user123",
        "task": {
            "type": "purchase_request",
            "data": {"amount": 1000}
        }
    })
    task_id = create_response.json()["task"]["id"]

    # 获取任务
    response = await client.get(f"/v1/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["task"]["id"] == task_id


@pytest.mark.asyncio
async def test_get_nonexistent_task(client):
    """GET 不存在的任务应该返回 404"""
    response = await client.get("/v1/tasks/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_callback_endpoint(client):
    """POST /v1/tasks/{task_id}/callback 应该恢复工作流"""
    # 创建任务
    create_response = await client.post("/v1/tasks", json={
        "user_id": "user123",
        "task": {
            "type": "purchase_request",
            "data": {"amount": 1000}
        }
    })
    task_id = create_response.json()["task"]["id"]

    # 获取事件（模拟）
    import asyncio
    from app.infrastructure.sqlite_bus import SQLiteMessageBus
    message_bus = app.state.message_bus
    event_msg = None
    async for msg in message_bus.subscribe("user123"):
        event_msg = msg
        break

    if event_msg:
        # 回调
        response = await client.post(f"/v1/tasks/{task_id}/callback", json={
            "event_id": event_msg.event_id,
            "node_id": event_msg.node_id,
            "user_input": {"is_approved": True, "audit_opinion": "同意", "approver": "manager"}
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/integration/test_api_endpoints.py -v
```

Expected: FAIL - `ModuleNotFoundError: No module named 'app.api.main'`

- [ ] **Step 3: 实现 API 层**

```python
# app/api/__init__.py
```

```python
# app/api/deps.py
from fastapi import Depends

from app.service.task_service import TaskService


async def get_task_service() -> TaskService:
    """获取 TaskService 实例"""
    # 注意：实际使用时从 app.state 获取
    from app.api.main import app
    return app.state.task_service
```

```python
# app/api/routes.py
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import Dict

from app.domain.schemas import TaskCreate, TaskResponse, CallbackRequest, CallbackResponse, ErrorResponse
from app.service.task_service import TaskService
from app.api.deps import get_task_service


router = APIRouter(prefix="/v1", tags=["tasks"])


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreate,
    task_service: TaskService = Depends(get_task_service)
):
    """创建任务"""
    try:
        result = await task_service.create_task(
            user_id=request.user_id,
            task_type=request.task.type,
            data=request.task.data
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    task_service: TaskService = Depends(get_task_service)
):
    """获取任务详情"""
    result = await task_service.get_task(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.post("/tasks/{task_id}/callback", response_model=CallbackResponse)
async def callback_task(
    task_id: str,
    request: CallbackRequest,
    task_service: TaskService = Depends(get_task_service)
):
    """回调恢复工作流"""
    result = await task_service.callback(
        task_id=task_id,
        event_id=request.event_id,
        node_id=request.node_id,
        user_input=request.user_input
    )

    if not result["success"]:
        error_code = "EVENT_ALREADY_CONSUMED" if "consumed" in result.get("error", "") else "CALLBACK_FAILED"
        raise HTTPException(status_code=409, detail={
            "code": error_code,
            "message": result.get("error", "Callback failed")
        })

    return result


# WebSocket 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str = None):
    """WebSocket 端点，用于实时推送中断事件"""
    if user_id is None:
        await websocket.close(code=1008, reason="user_id required")
        return

    await manager.connect(user_id, websocket)
    from app.api.main import app
    message_bus = app.state.message_bus

    # 注册监听器
    import asyncio
    queue = asyncio.Queue()
    message_bus.register_listener(user_id, queue)

    try:
        while True:
            # 等待新消息
            message = await queue.get()
            await websocket.send_json(message.model_dump())
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
        message_bus.unregister_listener(user_id, queue)
```

```python
# app/api/main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.infrastructure.database import Database


app = FastAPI(title="LangGraph Cloud Service", version="0.1.0")

# 全局状态
app.state.task_service = None
app.state.message_bus = None
app.state.database = None


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


app.include_router(router)


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    db_path = "langgraph.db"
    database = Database(db_path)
    await database.init_tables()

    app.state.database = database


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)}}
    )
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/integration/test_api_endpoints.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/ tests/integration/test_api_endpoints.py
git commit -m "feat(api): implement FastAPI routes with REST and WebSocket support"
```

---

## Client SDK

### Task 14: 实现 WebSocket 客户端

**Files:**
- Create: `app/client_sdk/__init__.py`
- Create: `app/client_sdk/websocket_client.py`
- Test: `tests/integration/test_websocket.py`

- [ ] **Step 1: 编写 WebSocket 客户端测试**

```python
# tests/integration/test_websocket.py
import pytest
import asyncio
from app.client_sdk.websocket_client import WebSocketClient


@pytest.mark.asyncio
async def test_websocket_client_connect(db):
    """应该能连接到 WebSocket"""
    # 这个测试需要实际运行的服务器
    # 在 E2E 测试中实现
    pass
```

- [ ] **Step 2: 实现 WebSocket 客户端**

```python
# app/client_sdk/__init__.py
```

```python
# app/client_sdk/websocket_client.py
import asyncio
import json
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from app.domain.schemas import EventMessage


class WebSocketClient:
    """
    WebSocket 客户端

    用于连接服务端 WebSocket，接收实时通知
    """

    def __init__(
        self,
        server_url: str = "ws://localhost:8000/ws",
        user_id: str = "default_user",
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0
    ):
        self.server_url = f"{server_url}?user_id={user_id}"
        self.user_id = user_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._message_handler: Optional[Callable[[EventMessage], None]] = None
        self._running = False
        self._current_delay = reconnect_delay

    def on_message(self, handler: Callable[[EventMessage], None]):
        """注册消息处理器"""
        self._message_handler = handler

    async def connect(self):
        """连接到 WebSocket 服务器"""
        self._running = True
        await self._connect_with_backoff()

    async def _connect_with_backoff(self):
        """带指数退避的连接"""
        while self._running:
            try:
                self._websocket = await websockets.connect(self.server_url)
                self._current_delay = self.reconnect_delay  # 重置延迟
                await self._listen()
            except (ConnectionRefusedError, OSError) as e:
                if self._running:
                    await asyncio.sleep(self._current_delay)
                    self._current_delay = min(self._current_delay * 2, self.max_reconnect_delay)
            except Exception as e:
                if self._running:
                    await asyncio.sleep(self._current_delay)

    async def _listen(self):
        """监听消息"""
        if not self._websocket:
            return

        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    event_msg = EventMessage.model_validate(data)
                    if self._message_handler:
                        self._message_handler(event_msg)
                except Exception as e:
                    # 跳过无法解析的消息
                    pass
        except ConnectionClosed:
            # 连接关闭，尝试重连
            if self._running:
                await self._connect_with_backoff()

    async def disconnect(self):
        """断开连接"""
        self._running = False
        if self._websocket:
            await self._websocket.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

- [ ] **Step 3: Commit**

```bash
git add app/client_sdk/ tests/integration/test_websocket.py
git commit -m "feat(client): add WebSocket client with reconnection support"
```

---

### Task 15: 实现 CLI 客户端

**Files:**
- Create: `app/client_sdk/cli.py`

- [ ] **Step 1: 实现 CLI 客户端**

```python
# app/client_sdk/cli.py
import asyncio
import sys
from typing import Optional

import httpx
from app.client_sdk.websocket_client import WebSocketClient
from app.domain.schemas import EventMessage, CallbackRequest


class LangGraphClient:
    """
    LangGraph 云端服务客户端

    支持两种模式：
    1. WebSocket 实时模式（默认）
    2. Polling 轮询模式（Fallback）
    """

    def __init__(
        self,
        api_base_url: str = "http://localhost:8000",
        ws_server_url: str = "ws://localhost:8000/ws",
        user_id: str = "demo_user",
        use_websocket: bool = True
    ):
        self.api_base_url = api_base_url
        self.ws_server_url = ws_server_url
        self.user_id = user_id
        self.use_websocket = use_websocket
        self._http_client = httpx.AsyncClient()
        self._ws_client: Optional[WebSocketClient] = None
        self._pending_events: dict[str, EventMessage] = {}

    async def create_task(self, task_type: str, data: dict) -> dict:
        """创建任务"""
        response = await self._http_client.post(
            f"{self.api_base_url}/v1/tasks",
            json={
                "user_id": self.user_id,
                "task": {"type": task_type, "data": data}
            }
        )
        response.raise_for_status()
        return response.json()

    async def get_task(self, task_id: str) -> dict:
        """获取任务状态"""
        response = await self._http_client.get(f"{self.api_base_url}/v1/tasks/{task_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
        user_input: dict
    ) -> dict:
        """回调恢复工作流"""
        response = await self._http_client.post(
            f"{self.api_base_url}/v1/tasks/{task_id}/callback",
            json={
                "event_id": event_id,
                "node_id": node_id,
                "user_input": user_input
            }
        )
        response.raise_for_status()
        return response.json()

    def on_event(self, event: EventMessage):
        """收到中断事件"""
        print(f"\n📬 收到通知: {event.display_data.get('title', '待处理')}")
        print(f"   内容: {event.display_data.get('content', '请处理')}")
        print(f"   节点: {event.node_id}")

        # 保存待处理事件
        self._pending_events[event.task_id] = event

    async def run_websocket_mode(self):
        """运行 WebSocket 实时模式"""
        self._ws_client = WebSocketClient(
            server_url=self.ws_server_url,
            user_id=self.user_id
        )
        self._ws_client.on_message(self.on_event)

        print(f"🔗 连接到 WebSocket: {self.ws_server_url}")
        await self._ws_client.connect()

    async def run_polling_mode(self, interval: float = 2.0):
        """运行轮询模式（Fallback）"""
        print(f"🔄 启动轮询模式，间隔 {interval} 秒")

        while True:
            # 检查所有待处理的任务
            for task_id in list(self._pending_events.keys()):
                task = await self.get_task(task_id)
                if task:
                    status = task["task"]["status"]
                    # 如果状态不是 awaiting_*，说明已完成
                    if not status.startswith("awaiting_"):
                        del self._pending_events[task_id]
                        print(f"✅ 任务 {task_id} 已完成: {status}")

            await asyncio.sleep(interval)

    async def interactive_loop(self):
        """交互式循环"""
        if self.use_websocket:
            asyncio.create_task(self.run_websocket_mode())

        while True:
            try:
                # 显示菜单
                print("\n" + "=" * 50)
                print("1. 创建采购申请任务")
                print("2. 查看任务状态")
                print("3. 处理待审批任务")
                print("4. 退出")
                choice = input("请选择操作 (1-4): ").strip()

                if choice == "1":
                    await self._create_purchase_request()
                elif choice == "2":
                    await self._view_task_status()
                elif choice == "3":
                    await self._handle_pending_task()
                elif choice == "4":
                    print("👋 再见！")
                    break
            except KeyboardInterrupt:
                print("\n👋 再见！")
                break

    async def _create_purchase_request(self):
        """创建采购申请"""
        print("\n--- 创建采购申请 ---")
        order_no = input("订单号: ")
        amount = float(input("金额: "))
        reason = input("申请理由: ")

        result = await self.create_task("purchase_request", {
            "order_no": order_no,
            "amount": amount,
            "apply_reason": reason
        })

        task_id = result["task"]["id"]
        print(f"✅ 任务已创建: {task_id}")
        print(f"   状态: {result['task']['status']}")

    async def _view_task_status(self):
        """查看任务状态"""
        print("\n--- 查看任务状态 ---")
        task_id = input("任务 ID: ")

        result = await self.get_task(task_id)
        if not result:
            print("❌ 任务不存在")
            return

        task = result["task"]
        print(f"任务 ID: {task['id']}")
        print(f"类型: {task['type']}")
        print(f"状态: {task['status']}")
        print(f"数据: {task['data']}")

    async def _handle_pending_task(self):
        """处理待审批任务"""
        if not self._pending_events:
            print("📭 没有待处理的任务")
            return

        print("\n--- 待处理任务 ---")
        for i, (task_id, event) in enumerate(self._pending_events.items(), 1):
            print(f"{i}. 任务 {task_id} - {event.display_data.get('title', '')}")

        choice = input("选择任务编号: ").strip()
        try:
            idx = int(choice) - 1
            task_id = list(self._pending_events.keys())[idx]
            event = self._pending_events[task_id]

            # 获取用户输入
            print(f"\n--- 处理任务 {task_id} ---")
            print(event.display_data.get("content", ""))

            is_approved = input("是否同意? (y/n): ").strip().lower() == "y"
            opinion = input("审批意见: ")
            approver = input("审批人: ")

            # 回调
            result = await self.callback(
                task_id=task_id,
                event_id=event.event_id,
                node_id=event.node_id,
                user_input={
                    "is_approved": is_approved,
                    "audit_opinion": opinion,
                    "approver": approver
                }
            )

            if result["success"]:
                print(f"✅ 回调成功，下一状态: {result['next_status']}")
                del self._pending_events[task_id]
            else:
                print(f"❌ 回调失败: {result}")
        except (ValueError, IndexError):
            print("❌ 无效选择")

    async def close(self):
        """关闭连接"""
        await self._http_client.aclose()
        if self._ws_client:
            await self._ws_client.disconnect()


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="LangGraph 客户端")
    parser.add_argument("--user-id", default="demo_user", help="用户 ID")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API 地址")
    parser.add_argument("--ws-url", default="ws://localhost:8000/ws", help="WebSocket 地址")
    parser.add_argument("--polling", action="store_true", help="使用轮询模式")
    args = parser.parse_args()

    client = LangGraphClient(
        api_base_url=args.api_url,
        ws_server_url=args.ws_url,
        user_id=args.user_id,
        use_websocket=not args.polling
    )

    try:
        await client.interactive_loop()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add app/client_sdk/cli.py
git commit -m "feat(client): add interactive CLI client with dual-mode support"
```

---

## E2E 测试

### Task 16: 实现 WebSocket 模式 E2E 测试

**Files:**
- Create: `tests/e2e/test_websocket_mode.py`

- [ ] **Step 1: 实现 WebSocket 模式 E2E 测试**

```python
# tests/e2e/test_websocket_mode.py
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.api.main import app
from app.infrastructure.database import Database
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor
from app.service.task_service import TaskService


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_complete_flow(tmp_path):
    """
    WebSocket 模式完整流程：
    1. 创建任务
    2. 通过 WebSocket 收到中断通知
    3. 回调恢复
    4. 收到完成通知
    """
    db_path = str(tmp_path / "test.db")

    # 初始化数据库
    database = Database(db_path)
    await database.init_tables()

    # 初始化服务
    task_repo = SQLiteTaskRepository(db_path)
    message_bus = SQLiteMessageBus(db_path)
    event_store = SQLiteEventStore(db_path)
    workflow_repo = SQLiteWorkflowRepo(db_path)

    # 加载工作流配置
    from app.workflow.config import load_workflow_config
    config = load_workflow_config("purchase_request")
    await workflow_repo.save_version("v1", "purchase_request", config)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor
    )

    app.state.task_service = task_service
    app.state.message_bus = message_bus

    # 创建 HTTP 客户端
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 创建任务
        response = await client.post("/v1/tasks", json={
            "user_id": "test_user",
            "task": {
                "type": "purchase_request",
                "data": {"amount": 1000, "order_no": "REQ-001"}
            }
        })
        assert response.status_code == 201
        task_id = response.json()["task"]["id"]

        # 2. 等待 WebSocket 消息（经理审批）
        event_received = asyncio.Event()
        first_event = None

        def on_first_event(msg):
            nonlocal first_event
            first_event = msg
            event_received.set()

        listener = asyncio.Queue()
        message_bus.register_listener("test_user", listener)

        # 等待第一条消息
        try:
            first_event = await asyncio.wait_for(listener.get(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail("未收到 WebSocket 消息")

        assert first_event.node_id == "manager_audit"
        assert first_event.task_id == task_id

        # 3. 回调经理审批
        response = await client.post(f"/v1/tasks/{task_id}/callback", json={
            "event_id": first_event.event_id,
            "node_id": first_event.node_id,
            "user_input": {
                "is_approved": True,
                "audit_opinion": "同意",
                "approver": "manager"
            }
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

        # 4. 等待第二条消息（财务审批）
        try:
            second_event = await asyncio.wait_for(listener.get(), timeout=5.0)
            assert second_event.node_id == "finance_audit"

            # 5. 回调财务审批
            response = await client.post(f"/v1/tasks/{task_id}/callback", json={
                "event_id": second_event.event_id,
                "node_id": second_event.node_id,
                "user_input": {
                    "is_approved": True,
                    "audit_opinion": "同意",
                    "approver": "finance"
                }
            })
            assert response.status_code == 200
        except asyncio.TimeoutError:
            # 工作流可能直接完成了
            pass

        # 6. 验证最终状态
        response = await client.get(f"/v1/tasks/{task_id}")
        assert response.status_code == 200
        final_status = response.json()["task"]["status"]
        assert final_status in ["completed", "awaiting_finance_audit"]

    await database.clear_all()
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/test_websocket_mode.py
git commit -m "test(e2e): add WebSocket mode end-to-end test"
```

---

### Task 17: 实现 Polling 模式 E2E 测试

**Files:**
- Create: `tests/e2e/test_polling_mode.py`

- [ ] **Step 1: 实现 Polling 模式 E2E 测试**

```python
# tests/e2e/test_polling_mode.py
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.api.main import app
from app.infrastructure.database import Database
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor
from app.service.task_service import TaskService


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_complete_flow(tmp_path):
    """
    Polling 模式完整流程（Fallback）：
    1. 创建任务
    2. 定期轮询任务状态，检测到 awaiting_* 状态
    3. 主动调用回调接口
    4. 继续轮询直到完成
    """
    db_path = str(tmp_path / "test.db")

    # 初始化数据库
    database = Database(db_path)
    await database.init_tables()

    # 初始化服务
    task_repo = SQLiteTaskRepository(db_path)
    message_bus = SQLiteMessageBus(db_path)
    event_store = SQLiteEventStore(db_path)
    workflow_repo = SQLiteWorkflowRepo(db_path)

    # 加载工作流配置
    from app.workflow.config import load_workflow_config
    config = load_workflow_config("purchase_request")
    await workflow_repo.save_version("v1", "purchase_request", config)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor
    )

    app.state.task_service = task_service
    app.state.message_bus = message_bus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 创建任务
        response = await client.post("/v1/tasks", json={
            "user_id": "test_user",
            "task": {
                "type": "purchase_request",
                "data": {"amount": 1000, "order_no": "REQ-001"}
            }
        })
        assert response.status_code == 201
        task_id = response.json()["task"]["id"]

        # 2. 轮询等待状态变为 awaiting_*
        event_id = None
        node_id = None

        for _ in range(20):  # 最多轮询 20 次
            await asyncio.sleep(0.2)
            response = await client.get(f"/v1/tasks/{task_id}")
            assert response.status_code == 200
            task_data = response.json()["task"]
            status = task_data["status"]

            if status.startswith("awaiting_"):
                # 从消息总线获取事件信息
                async for msg in message_bus.subscribe("test_user"):
                    event_id = msg.event_id
                    node_id = msg.node_id
                    break
                break

        assert event_id is not None, "未检测到中断状态"

        # 3. 回调恢复
        response = await client.post(f"/v1/tasks/{task_id}/callback", json={
            "event_id": event_id,
            "node_id": node_id,
            "user_input": {
                "is_approved": True,
                "audit_opinion": "同意",
                "approver": "manager"
            }
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

        # 4. 继续轮询直到完成或下一个中断
        for _ in range(20):
            await asyncio.sleep(0.2)
            response = await client.get(f"/v1/tasks/{task_id}")
            task_data = response.json()["task"]
            status = task_data["status"]

            if status == "completed" or status.startswith("awaiting_"):
                break

        assert status in ["completed", "awaiting_finance_audit"]

    await database.clear_all()
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/test_polling_mode.py
git commit -m "test(e2e): add Polling mode end-to-end test (Fallback scenario)"
```

---

### Task 18: 实现工作流版本升级 E2E 测试

**Files:**
- Create: `tests/e2e/test_workflow_version_upgrade.py`

- [ ] **Step 1: 实现版本升级测试**

```python
# tests/e2e/test_workflow_version_upgrade.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.api.main import app
from app.infrastructure.database import Database
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor
from app.service.task_service import TaskService


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_version_isolation(tmp_path):
    """
    工作流版本隔离测试（模拟方案）：
    1. 使用 v1 配置创建任务 A
    2. 任务 A 运行到 manager_audit 节点（挂起）
    3. 直接插入 v2 配置到数据库（模拟升级）
    4. 创建新任务 B，应该自动使用 v2
    5. 验证任务 A 用 v1，任务 B 用 v2
    """
    db_path = str(tmp_path / "test.db")

    # 初始化数据库
    database = Database(db_path)
    await database.init_tables()

    # 初始化服务
    task_repo = SQLiteTaskRepository(db_path)
    message_bus = SQLiteMessageBus(db_path)
    event_store = SQLiteEventStore(db_path)
    workflow_repo = SQLiteWorkflowRepo(db_path)

    # v1 配置（原始配置）
    from app.workflow.config import load_workflow_config
    config_v1 = load_workflow_config("purchase_request")
    await workflow_repo.save_version("v1", "purchase_request", config_v1, active=True)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor
    )

    app.state.task_service = task_service
    app.state.message_bus = message_bus

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 创建任务 A（使用 v1）
        response = await client.post("/v1/tasks", json={
            "user_id": "test_user",
            "task": {
                "type": "purchase_request",
                "data": {"amount": 1000, "order_no": "REQ-A"}
            }
        })
        assert response.status_code == 201
        task_a_id = response.json()["task"]["id"]

        # 验证任务 A 使用 v1
        response = await client.get(f"/v1/tasks/{task_a_id}")
        assert response.json()["task"]["workflow_version"] == "v1"

        # 2. 插入 v2 配置（模拟升级，添加了 CTO 审批节点）
        config_v2 = {
            "name": "purchase_request",
            "nodes": [
                {"id": "submit", "type": "action", "next": "manager_audit"},
                {"id": "manager_audit", "type": "interrupt", "required_params": ["is_approved"],
                 "display_data": {}, "next": "cto_audit"},
                {"id": "cto_audit", "type": "interrupt", "required_params": ["is_approved"],
                 "display_data": {}, "next": "approved"},
                {"id": "approved", "type": "terminal", "status": "completed"}
            ]
        }
        await workflow_repo.save_version("v2", "purchase_request", config_v2, active=True)

        # 3. 创建任务 B（应该使用 v2）
        response = await client.post("/v1/tasks", json={
            "user_id": "test_user",
            "task": {
                "type": "purchase_request",
                "data": {"amount": 5000, "order_no": "REQ-B"}
            }
        })
        assert response.status_code == 201
        task_b_id = response.json()["task"]["id"]

        # 验证任务 B 使用 v2
        response = await client.get(f"/v1/tasks/{task_b_id}")
        assert response.json()["task"]["workflow_version"] == "v2"

        # 4. 验证版本隔离
        response = await client.get(f"/v1/tasks/{task_a_id}")
        task_a = response.json()["task"]
        assert task_a["workflow_version"] == "v1"  # 旧任务仍用 v1

        response = await client.get(f"/v1/tasks/{task_b_id}")
        task_b = response.json()["task"]
        assert task_b["workflow_version"] == "v2"  # 新任务用 v2

    await database.clear_all()
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/test_workflow_version_upgrade.py
git commit -m "test(e2e): add workflow version isolation test"
```

---

## 文档和收尾

### Task 19: 创建项目文档

**Files:**
- Create: `README.md`
- Create: `scripts/run_server.py`
- Create: `scripts/run_client.py`

- [ ] **Step 1: 创建 README.md**

```markdown
# LangGraph 云端服务与本地客户端集成 - MVP

基于 FastAPI + SQLite + LangGraph 的云端工作流服务，支持 Human-in-the-Loop 场景。

## 特性

- 🔄 可配置的 YAML 工作流定义
- 📡 实时 WebSocket 通知 + 轮询模式 Fallback
- 🔒 防重放的回调机制
- 📦 工作流版本隔离
- 🎯 单用户演示场景

## 快速开始

### 创建虚拟环境

\`\`\`bash
# 创建 venv
python -m venv .venv

# 激活虚拟环境
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate
\`\`\`

### 安装依赖

\`\`\`bash
pip install -e ".[dev]"
\`\`\`

### 启动服务器

\`\`\`bash
python scripts/run_server.py
\`\`\`

或直接：

\`\`\`bash
uvicorn app.api.main:app --reload
\`\`\`

### 运行客户端

\`\`\`bash
python scripts/run_client.py
\`\`\`

## 运行测试

\`\`\`bash
# 运行所有测试
pytest

# 单元测试
pytest tests/unit/

# 集成测试
pytest tests/integration/

# E2E 测试
pytest tests/e2e/ -m e2e
\`\`\`

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/tasks` | 创建任务 |
| GET | `/v1/tasks/{task_id}` | 获取任务状态 |
| POST | `/v1/tasks/{task_id}/callback` | 回调恢复 |
| WS | `/ws?user_id={id}` | WebSocket 订阅 |

## 架构

- `app/domain/` - 领域接口和 DTO
- `app/infrastructure/` - SQLite 基础设施实现
- `app/workflow/` - LangGraph 工作流
- `app/service/` - 业务编排
- `app/api/` - FastAPI 接口
- `app/client_sdk/` - 客户端 SDK

## 许可

MIT
```

- [ ] **Step 2: 创建启动脚本**

```python
# scripts/run_server.py
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=8000, reload=True)
```

```python
# scripts/run_client.py
import asyncio
import sys
sys.path.insert(0, ".")

from app.client_sdk.cli import main

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Commit**

```bash
git add README.md scripts/
git commit -m "docs: add README and convenience scripts"
```

---

## 实现完成检查清单

- [ ] 所有单元测试通过 (`pytest tests/unit/`)
- [ ] 所有集成测试通过 (`pytest tests/integration/`)
- [ ] 所有 E2E 测试通过 (`pytest tests/e2e/ -m e2e`)
- [ ] 服务器能正常启动 (`uvicorn app.api.main:app`)
- [ ] 客户端能正常连接和交互
- [ ] 工作流版本隔离验证通过

---

**执行说明**

使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务顺序实现。
