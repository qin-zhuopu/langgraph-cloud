# LangGraph 云端服务与本地客户端集成 - MVP 设计文档

**日期**: 2026-04-15
**版本**: 1.0
**状态**: 待实现

---

## 1. 概述

本 MVP 旨在通过最轻量化的技术栈（Python + SQLite），实现 LangGraph 云端工作流与本地客户端之间的异步协作，重点支持"人工在环"（Human-in-the-Loop）场景。

### 1.1 设计目标

1. **概念验证 (PoC)** - 验证 LangGraph + 本地客户端架构的可行性
2. **参考实现** - 展示最佳实践，代码结构清晰，易于理解和扩展
3. **可演进原型** - 设计支持从 MVP 平滑迁移到生产环境

### 1.2 核心技术栈

| 组件 | MVP | Production (迁移路径) |
|------|-----|---------------------|
| API 框架 | FastAPI + Uvicorn | 保持 |
| 数据库 | SQLite (aiosqlite) | PostgreSQL |
| 工作流引擎 | LangGraph + MemorySaver | 保持 |
| 并发锁 | SQLite BEGIN IMMEDIATE 事务 | PostgreSQL advisory locks / Redis |
| 消息总线 | SQLite Message Table | Kafka / RabbitMQ |
| 实时通信 | WebSocket | 保持 |

---

