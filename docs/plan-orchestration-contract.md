# 实施计划：编排元数据接口 + 任务详情增强 + Callback 校验

> 目标：对齐 LangGraph 云端与客户端集成契约中的三块核心需求
> 全链路统一使用 `transitions` 命名（YAML → 代码 → API 响应 → 契约）

## 变更概览

```
YAML 扩展 → Builder 适配 → 新 Schemas → Repo 扩展
  → Task 存储 → Executor 改造 → Service 改造 → 路由层 → 测试
```

---

## Step 1：扩展 YAML Schema — transitions 加入 action、label、form_schema

**改什么：** `app/workflow/config/*.yml`

保留 `transitions` 名称不变，每个 transition 扩展字段：
- 新增 `action` — 分支标识（如 approve/reject）
- 新增 `label` — 显示名称
- `next` 改为 `target_node` — 与契约对齐
- 新增 `form_schema` — JSON Schema 定义
- 保留 `condition` — Builder 构建条件边用
- 删除节点级 `required_params` — 被 form_schema 替代

**示例（manager_audit 节点）：**
```yaml
  - id: manager_audit
    type: interrupt
    display_name: 经理审批
    description: 部门经理审批采购申请
    transitions:
      - action: approve
        label: 批准
        target_node: finance_audit
        condition: is_approved == true
        form_schema:
          type: object
          required: [is_approved, audit_opinion, approver]
          properties:
            is_approved: { type: boolean, const: true }
            audit_opinion: { type: string, minLength: 1 }
            approver: { type: string }
      - action: reject
        label: 驳回
        target_node: rejected
        condition: is_approved == false
        form_schema:
          type: object
          required: [is_approved, reject_reason, approver]
          properties:
            is_approved: { type: boolean, const: false }
            reject_reason: { type: string, minLength: 1 }
            approver: { type: string }
```

action 节点的 `next` 也改为 `target_node`。

**涉及文件：**
- `app/workflow/config/purchase_request.yml`
- `app/workflow/config/todo_workflow.yml`

---

## Step 2：适配 WorkflowBuilder

**改什么：** `app/workflow/builder.py`

`_add_edges` 中将 `transition["next"]` 改为 `transition["target_node"]`。
action 节点的 `node["next"]` 也改为 `node["target_node"]`。

其余逻辑（condition 读取、evaluate_condition）不变。

---

## Step 3：新增 Pydantic Schemas

**改什么：** `app/domain/schemas.py`

新增模型：

```python
class TransitionSchema(BaseModel):
    action: str
    label: str
    target_node: str
    form_schema: dict

class NodeSchema(BaseModel):
    id: str
    type: str
    description: str
    transitions: list[TransitionSchema] | None = None

class OrchestrationDetail(BaseModel):
    type: str
    version: str
    description: str
    nodes: list[NodeSchema]

class OrchestrationSummary(BaseModel):
    type: str
    latest_version: str
    description: str
    created_at: datetime
    updated_at: datetime

class OrchestrationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[OrchestrationSummary]

class PendingCallback(BaseModel):
    event_id: str
    node_id: str

class CurrentOwner(BaseModel):
    type: str
    id: str
    name: str
```

修改现有模型：
- `Task` → 新增 `pending_callback: PendingCallback | None`、`current_owner: CurrentOwner | None`
- `CallbackRequest` → 新增 `action: str` 字段

---

## Step 4：扩展 IWorkflowRepo + SQLiteWorkflowRepo

**改什么：** `app/domain/interfaces.py` + `app/infrastructure/workflow_repo.py`

新增方法：
- `list_orchestrations(page, page_size) -> dict` — 分页查询编排列表

---

## Step 5：扩展 Task 存储

**改什么：** `app/infrastructure/database.py` + `app/infrastructure/sqlite_repository.py`

tasks 表新增列：
- `pending_event_id TEXT`
- `pending_node_id TEXT`

Repository 新增方法：
- `update_pending_callback(task_id, event_id, node_id)`
- `clear_pending_callback(task_id)`
- `get()` 返回值包含 pending_callback

---

## Step 6：Executor 改造 — 返回结构化结果

**改什么：** `app/workflow/executor.py`

新增 `ExecutionResult` dataclass：
```python
@dataclass
class ExecutionResult:
    status: str
    node_id: str | None = None
    event_id: str | None = None
```

`execute()` 和 `resume()` 返回 `ExecutionResult` 替代 str。
interrupt 时 event_id 由 executor 生成并返回。

---

## Step 7：TaskService 改造

**改什么：** `app/service/task_service.py`

1. **Status 语义化：** interrupt 时状态为 `awaiting_{node_id}`
2. **pending_callback 管理：** interrupt 时写入，callback 时清除
3. **Callback 校验：**
   - 校验 action 在节点 transitions 中存在
   - 用匹配 transition 的 form_schema 校验 user_input（jsonschema）

**新增依赖：** `jsonschema>=4.20.0` 加入 pyproject.toml

---

## Step 8：新增编排路由 + 修改任务路由

**改什么：** `app/api/routes.py` + `app/api/deps.py`

新增路由：
- `GET /v1/orchestrations` — 编排列表
- `GET /v1/orchestrations/{type}/versions/{version}` — 全量定义
- `GET /v1/orchestrations/{type}/versions/{version}/nodes/{node_id}` — 单节点

修改路由：
- `GET /v1/tasks/{task_id}` — 返回增强的 Task（含 pending_callback）
- `POST /v1/tasks/{task_id}/callback` — 传递 action 参数

新增 dep：`WorkflowRepoDep`

---

## Step 9：更新测试

- 更新所有测试 fixture 中的 config dict（`next` → `target_node`，加 action/label/form_schema）
- 新增编排接口测试
- 新增 callback action 校验 + form_schema 校验测试
- 新增 pending_callback 测试

---

## 执行顺序

Step 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

每步完成后跑测试确保不破坏。
