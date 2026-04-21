# 询价任务工作流编排设计

**日期：** 2026-04-21
**状态：** Approved

## 概述

编排一个询价单从创建到 ERP 导入的完整工作流。基于自动询比价智能体 PRD（`raw/planning-artifacts/`），聚焦询价任务的核心流程。

前置任务（拉取 ERP 请购池、物料预览勾选、供应商匹配）在询价任务创建前完成，不属于本编排范围。

## 流程图

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌────────┐
│ 创建询价单 │───→│ 发送询价  │───→│ [报价检查点]   │───→│ 导入ERP   │───→│ 已完成  │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └────────┘
                                       │
                                       │ new_round
                                       ↓
                                 ┌──────────┐
                                 │ 发送询价  │
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

## Interrupt 节点：check_quotes

唯一的 interrupt 节点，采购员在此完成报价处理和业务决策。

### 分支定义

| action | label | target_node | 触发条件 |
|--------|-------|-------------|---------|
| `new_round` | 继续询价 | `send_inquiry` | 存在未报价供应商或对价格不满意 |
| `push_erp` | 导入 ERP | `push_to_erp` | 报价完成，选择中标供应商 |

### new_round 分支 — form_schema

```json
{
  "type": "object",
  "required": ["new_deadline"],
  "properties": {
    "new_deadline": {
      "type": "string",
      "format": "date-time",
      "description": "新一轮报价截止时间，必须晚于当前时间"
    }
  }
}
```

### push_erp 分支 — form_schema

```json
{
  "type": "object",
  "required": ["quotes", "winners"],
  "properties": {
    "quotes": {
      "type": "array",
      "description": "各供应商报价数据（含补录）",
      "items": {
        "type": "object",
        "required": ["supplier_id", "items"],
        "properties": {
          "supplier_id": {
            "type": "string",
            "description": "供应商编码"
          },
          "items": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["material_code", "unit_price_tax_incl", "tax_rate", "currency"],
              "properties": {
                "material_code": { "type": "string", "description": "物料编码" },
                "unit_price_tax_incl": { "type": "number", "description": "含税单价" },
                "tax_rate": { "type": "number", "description": "税率" },
                "currency": { "type": "string", "description": "币种" },
                "delivery_period": { "type": "string", "description": "交货期" },
                "remark": { "type": "string", "description": "备注" }
              }
            }
          }
        }
      }
    },
    "winners": {
      "type": "array",
      "description": "中标供应商及对应物料（按物料维度，支持部分中标）",
      "items": {
        "type": "object",
        "required": ["supplier_id", "material_code"],
        "properties": {
          "supplier_id": { "type": "string", "description": "中标供应商编码" },
          "material_code": { "type": "string", "description": "中标物料编码" }
        }
      }
    }
  }
}
```

## 状态映射

工作流状态与 PRD 询价单状态的对应关系：

| 工作流位置 | PRD 状态 |
|-----------|---------|
| `create_inquiry` 执行中 | 草稿 |
| `send_inquiry` 执行中 | 询价中 |
| `check_quotes` 等待中 | 报价中 / 报价完成 |
| `push_to_erp` 执行中 | 已定标 |
| `completed` | 已完成 |

## YAML 配置

```yaml
name: inquiry
display_name: 询价任务

nodes:
  - id: create_inquiry
    type: action
    display_name: 创建询价单
    description: 根据已确认的物料和供应商数据创建询价单
    next: send_inquiry

  - id: send_inquiry
    type: action
    display_name: 发送询价
    description: 通过 SMTP 向所有供应商发送询价邮件
    next: check_quotes

  - id: check_quotes
    type: interrupt
    display_name: 报价检查点
    description: 补录报价、查看对比表、决策继续询价或导入ERP
    transitions:
      - condition: action == "new_round"
        next: send_inquiry
      - condition: action == "push_erp"
        next: push_to_erp

  - id: push_to_erp
    type: action
    display_name: 导入ERP
    description: 报价数据和中标结果导入 Oracle EBS
    next: completed

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
3. **interrupt 分支** — 验证 `check_quotes` 节点有 2 个 transitions，条件表达式正确
4. **条件路由** — 分别传入 `action == "new_round"` 和 `action == "push_erp"` 验证路由到正确节点

### 集成测试

文件：`tests/integration/test_inquiry_workflow.py`

集成真实数据库（SQLite），mock 程序节点外部依赖，验证完整流程：

1. **正常流程：直接推送 ERP**
   - 创建询价任务 → 执行到 `check_quotes` interrupt
   - 验证数据库中任务状态、pending_callback 正确
   - 回调 `push_erp` 分支（带 quotes + winners）
   - 验证任务流转到 `push_to_erp` → `completed`
   - 验证数据库中任务最终状态为 completed

2. **多轮询价后推送 ERP**
   - 创建询价任务 → 执行到 interrupt
   - 回调 `new_round`（带 new_deadline）
   - 验证任务回到 `send_inquiry`，再次到 interrupt
   - 第二轮回调 `push_erp`
   - 验证任务流转到 completed
   - 验证数据库中记录了两轮询价历史

3. **form_schema 校验**
   - `new_round` 分支：缺少 `new_deadline` 应校验失败
   - `push_erp` 分支：缺少 `quotes` 或 `winners` 应校验失败
   - `push_erp` 分支：`winners` 中引用不存在的 supplier_id 应校验失败

4. **数据库持久化验证**
   - 每次回调后检查 tasks 表中 status、data 字段更新正确
   - 验证 event_store 中 event_id 幂等性（重复回调返回失败）