## 2. 整体架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cloud Service                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    FastAPI + Uvicorn                      │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │  │
│  │  │   REST      │  │  WebSocket   │  │    LangGraph   │  │  │
│  │  │   Routes    │  │   Manager    │  │    Engine      │  │  │
│  │  └──────┬──────┘  └──────┬───────┘  └────────┬───────┘  │  │
│  │         │                │                    │          │  │
│  │  ┌──────▼────────────────▼────────────────────▼──────┐  │  │
│  │  │              TaskService (Orchestration)          │  │  │
│  │  └──────┬────────────────────────────────────────────┘  │  │
│  └─────────┼────────────────────────────────────────────────┘  │
│            │                                                   │
│  ┌─────────▼─────────────────────────────────────────────┐    │
│  │              Domain Interfaces (Contracts)             │    │
│  │  ITaskRepository │ IMessageBus                         │    │
│  └────────────────────────────────────────────────────────┘    │
│            │                                                   │
│  ┌─────────▼─────────────────────────────────────────────┐    │
│  │           Infrastructure (SQLite-based)                 │    │
│  │  • TaskRepository       • SQLiteMessageBus             │    │
│  │  • TransactionLock      • WebSocketNotifier            │    │
│  │  • WorkflowRepo         • EventStore                   │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   SQLite DB     │
                    │ • tasks         │
                    │ • events        │
                    │ • checkpoints   │
                    │ • workflow_versions │
                    └─────────────────┘

                              │
                    WebSocket (ws://localhost:8000/ws)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Local Client (CLI)                            │
│  ┌───────────────┐  ┌────────────────┐  ┌─────────────────────┐  │
│  │ WebSocketClient│ → │ MessageHandler│ → │ UserInteraction     │  │
│  │ (SDK Core)     │  │ (Callbacks)   │  │ (Console Input)     │  │
│  └───────────────┘  └────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
app/
├── domain/                    # 领域契约 (Server & Client 共享)
│   ├── interfaces.py          # ITaskRepository, IMessageBus
│   └── schemas.py             # 统一的消息格式 DTO
│
├── infrastructure/            # 基础设施层
│   ├── sqlite_repository.py   # TaskRepository 实现
│   ├── sqlite_bus.py          # SQLiteMessageBus (发布/订阅)
│   ├── event_store.py         # 事件防重放
│   └── workflow_repo.py       # 工作流配置管理
│
├── workflow/                  # LangGraph 工作流
│   ├── builder.py             # 动态图构建器
│   ├── checkpointer.py        # MemorySaver 实现
│   └── config/                # 工作流配置文件 (YAML)
│       └── purchase_request.yml
│
├── api/                       # FastAPI 应用
│   ├── main.py                # 应用入口
│   ├── routes.py              # REST + WebSocket 路由
│   └── deps.py                # 依赖注入
│
├── service/                   # 业务编排层
│   └── task_service.py        # 任务服务
│
└── client_sdk/                # 客户端 SDK
    ├── cli.py                 # 控制台演示客户端
    └── websocket_client.py    # WebSocket 消费者
```

---

## 3. API 设计

### 3.1 端点列表

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/v1/tasks` | 创建任务 |
| GET | `/v1/tasks/{task_id}` | 获取任务状态 (Fallback 轮询) |
| POST | `/v1/tasks/{task_id}/callback` | 回调恢复工作流 |
| WS | `/ws?user_id={user_id}` | WebSocket 订阅通知 |

### 3.2 创建任务

**Request:**
```json
POST /v1/tasks
{
  "user_id": "12345",
  "task": {
    "type": "purchase_request",
    "data": {
      "order_no": "REQ-2026-001",
      "amount": 8000,
      "apply_reason": "采购高性能工作站"
    }
  }
}
```

**Response (201 Created):**
```json
{
  "task": {
    "id": "task_uuid_987654321",
    "status": "initiated",
    "data": {
      "message": "工作流已启动"
    }
  }
}
```

### 3.3 获取任务状态 (Fallback 轮询)

**Response (200 OK):**
```json
{
  "task": {
    "id": "task_uuid_987654321",
    "type": "purchase_request",
    "status": "awaiting_manager_audit",
    "data": {
      "order_no": "REQ-2026-001",
      "amount": 8000,
      "updated_at": "2026-04-15T04:12:00Z"
    }
  }
}
```

### 3.4 回调恢复

**Request:**
```json
POST /v1/tasks/{task_id}/callback
{
  "event_id": "evt_abc123456789",
  "node_id": "manager_audit",
  "user_input": {
    "is_approved": true,
    "audit_opinion": "符合预算，准予采购",
    "approver": "Zhang San"
  }
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "next_status": "running"
}
```

---

## 4. 数据模型

### 4.1 Domain Schemas

```python
from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime

class TaskCreate(BaseModel):
    user_id: str
    task: TaskData

class TaskData(BaseModel):
    type: str
    data: dict

class Task(BaseModel):
    id: str
    user_id: str
    type: str
    status: str
    data: dict
    created_at: datetime
    updated_at: datetime

class EventMessage(BaseModel):
    event_id: str
    task_id: str
    task_type: str
    status: str
    node_id: str
    required_params: list[str]
    display_data: dict
```

### 4.2 Database Schema

```sql
-- 任务表
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    workflow_version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'initiated',
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 事件表（消息队列）
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    consumed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- LangGraph 状态持久化
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id)
);

-- 工作流配置版本
CREATE TABLE workflow_versions (
    version TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    config TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- 索引
CREATE INDEX idx_tasks_user ON tasks(user_id);
CREATE INDEX idx_events_user_consumed ON events(user_id, consumed);
CREATE INDEX idx_checkpoints_thread ON checkpoints(thread_id);
```

---

## 5. 核心流程

### 5.1 闭环模式对比

**模式 A: WebSocket 实时模式 (推荐)**
- 服务端通过 WebSocket 实时推送中断事件
- 客户端无需轮询，立即收到通知

**模式 B: Polling 轮询模式 (Fallback)**
- WebSocket 不可用时启用
- 客户端定期调用 `GET /v1/tasks/{id}` 检查状态
- 检测到 `awaiting_*` 状态时主动回调

### 5.2 防重放机制

每个 `event_id` 只能被消费一次，通过 `events.consumed` 字段实现。

```python
async def mark_consumed(self, event_id: str) -> bool:
    async with aiosqlite.connect(self.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT consumed FROM events WHERE event_id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:  # 已消费
            return False
        await db.execute(
            "UPDATE events SET consumed = 1 WHERE event_id = ?",
            (event_id,)
        )
        await db.commit()
        return True
```

---

## 6. 可配置工作流

### 6.1 配置示例

```yaml
# workflow/config/purchase_request.yml
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
      title: 待审批
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

### 6.2 工作流版本控制

- 任务创建时快照当前工作流配置版本
- 配置更新不影响已运行的任务
- 新任务使用最新版本

**MVP 版本升级流程：**

1. 停止服务器
2. 修改 YAML 配置文件
3. 重启服务器（加载新配置）
4. 新任务自动使用最新版本

> **注意**：MVP 期间不支持热重载，配置变更需要重启服务。

---

## 7. 错误处理

| 错误类型 | HTTP 状态 | 是否重试 |
|---------|-----------|---------|
| 任务不存在 | 404 | 否 |
| 数据校验失败 | 400 | 否 |
| event_id 已消费 | 409 | 否 |
| 并发冲突 | 409 | 是 (客户端重试) |
| WebSocket 断线 | - | 是 (自动重连) |

---

## 8. 测试策略

### 8.1 E2E 测试要求

**必须实现的端到端测试：**

1. **test_websocket_mode.py** - WebSocket 实时模式完整流程
2. **test_polling_mode.py** - 轮询模式完整流程（Fallback）
3. **test_workflow_version_upgrade.py** - 工作流版本升级场景

**工作流版本升级测试场景（MVP 模拟方案）：**

```python
# tests/e2e/test_workflow_version_upgrade.py
@pytest.mark.e2e
async def test_workflow_version_isolation():
    """验证：不同版本的任务互不影响（无需重启服务器）"""
    # 1. 使用 v1 配置创建任务 A
    task_a = await create_task_with_version("v1")

    # 2. 任务 A 运行到 manager_audit 节点（挂起）

    # 3. 直接插入 v2 配置到数据库（模拟升级）
    await insert_workflow_version("v2", v2_config, active=True)

    # 4. 创建新任务 B，应该自动使用 v2
    task_b = await create_task()  # workflow_version = "v2"

    # 5. 验证版本隔离
    assert task_a.workflow_version == "v1"
    assert task_b.workflow_version == "v2"

    # 6. 回调任务 A，应继续用 v1 流程（无 CTO 审批）
    await callback_task(task_a, manager_approval)
    assert task_a.status == "completed"  # v1 流程直接完成

    # 7. 验证任务 B 使用 v2 流程（需要 CTO 审批）
    await callback_task(task_b, manager_approval)
    assert task_b.status == "awaiting_cto_audit"  # v2 特有节点
```

**测试验证点：**
- 旧任务 `workflow_version` 字段保持不变
- 新任务自动获取最新版本
- 不同版本的任务按各自配置路径执行
- 版本间互不干扰

**注**：MVP 期间使用模拟方案（直接插入数据库），避免真实服务器重启的复杂性。

### 8.2 测试目录结构

```
tests/
├── unit/                      # 单元测试
│   ├── test_repository.py
│   ├── test_message_bus.py
│   ├── test_workflow_builder.py
│   └── test_event_store.py
├── integration/               # 集成测试
│   ├── test_api_endpoints.py
│   ├── test_websocket.py
│   └── test_task_service.py
└── e2e/                       # 端到端测试
    ├── test_websocket_mode.py
    └── test_polling_mode.py
```

---

## 9. MVP 范围

### 9.1 包含

- 单用户演示场景
- 可配置工作流（YAML）
- WebSocket 实时通知
- 轮询模式 Fallback
- 防重放机制
- 工作流版本控制
- E2E 测试（双模式）

### 9.2 不包含

- 多用户隔离
- 身份认证/授权
- 复杂的角色权限
- 分布式部署
- Kafka 消息队列（生产环境迁移目标）

---

## 10. 迁移到生产环境

| 组件 | MVP → Production 迁移路径 |
|------|-------------------------|
| 消息总线 | SQLite Table → Kafka |
| 数据库 | SQLite → PostgreSQL |
| 并发锁 | 事务锁 → Redis Lock |
| 配置加载 | 启动加载 → 热重载 |
| 多租户 | 单用户 → 多用户隔离 |
