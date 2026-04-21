# LangGraph 云端与客户端集成契约

> Sources: Qin Shuguo, 2026-04-20
> Raw: [langgraph-cloud-client-contract](../../raw/langgraph-integration/2026-04-20-langgraph-cloud-client-contract.md)

## Overview

本契约定义了 LangGraph 云端工作流引擎与本地客户端之间的异步协作规范，覆盖 Human-in-the-Loop 场景下的任务创建、状态追踪、消息通知与人工回调。核心设计原则：**编排与实例分离**（任务只存定位信息，编排定义独立查询）、**参数契约一致**（Kafka 与 REST 共享 schema）、**防重放**（event_id 幂等）。

## Kafka 消息契约

**Topic:** `langgraph_message_user_{user_id}`

**消息 Key:** `{user_id}:{device_id}` — 支持消费者按用户+设备分区隔离。

**Payload 结构：**

| 字段                         | 说明                                       |
| -------------------------- | ---------------------------------------- |
| `header.event_id`          | 全局唯一事件 ID，用于防重放                          |
| `header.task_id`           | 关联的任务 ID                                 |
| `header.task_type`         | 编排类型（即 `task.type`，如 `purchase_request`） |
| `header.status`            | 当前业务状态                                   |
| `header.timestamp`         | 事件时间戳                                    |
| `callback_context.node_id` | 需要恢复的工作流节点 ID                            |
| `display_data.title`       | 通知标题（供 UI 展示）                            |
| `display_data.content`     | 通知正文（供 UI 展示）                            |

**参数契约规则：** 回调时 `action` 必须匹配编排定义中该节点的合法分支，`user_input` 必须通过对应 `form_schema` 的 JSON Schema 校验。


## REST API 契约

### POST /v1/tasks — 创建任务

客户端提交 `{task: {type, data}}`，`type` 即编排标识（如 `purchase_request`）。服务端根据 `type` 对 `task.data` 执行强校验。校验通过后生成 `task_id`（即 LangGraph `thread_id`），快照当前编排版本，启动工作流。

```json
{
  "task": {
    "type": "purchase_request",
    "data": { "order_no": "REQ-2026-001", "amount": 8000, "apply_reason": "采购高性能工作站" }
  }
}
```

返回 201，包含 `task.id`、`status: "initiated"` 及初始 `data`。


### GET /v1/tasks/{task_id} — 任务详情

返回业务状态、负责人及**编排定位信息**。当任务处于 interrupt 状态时，`pending_callback` 提供回调所需的最小上下文（`event_id`、`node_id`），客户端凭 `type` + `orchestration_version` + `node_id` 查询编排元数据获取完整的 transitions 和 form_schema。

```json
{
  "task": {
    "id": "task_uuid_987654321",
    "type": "purchase_request",
    "orchestration_version": 3,
    "status": "awaiting_manager_audit",
    "current_owner": { "type": "human", "id": "00123", "name": "张三"},
    "pending_callback": {
      "event_id": "evt_abc123456789",
      "node_id": "manager_audit"
    },
    "data": { "order_no": "REQ-2026-001", "amount": 8000, "updated_at": "2026-04-14T04:12:00Z", "result": null }
  }
}
```

- `type` 即编排标识，`orchestration_version` 为任务创建时快照的版本号
- `pending_callback` 仅在 interrupt 状态时出现，非 interrupt 时为 `null`
- 客户端拿 `type` + `orchestration_version` + `node_id` 去编排元数据接口查询完整 schema

### POST /v1/tasks/{task_id}/callback — 人工回调

工作流恢复入口。`event_id` 和 `node_id` 可来源于 Kafka 推送或 GET 详情中的 `pending_callback`。`action` 标识用户选择的分支走向，`user_input` 必须符合编排定义中对应 transition 的 `form_schema`：

```json
{
  "event_id": "evt_abc123456789",
  "node_id": "manager_audit",
  "action": "approve",
  "user_input": { "is_approved": true, "audit_opinion": "符合预算，准予采购", "approver": "Zhang San" }
}
```

服务端校验：① `event_id` 未被消费；② `action` 为当前节点合法分支；③ `user_input` 通过对应 transition 的 `form_schema` JSON Schema 校验。通过后标记事件已消费、恢复工作流。


