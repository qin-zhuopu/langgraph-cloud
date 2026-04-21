# 询价任务工作流编排设计

**日期：** 2026-04-21
**状态：** Approved

## 概述

编排一个询价单从创建到 ERP 导入的完整工作流。基于自动询比价智能体 PRD（`raw/planning-artifacts/`），聚焦询价任务的核心流程。

前置任务（拉取 ERP 请购池、物料预览勾选、供应商匹配）在询价任务创建前完成，不属于本编排范围。

## 流程图

```
┌────────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌────────┐
│ 创建询价单 │───→│ 发送询价 │───→│ [报价检查点] │───→│ 导入ERP  │───→│ 已完成 │
└────────────┘    └──────────┘    └──────────────┘    └──────────┘    └────────┘
                                       │
                                       │ new_round
                                       ↓
                                 ┌──────────┐
                                 │ 发送询价 │
                                 └──────────┘
```

## 节点定义

| # | 节点 ID | 类型 | 负责方 | 说明 |
|---|---------|------|--------|------|
| 1 | `create_inquiry` | action | 程序 | 根据已确认的物料和供应商数据创建询价单 |
| 2 | `send_inquiry` | action | 程序 | 通过 SMTP 向所有供应商发送询价邮件 |
| 3 | `check_quotes` | interrupt | 人类 | 补录/确认报价、查看对比表、决策下一步 |
| 4 | `push_to_erp` | action | 程序 | 报价数据 + 中标结果导入 Oracle EBS |
| 5 | `completed` | terminal | — | 询价单完成 |

## 创建询价单 — task.data 字段定义

创建任务时 `POST /v1/tasks` 的 `task.data` 结构：

| 字段 | 类型 | 必填 | 来源 | 说明 |
|------|------|------|------|------|
| `title` | string | 是 | 手动/自动生成 | 询价单标题 |
| `business_entity` | string | 是 | ERP | 业务实体 |
| `deadline` | datetime | 是 | 手动 | 报价截止时间 |
| `template_id` | string | 是 | 自动匹配/手动 | 询价单模版 ID |
| `is_annual` | boolean | 否 | 手动 | 是否年度谈判，默认 false |
| `remark` | string | 否 | 手动 | 备注 |
| `materials` | array | 是 | ERP/手动 | 物料明细行 |
| `materials[].material_code` | string | 是 | | 物料编码 |
| `materials[].material_desc` | string | 是 | ERP 带出 | 物料描述 |
| `materials[].quantity` | number | 是 | 手动 | 数量，>0 |
| `materials[].unit` | string | 是 | ERP 带出 | 单位 |
| `materials[].need_date` | date | 是 | 手动 | 需要日期 |
| `materials[].category_l4` | string | 是 | ERP 带出 | 四级品类 |
| `suppliers` | array | 是 | 供应商组匹配/手动/AI | 供应商明细行 |
| `suppliers[].supplier_code` | string | 是 | | 供应商编码 |
| `suppliers[].supplier_name` | string | 是 | | 供应商名称 |
| `suppliers[].contact_name` | string | 是 | | 联系人 |
| `suppliers[].contact_phone` | string | 否 | | 联系电话 |
| `suppliers[].email` | string | 是 | | 邮箱（发送询价用） |
| `suppliers[].source` | string | 是 | | 来源：`group_match` / `manual` / `ai_recommend` |

## Interrupt 节点：check_quotes

唯一的 interrupt 节点，采购员在此完成报价处理和业务决策。

### 分支定义

| action | label | target_node | 说明 |
|--------|-------|-------------|------|
| `new_round` | 继续询价 | `send_inquiry` | 选定供应商进入下一轮，淘汰未选中的 |
| `award` | 定标 | `push_to_erp` | 按物料维度选定中标供应商和价格，程序自动导入 ERP |

### new_round 分支 — form_schema

采购员选定参与下一轮的供应商（未选中的视为淘汰），并设置新的报价截止时间。

```json
{
  "type": "object",
  "required": ["new_deadline", "supplier_codes"],
  "properties": {
    "new_deadline": {
      "type": "string",
      "format": "date-time",
      "description": "新一轮报价截止时间，必须晚于当前时间"
    },
    "supplier_codes": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1,
      "description": "参与下一轮询价的供应商编码列表，未选中的视为淘汰"
    }
  }
}
```

### award 分支 — form_schema

采购员按物料维度选定中标供应商和确认中标价格。每个物料绑定一个供应商和一个价格。

```json
{
  "type": "object",
  "required": ["winners"],
  "properties": {
    "winners": {
      "type": "array",
      "minItems": 1,
      "description": "中标结果，每条是一个物料的定标决策（物料×供应商×价格）",
      "items": {
        "type": "object",
        "required": ["material_code", "supplier_code", "awarded_price"],
        "properties": {
          "material_code": { "type": "string", "description": "物料编码" },
          "supplier_code": { "type": "string", "description": "中标供应商编码" },
          "awarded_price": { "type": "number", "description": "中标价格（默认取报价，采购员可改）" }
        }
      }
    }
  }
}
```

**示例：** 3 个物料、5 家供应商报价后定标

```json
{
  "winners": [
    { "material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.00 },
    { "material_code": "C050086211", "supplier_code": "SUP_DEXIN",   "awarded_price": 2200.00 },
    { "material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.00 }
  ]
}
```

## 状态映射

工作流状态与 PRD 询价单状态的对应关系：

