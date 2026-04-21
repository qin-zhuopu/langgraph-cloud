# LangGraph 云端服务与本地客户端集成设计方案

> Source: 内部设计文档 (Qin Shuguo)
> Collected: 2026-04-20
> Published: 2026-04-20

本方案旨在解决云端运行的 LangGraph 工作流与本地客户端之间的异步协作问题，特别是针对"人工在环"（Human-in-the-Loop）场景下的任务创建、状态追踪与通知机制。

## 1. 整体架构

- **云端服务 (Cloud Service)**: 托管 LangGraph 引擎，负责流程编排、状态持久化 (Checkpointer) 及消息下发。内置校验引擎，根据不同的 task.type 调用不同的校验器。
- **消息队列 (Kafka)**: 作为异步通知通道，服务端向 `langgraph_message_user_{user_id}` 发送干预请求。
- **本地客户端 (Local Client)**: 负责发起任务、监听 Kafka 消息、展示用户 UI 并通过回调接口回传结果。

## 2. 认证机制

所有 REST API 接口统一采用 **IAM OIDC** 颁发的 JWT 进行认证。

- **认证方式**: `Authorization: Bearer <JWT>`
- **IdP 发现端点**: `https://iam.jereh.cn/idp/.well-known/openid-configuration`
- **验签流程**: 服务端从 OIDC Discovery 文档中的 `jwks_uri` 获取公钥（JWKS），对 JWT 签名进行本地验证，不依赖网络调用 IdP。
- **身份提取**: 从 JWT 的 `sub` 或 `preferred_username` claim 中提取 `user_id`，作为任务归属和 Kafka 消息路由的唯一标识。
- **移除请求体中的 user_id**: `user_id` 不再出现在请求 body 中，统一由 JWT 认证层注入，避免身份伪造。

## 3. 接口设计 (REST API)

### 3.1 创建任务 (Create Task)

客户端提交业务数据及任务类型。`type` 即编排标识，服务端根据 `type` 对 `task.data` 字段进行强校验。校验通过后生成 `task_id`（即 LangGraph `thread_id`），快照当前编排版本，启动工作流。

**Endpoint:** `POST /v1/tasks`

**Headers:**
```
Authorization: Bearer <JWT>
```

**Request Body:**
```json
{
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
      "message": "工作流已启动",
      "estimated_completion": "2026-04-14T12:00:00Z"
    }
  }
}
```

### 3.2 搜索任务 (Search Tasks)

分页查询当前用户的任务列表，支持按状态和类型过滤。

**Endpoint:** `GET /v1/tasks?type=purchase_request&status=awaiting_manager_audit&page=1&page_size=20`

**Query Parameters:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 否 | 按编排类型过滤 |
| `status` | string | 否 | 按任务状态过滤 |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |

**Response (200 OK):**
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": "task_uuid_987654321",
      "type": "purchase_request",
      "status": "awaiting_manager_audit",
      "orchestration_version": 3,
      "current_owner": {
        "type": "human",
        "id": "EMP_00123",
        "name": "张三",
        "description": "财务部经理"
      },
      "created_at": "2026-04-14T04:10:00Z",
      "updated_at": "2026-04-14T04:12:00Z"
    }
  ]
}
```

- 仅返回当前 JWT 用户关联的任务
- 列表项为轻量摘要，不含 `data` 和 `pending_callback`

### 3.3 获取任务详情 (Get Task Detail)

用于客户端主动查询任务进度，**也是 Kafka 消息丢失时的兜底闭环方案**。当任务处于 interrupt 状态时，响应中包含 `pending_callback` 字段（`event_id` + `node_id`），以及编排定位信息（`type` + `orchestration_version`）。客户端凭这三项去编排元数据接口查询完整的 branches 和 form_schema。非 interrupt 状态时 `pending_callback` 为 `null`。

**Endpoint:** `GET /v1/tasks/{task_id}`

**Response:**
```json
{
  "task": {
    "id": "task_uuid_987654321",
    "type": "purchase_request",
    "orchestration_version": 3,
    "status": "awaiting_manager_audit",
    "current_owner": {
      "type": "human",
      "id": "EMP_00123",
      "name": "张三",
      "description": "财务部经理"
    },
    "pending_callback": {
      "event_id": "evt_abc123456789",
      "node_id": "manager_audit"
    },
    "data": {
      "order_no": "REQ-2026-001",
      "amount": 8000,
      "updated_at": "2026-04-14T04:12:00Z",
      "result": null
    }
  }
}
```

- `type` 即编排标识，`orchestration_version` 为任务创建时快照的版本号
- `pending_callback` 仅在 interrupt 状态时出现，非 interrupt 时为 `null`

### 3.4 人工回调接口 (Callback/Resume)

当用户处理完 Kafka 消息后，通过此接口回传结果。`event_id` 和 `node_id` 可来源于 Kafka 推送或 GET 详情中的 `pending_callback`。`action` 标识用户选择的分支走向，`user_input` 必须符合编排定义中对应 branch 的 `form_schema`。

**Endpoint:** `POST /v1/tasks/{task_id}/callback`

**Request Body:**
```json
{
  "event_id": "evt_abc123456789",
  "node_id": "manager_audit",
  "action": "approve",
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

### 3.5 搜索编排 (Search Orchestrations)

分页查询可用的编排定义列表。

**Endpoint:** `GET /v1/orchestrations?page=1&page_size=20`

**Response (200 OK):**
```json
{
  "total": 5,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "type": "purchase_request",
      "latest_version": 3,
      "description": "采购申请审批流程",
      "created_at": "2026-03-01T00:00:00Z",
      "updated_at": "2026-04-10T00:00:00Z"
    }
  ]
}
```

- `type` 为编排标识，即创建任务时使用的 `task.type`
- `latest_version` 为当前最新版本号

### 3.6 获取编排全量定义 (Get Orchestration)

返回指定版本编排的完整节点、分支及 form_schema 定义。客户端可缓存此响应，按 `node_id` 本地查找。

**Endpoint:** `GET /v1/orchestrations/{type}/versions/{version}`

**示例:** `GET /v1/orchestrations/purchase_request/versions/3`

**Response (200 OK):**
```json
{
  "type": "purchase_request",
  "version": 3,
  "description": "采购申请审批流程",
  "nodes": [
    {
      "id": "submit",
      "type": "action",
      "description": "提交申请"
    },
    {
      "id": "manager_audit",
      "type": "interrupt",
      "description": "部门经理审批",
      "branches": [
        {
          "action": "approve",
          "label": "批准",
          "target_node": "finance_review",
          "form_schema": {
            "type": "object",
            "required": ["is_approved", "audit_opinion", "approver"],
            "properties": {
              "is_approved": { "type": "boolean", "const": true },
              "audit_opinion": { "type": "string", "minLength": 1, "description": "审批意见" },
              "approver": { "type": "string", "description": "审批人姓名" }
            }
          }
        },
        {
          "action": "reject",
          "label": "驳回",
          "target_node": "rejected",
          "form_schema": {
            "type": "object",
            "required": ["is_approved", "reject_reason", "approver"],
            "properties": {
              "is_approved": { "type": "boolean", "const": false },
              "reject_reason": { "type": "string", "minLength": 1, "description": "驳回原因" },
              "approver": { "type": "string", "description": "审批人姓名" }
            }
          }
        }
      ]
    },
    { "id": "finance_review", "type": "action", "description": "财务复核" },
    { "id": "approved", "type": "terminal", "description": "审批通过" },
    { "id": "rejected", "type": "terminal", "description": "审批驳回" }
  ]
}
```

### 3.7 获取单节点定义 (Get Node)

返回指定节点的 branches 和 form_schema，适合按需精确查询。客户端优先尝试本地缓存（全量接口响应），miss 时按节点精确拉取。

**Endpoint:** `GET /v1/orchestrations/{type}/versions/{version}/nodes/{node_id}`

**示例:** `GET /v1/orchestrations/purchase_request/versions/3/nodes/manager_audit`

**Response (200 OK):**
```json
{
  "node_id": "manager_audit",
  "type": "interrupt",
  "description": "部门经理审批",
  "branches": [
    {
      "action": "approve",
      "label": "批准",
      "target_node": "finance_review",
      "form_schema": { "..." }
    },
    {
      "action": "reject",
      "label": "驳回",
      "target_node": "rejected",
      "form_schema": { "..." }
    }
  ]
}
```

- `form_schema` 遵循 JSON Schema Draft 2020-12 规范
- `target_node` 标识该分支导向的下一节点，供客户端做流程预览

## 4. Kafka 消息设计 (通知下行)

当 LangGraph 运行到 interrupt 节点时，服务端发送消息。

**Topic 命名规则:** `langgraph_message_user_{user_id}`

**消息 Key 设计:** `{user_id}:{device_id}` — Kafka 消费者可通过消息 Key 实现按用户+设备的分区隔离，确保每个订阅者只收到属于自己的消息。

**消息 Payload:**
```json
{
  "header": {
    "event_id": "evt_abc123456789",
    "task_id": "task_uuid_987654321",
    "task_type": "purchase_request",
    "status": "awaiting_manager_audit",
    "timestamp": 1713067800
  },
  "callback_context": {
    "node_id": "manager_audit"
  },
  "display_data": {
    "title": "待办审批通知",
    "content": "您有一个新的采购申请需要审批，金额：8000元。"
  }
}
```

**说明：** Kafka 消息仅传递通知和节点定位信息（`node_id`）。完整的 branches 和 form_schema 由客户端通过编排元数据接口按需获取。

## 5. 核心业务流程

1. **发起与校验**: 客户端发起任务，服务端生成 `task_id`。服务端校验 `task.data` 合法性。
2. **执行与挂起**: LangGraph 运行至审批节点，触发 interrupt。服务端生成唯一的 `event_id`，并记录该事件与 `task_id`、`node_id` 的关联。
3. **通知**: 服务端向 Kafka 发送消息（Key = `{user_id}:{device_id}`）。同时查询接口中的 `status` 同步更新，`pending_callback` 填充节点定位信息。
4. **本地响应（推送路径）**: 客户端消费 Kafka 消息，从 `callback_context.node_id` 查询编排节点接口获取 branches 和 form_schema，渲染表单，提交回调。
5. **本地响应（兜底路径）**: 若 Kafka 消息丢失，客户端主动轮询 `GET /v1/tasks/{id}`，从 `pending_callback` 获取 `event_id` 和 `node_id`，再查询编排节点接口获取 schema，完成回调。
6. **安全校验与恢复**: 服务端检查 `event_id` 有效性，验证 `action` 合法性及 `user_input` 通过对应 `form_schema` 校验。通过后标记事件已完成，并根据 `node_id` 恢复工作流。

## 6. 负责人 (Owner) 透明化

在任务详情中引入 `current_owner` 多态对象，明确当前任务的处理负责人。

### 多态负责人类型定义

| type | 标识字段 (id) | 描述字段 (description/name) | 附加元数据 (metadata) |
|------|---------------|---------------------------|----------------------|
| `human` (人) | 工号 (e.g., EMP_102) | 姓名 (e.g., 李四) | 部门、联系方式 |
| `agent` (智能体) | Agent ID / Name | 角色描述 (e.g., 风控分析助手) | 模型版本、Prompt 版本 |
| `program` (程序) | 方法指纹/签名 | 函数名或类名 | 部署环境、执行实例 ID |

## 7. 设计要点说明

- **编排与实例分离**: 任务详情只返回 `type` + `orchestration_version` + `node_id`，编排定义通过独立接口查询，职责清晰。
- **状态与节点解耦**: 详情 DTO 暴露业务化的 `status`，`node_id` 封装在 `pending_callback` 中，仅在 interrupt 状态时出现。
- **Pull 兜底闭环**: `pending_callback` 提供编排定位信息，配合编排元数据接口可完整闭环，即使消息丢失也可通过轮询完成回调。
- **参数契约一致性**: 编排定义中的 `form_schema` 是回调 `user_input` 校验的唯一标准。
- **防重放与幂等性**: 通过唯一 `event_id` 确保人工干预事件不会被重复处理。
- **ID 统一性**: `task.id` == LangGraph `thread_id`；`task.type` == 编排标识。
- **结果封装**: 所有的执行结果（`result`）和过程元数据统一放在 `task.data` 内部。
- **设备级消息隔离**: Kafka 消息 Key 采用 `{user_id}:{device_id}` 格式，支持消费者按用户+设备维度过滤消息。
- **统一认证**: 所有 API 使用 IAM OIDC JWT 认证，`user_id` 由认证层注入而非请求体传入，杜绝身份伪造。
