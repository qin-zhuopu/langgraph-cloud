# 实施计划：客户端适配层 + Kafka 集成 + E2E 测试

> 目标：让现有 JerehPilot 客户端无需改动即可对接我们的工作流引擎

## 背景

JerehPilot 客户端期望的接口：
- `POST /financial/audit` — 创建任务（multipart 文件上传），返回 `{thread_id}`
- `POST /financial/audit/decide` — 提交决策 `{event_id, thread_id, decision: "add in"|"reject"}`，返回 `{success, next_status}`
- Kafka 消息格式：`{header: {event_id, thread_id, status, timestamp}, result: {...}, callback_context: {...}}`
- Status 枚举：`awaiting_human_review` | `completed` | `error`

我们的核心引擎接口：
- `POST /v1/tasks` — 创建任务
- `POST /v1/tasks/{task_id}/callback` — 回调 `{event_id, node_id, action, user_input}`
- SQLite MessageBus 推送

适配层负责两端的协议转换，不改动核心引擎代码。

---

## Step 1：新增 Kafka Producer

**新建：** `app/infrastructure/kafka_producer.py`

基于 `aiokafka` 实现异步 Kafka 生产者，替代 SQLite MessageBus 用于生产环境消息推送。

```python
class KafkaProducer:
    async def start(brokers: list[str])
    async def send(topic: str, key: str, value: dict)
    async def stop()
```

消息格式适配：将 `EventMessage` 转换为客户端期望的 Kafka payload：

```python
def event_to_kafka_payload(event: EventMessage, workflow_config: dict) -> dict:
    """将内部 EventMessage 转换为客户端期望的 Kafka 消息格式"""
    return {
        "header": {
            "event_id": event.event_id,
            "thread_id": event.task_id,  # task_id == thread_id
            "status": map_status(event.status),  # awaiting_xxx → awaiting_human_review
            "timestamp": int(time.time()),
        },
        "result": event.display_data,
        "callback_context": {
            "required_action": "human_decision",
            "node_id": event.node_id,
            "required_params": event.required_params,
        } if event.status == "interrupted" else None,
    }
```

Status 映射：`awaiting_*` → `awaiting_human_review`，`completed` → `completed`，`error` → `error`

**新增依赖：** `aiokafka>=0.10.0` 加入 pyproject.toml

---

## Step 2：适配层路由

**新建：** `app/api/adapter.py`

独立的 FastAPI router，挂载在 `/financial/audit` 路径下。

### POST /financial/audit — 创建任务

接收 multipart/form-data（files 字段），内部调用 `TaskService.create_task`：
- 从配置中确定 workflow type（如 `inquiry`）
- 构建 task.data（文件信息等）
- 返回 `{thread_id: task_id}`

### POST /financial/audit/decide — 提交决策

接收 `{event_id, thread_id, decision}`，映射到 `TaskService.callback`：
- `thread_id` → `task_id`
- `decision: "add in"` → `action: "approve"` 或根据 workflow 配置映射
- `decision: "reject"` → `action: "reject"`
- 返回 `{success: true, next_status: "xxx"}`

### GET /financial/audit/status — 查询状态

接收 `?thread_id=xxx`，调用 `TaskService.get_task`，返回客户端期望的格式。

---

## Step 3：Kafka 集成到 Executor

**修改：** `app/workflow/executor.py` 的 `_handle_interrupt` 方法

在发布到 SQLite MessageBus 的同时，如果配置了 Kafka，也发送到 Kafka topic。

```python
# 现有：发到 SQLite MessageBus
await self._message_bus.publish(user_id, event)

# 新增：发到 Kafka（如果配置了）
if self._kafka_producer:
    payload = event_to_kafka_payload(event, workflow_config)
    await self._kafka_producer.send(
        topic=self._kafka_topic,
        key=event.task_id,
        value=payload,
    )
```

同样，workflow 完成时也需要发一条 `completed` 消息到 Kafka。

---

## Step 4：配置管理

**新建：** `app/config.py`

从环境变量或配置文件加载 Kafka 配置：

```python
@dataclass
class AppConfig:
    kafka_brokers: list[str] = field(default_factory=list)  # 空则不启用 Kafka
    kafka_topic: str = "financial_audit_notify"
    db_path: str = "langgraph_cloud.db"
```

**修改：** `app/api/main.py` 的 `lifespan`

启动时如果配置了 Kafka brokers，初始化 KafkaProducer 并注入到 Executor。

---

## Step 5：注册适配层路由

**修改：** `app/api/main.py`

```python
from app.api.adapter import adapter_router
app.include_router(adapter_router)
```

---

## Step 6：E2E 测试 — Happy Path

**新建：** `tests/e2e/test_client_adapter_e2e.py`

**前提：** 真实 Kafka broker 可达（`kafka01.ndev.jereh.cn:9092`）

### 测试流程

```
1. 启动 FastAPI 服务（ASGI transport，带 Kafka producer）
2. POST /financial/audit 创建任务
   → 验证返回 {thread_id}
3. 消费 Kafka topic，等待收到 awaiting_human_review 消息
   → 验证消息格式：header.thread_id, header.status, header.event_id, callback_context
4. POST /financial/audit/decide 提交 "add in" 决策
   → 验证返回 {success: true, next_status}
5. 消费 Kafka topic，等待收到 completed 消息
   → 验证消息格式
6. GET /financial/audit/status?thread_id=xxx
   → 验证任务状态为 completed
```

### Kafka 消费辅助

测试中用 `aiokafka.AIOKafkaConsumer` 消费消息，设置唯一 group_id 避免和其他消费者冲突。

### 标记

```python
@pytest.mark.e2e
@pytest.mark.kafka  # 需要真实 Kafka，CI 中可跳过
```

---

## Step 7：E2E 测试 — 多轮询价 Happy Path（inquiry workflow）

**新建：** `tests/e2e/test_inquiry_e2e.py`

使用 inquiry workflow 的完整流程：

```
1. POST /v1/tasks 创建询价任务（5 家供应商、3 个物料）
2. 消费 Kafka → awaiting_human_review（check_quotes 节点）
3. POST /v1/tasks/{id}/callback action=new_round（淘汰万山，4 家继续）
4. 消费 Kafka → awaiting_human_review（再次 check_quotes）
5. POST /v1/tasks/{id}/callback action=award（3 个物料定标）
6. 消费 Kafka → completed
7. GET /v1/tasks/{id} → 验证 completed + pending_callback=null
```

---

## Step 8：更新现有测试

确保新增的 Kafka 集成不破坏现有测试：
- 现有测试不配置 Kafka brokers → KafkaProducer 不初始化 → 行为不变
- 新增 `conftest.py` fixture 提供 Kafka 配置（仅 e2e kafka 测试使用）

---

## 文件清单

```
新建：
  app/infrastructure/kafka_producer.py   — Kafka 异步生产者
  app/api/adapter.py                     — 客户端适配层路由
  app/config.py                          — 配置管理
  tests/e2e/test_client_adapter_e2e.py   — 适配层 E2E 测试
  tests/e2e/test_inquiry_e2e.py          — 询价工作流 E2E 测试

修改：
  app/api/main.py                        — 注册适配层路由 + Kafka 初始化
  app/workflow/executor.py               — Kafka 发送集成
  pyproject.toml                         — 新增 aiokafka 依赖

不改：
  app/service/task_service.py            — 核心逻辑不变
  app/api/routes.py                      — 核心路由不变
  tests/unit/*                           — 单元测试不变
  tests/integration/*                    — 集成测试不变
```

## 执行顺序

Step 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

每步完成后跑现有 150 个测试确保不回归。