| 工作流 status | PRD 状态 |
|-----------|---------|
| `awaiting_create_inquiry`（不会出现，action 节点自动执行） | 草稿 |
| `awaiting_send_inquiry`（不会出现，action 节点自动执行） | 询价中 |
| `awaiting_check_quotes` | 报价中 / 报价完成 |
| `awaiting_push_to_erp`（不会出现，action 节点自动执行） | 已定标 |
| `completed` | 已完成 |

> 实际运行中，action 节点会自动执行并流转，客户端只会观察到 `awaiting_check_quotes` 和 `completed` 两个稳态。

## Mock 测试数据

### 供应商

| 编码 | 名称 | 联系人 | 邮箱 | 来源 |
|------|------|--------|------|------|
| `SUP_JINGLIN` | 河北京霖拖链技术有限公司 | 王经理 | wang@jinglin.com | group_match |
| `SUP_DEXIN` | 河南德信安全科技有限公司 | 李工 | li@dexin.com | group_match |
| `SUP_SHIYI` | 山东拾一科技服务有限公司 | 张总 | zhang@shiyi.com | manual |
| `SUP_TONGZHOU` | 北京同洲维普科技有限公司 | 赵经理 | zhao@tongzhou.com | ai_recommend |
| `SUP_WANSHAN` | 深圳市万山文创有限公司 | 陈总 | chen@wanshan.com | ai_recommend |

### 物料

| 编码 | 描述 | 数量 | 单位 | 四级品类 |
|------|------|------|------|---------|
| `C050066547` | 8路模拟量输出模块 | 10 | 个 | 自动化控制 |
| `C050086211` | 高速计数模块 | 5 | 个 | 自动化控制 |
| `C050099301` | 工业以太网交换机 | 20 | 台 | 网络设备 |

### 多轮询价场景

**第一轮：** 5 家供应商全部参与
**第二轮（new_round）：** 淘汰万山（报价过高），4 家继续
```json
{ "new_deadline": "2026-05-15T18:00:00", "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN", "SUP_SHIYI", "SUP_TONGZHOU"] }
```
**第三轮（award）：** 定标
```json
{
  "winners": [
    { "material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.00 },
    { "material_code": "C050086211", "supplier_code": "SUP_DEXIN",   "awarded_price": 2200.00 },
    { "material_code": "C050099301", "supplier_code": "SUP_JINGLIN", "awarded_price": 680.00 }
  ]
}
```

## YAML 配置

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

## 测试策略

### Mock 对象

程序节点（action 类型）在测试中需要 mock：

| 节点 | Mock 内容 | 说明 |
|------|----------|------|
| `create_inquiry` | Mock 创建询价单的数据库写入 | 返回固定 task_id，不实际操作 ERP |
| `send_inquiry` | Mock SMTP 邮件发送 | 记录调用参数，不实际发邮件 |
| `push_to_erp` | Mock Oracle EBS API 调用 | 模拟成功/失败响应，不实际调 ERP |

interrupt 节点（`check_quotes`）是唯一的真实人类交互点，在测试中通过 `WorkflowExecutor` 的 `resume` 接口模拟用户回调。

### Unit 测试

文件：`tests/unit/test_inquiry_workflow.py`

验证 WorkflowBuilder 能正确构建询价工作流图：

1. **构建工作流** — 加载 `inquiry.yml` 配置，build 成功，compile 通过
2. **节点结构** — 验证 5 个节点类型正确（3 action + 1 interrupt + 1 terminal）
3. **interrupt 分支** — 验证 `check_quotes` 节点有 2 个 transitions（new_round / award）
4. **条件路由** — 分别传入 `action == "new_round"` 和 `action == "award"` 验证路由到正确节点

### 集成测试

文件：`tests/integration/test_inquiry_workflow.py`

集成真实数据库（SQLite），mock 程序节点外部依赖，验证完整流程：

1. **正常流程：直接定标**
   - 创建询价任务（5 家供应商、3 个物料）→ 执行到 `check_quotes` interrupt
   - 验证任务状态为 `awaiting_check_quotes`，`task["pending_callback"]` 包含 event_id 和 node_id
   - 回调 action=`award`（带 winners），user_input 通过 form_schema 校验
   - 验证任务流转到 `push_to_erp` → `completed`
   - 验证 `task["pending_callback"]` 为 null

2. **多轮询价后定标**
   - 创建询价任务（5 家供应商）→ 执行到 interrupt
   - 第一轮回调 action=`new_round`（淘汰万山，4 家继续，新截止时间）
   - 验证任务回到 `send_inquiry`，再次到 interrupt，状态仍为 `awaiting_check_quotes`
   - 验证新的 `pending_callback.event_id` 与第一轮不同
   - 第二轮回调 action=`award`（3 个物料分别选定供应商和价格）
   - 验证任务最终状态为 `completed`

3. **form_schema 校验**
   - `new_round` 分支：缺少 `supplier_codes` 应返回 400
   - `new_round` 分支：`supplier_codes` 为空数组应返回 400
   - `award` 分支：缺少 `winners` 应返回 400
   - `award` 分支：winner 缺少 `awarded_price` 应返回 400
   - 无效 action（如 `cancel`）应返回 400

4. **数据库持久化验证**
   - 每次回调后检查 tasks 表中 status、data 字段更新正确
   - 验证 event_store 中 event_id 幂等性（重复回调返回失败）