### GET /v1/tasks — 搜索任务

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
      "current_owner": { "type": "human", "id": "00123", "name": "张三"},
      "created_at": "2026-04-14T04:10:00Z",
      "updated_at": "2026-04-14T04:12:00Z"
    }
  ]
}
```

- 仅返回当前 JWT 用户关联的任务
- 列表项为轻量摘要，不含 `data` 和 `pending_callback`
### GET /v1/orchestrations — 搜索编排

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

### GET /v1/orchestrations/{type}/versions/{version}/nodes/{node_id} — 获取单节点定义

返回指定节点的 transitions 和 form_schema，适合按需精确查询。

**Endpoint:** `GET /v1/orchestrations/purchase_request/versions/3/nodes/manager_audit`

**Response (200 OK):**
```json
{
  "node_id": "manager_audit",
  "type": "interrupt",
  "description": "部门经理审批",
  "transitions": [
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
}
```

- 客户端优先尝试本地缓存（全量接口响应），miss 时按节点精确拉取
- `form_schema` 遵循 [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation.html)
- `target_node` 标识该分支导向的下一节点，供客户端做流程预览

### GET /v1/orchestrations/{type}/versions/{version} — 获取编排全量定义

返回指定版本编排的完整节点、分支及 form_schema 定义。客户端可缓存此响应，按 `node_id` 本地查找。

**Endpoint:** `GET /v1/orchestrations/purchase_request/versions/3`

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
      "transitions": [
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

- 客户端按 `node_id` 查找对应节点，获取 `transitions` 和 `form_schema`
- 适用于流程图渲染、流程预览等需要全量编排信息的场景
- 可按 `{type}:{version}` 做客户端缓存


## 认证机制

所有 REST API 统一使用 **IAM OIDC JWT** 认证，`user_id` 由认证层注入，请求体中不携带 `user_id`。

| 项目            | 值                                                           |
| ------------- | ----------------------------------------------------------- |
| 认证方式          | `Authorization: Bearer <JWT>`                               |
| IdP Discovery | `https://iam.jereh.cn/idp/.well-known/openid-configuration` |
| 验签            | 从 Discovery 的 `jwks_uri` 获取 JWKS 公钥，本地验签                    |
| 身份提取          | JWT `sub` / `preferred_username` claim → `user_id`          |

**设计要点：** `user_id` 从请求体移除，改由 JWT 认证中间件注入，杜绝客户端伪造身份。

## 负责人 (current_owner) 多态设计

任务详情中的 `current_owner` 对象通过 `type` 字段区分负责人类型：

| type      | id 含义         | name/description | metadata 示例    |
| --------- | ------------- | ---------------- | -------------- |
| `human`   | 工号 (102)      | 姓名 + 职位          | 部门、联系方式        |
| `agent`   | Agent ID/Name | 角色描述             | 模型版本、Prompt 版本 |
| `program` | 方法指纹/签名       | 函数名/类名           | 部署环境、实例 ID     |

## 核心业务流程

```
客户端 POST /v1/tasks → 服务端校验 data → 生成 task_id → 启动 LangGraph
→ 运行至 interrupt 节点 → 生成 event_id → 发送 Kafka 消息 (key: user_id:device_id)
→ [推送路径] 客户端消费 Kafka → GET /v1/orchestrations/{type}/versions/{v}/nodes/{node_id}
                → 渲染表单 → POST callback
→ [兜底路径] 客户端轮询 GET /v1/tasks/{id} → 从 pending_callback 获取 node_id
                → GET orchestrations 节点接口 → 渲染表单 → POST callback
→ 服务端校验幂等性 + 参数完整性 → 恢复工作流 → 继续执行
```

## 设计原则

- **编排与实例分离** — 任务详情只返回 `type` + `orchestration_version` + `node_id`，编排定义通过独立接口查询，职责清晰
- **Pull 兜底闭环** — GET 详情的 `pending_callback` 提供编排定位信息，配合编排元数据接口可完整闭环
- **参数契约一致** — 编排定义中的 `form_schema` 是回调 `user_input` 校验的唯一标准
- **防重放** — `event_id` 通过事件存储确保 exactly-once 处理
- **ID 统一** — `task.id` == LangGraph `thread_id`；`task.type` == 编排标识
- **设备级隔离** — Kafka Key `{user_id}:{device_id}` 支持多设备场景下的消息定向投递
- **统一认证** — IAM OIDC JWT 认证，`user_id` 由中间件注入，请求体不含身份信息
