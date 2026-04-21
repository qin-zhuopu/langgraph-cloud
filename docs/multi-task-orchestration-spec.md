# 多任务编排功能规格说明

## 1. 背景

当前项目支持单任务的工作流编排，但无法处理多个任务之间的依赖关系。为了支持敏捷开发 Sprint 和 MES 生产制造系统，需要扩展为支持多任务编排。

## 2. 需求场景

### 2.1 敏捷开发 Sprint
- 用户故事拆分为多个子任务（设计、开发、测试、评审）
- 代码审查完成后才能合并
- 测试任务依赖于开发任务完成
- 发布任务依赖于所有测试通过

### 2.2 MES 生产制造系统
- 生产工单包含多个工序（加工→装配→质检→包装）
- 工序必须按顺序执行（串行）
- 多个组件可并行生产，最后汇总组装（并行+汇聚）
- 质检不合格需要返工（回退）

## 3. 核心功能

### 3.1 任务依赖类型

| 类型 | 描述 | 示例 |
|------|------|------|
| **串行 (Serial)** | A 完成后 B 才能开始 | 需求分析 → 系统设计 → 代码开发 |
| **并行 (Parallel)** | A 完成后同时触发 B、C、D | 开发完成后：单元测试、集成测试、文档编写并行执行 |
| **汇聚 (Sync)** | B、C、D 都完成后 E 才能开始 | 所有测试通过后才能发布 |

### 3.2 依赖关系 DSL

用户通过 JSON 定义任务依赖图：

```json
{
  "tasks": [
    {"id": "A", "type": "development", "data": {...}},
    {"id": "B", "type": "testing", "data": {...}},
    {"id": "C", "type": "review", "data": {...}},
    {"id": "D", "type": "deploy", "data": {...}}
  ],
  "dependencies": [
    {"from": "A", "to": "B", "type": "serial"},
    {"from": "A", "to": "C", "type": "parallel"},
    {"from": "B", "to": "D", "type": "sync"},
    {"from": "C", "to": "D", "type": "sync"}
  ]
}
```

### 3.3 执行语义

| 依赖类型 | 触发条件 | 行为 |
|---------|---------|------|
| `serial` | 前置任务完成 | 立即启动后置任务 |
| `parallel` | 前置任务完成 | 同时启动所有后置任务 |
| `sync` | 所有前置任务完成 | 等待汇聚后启动后置任务 |

## 4. 数据模型

### 4.1 新增表结构

```sql
-- 任务依赖关系表
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    predecessor_id TEXT NOT NULL,      -- 前置任务 ID
    successor_id TEXT NOT NULL,        -- 后置任务 ID
    dependency_type TEXT NOT NULL,     -- serial/parallel/sync
    workflow_id TEXT,                  -- 所属工作流 ID（可选，用于批量管理）
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (predecessor_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (successor_id) REFERENCES tasks(id) ON DELETE CASCADE,
    UNIQUE(predecessor_id, successor_id)
);

-- 工作流编排表（可选，用于批量任务管理）
CREATE TABLE task_workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    definition TEXT NOT NULL,          -- JSON 格式的依赖图定义
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/running/completed/failed
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 4.2 任务状态扩展

在现有 `tasks` 表基础上，添加字段：

```sql
ALTER TABLE tasks ADD COLUMN workflow_id TEXT;  -- 所属工作流 ID
ALTER TABLE tasks ADD COLUMN blocked_by TEXT;   -- 被哪个任务阻塞（JSON 数组）
```

## 5. API 设计

### 5.1 创建编排任务

```http
POST /v1/workflows
Content-Type: application/json

{
  "name": "Sprint 1 开发流程",
  "definition": {
    "tasks": [...],
    "dependencies": [...]
  }
}

Response: 201 Created
{
  "workflow_id": "wf-uuid",
  "status": "pending",
  "tasks": [
    {"id": "task-1", "status": "pending", "blocked_by": []},
    {"id": "task-2", "status": "blocked", "blocked_by": ["task-1"]}
  ]
}
```

### 5.2 查询任务依赖

```http
GET /v1/tasks/{task_id}/dependencies

Response: 200 OK
{
  "predecessors": [
    {"id": "task-1", "status": "completed"}
  ],
  "successors": [
    {"id": "task-3", "status": "blocked"},
    {"id": "task-4", "status": "blocked"}
  ]
}
```

### 5.3 任务完成回调

当任务完成时，自动检查并启动依赖任务：

```python
async def on_task_completed(task_id: str):
    # 1. 查找所有依赖此任务的后置任务
    successors = await dependency_repo.get_successors(task_id)

    # 2. 对于每个后置任务，检查是否所有前置任务都完成
    for successor in successors:
        predecessors = await dependency_repo.get_predecessors(successor.id)

        # 3. 根据依赖类型处理
        if successor.dependency_type == "serial":
            await task_service.start_task(successor.id)
        elif successor.dependency_type == "sync":
            if all(p.status == "completed" for p in predecessors):
                await task_service.start_task(successor.id)
```

## 6. 工作流集成

### 6.1 YAML 配置扩展

支持在工作流 YAML 中声明子任务：

```yaml
name: production_workflow
display_name: 生产制造流程

nodes:
  - id: start
    type: action
    next: create_workflow

  - id: create_workflow
    type: action
    action: create_task_orchestration
    config:
      definition:
        tasks:
          - id: machining
            type: todo_workflow
          - id: assembly
            type: todo_workflow
          - id: quality_check
            type: todo_workflow
        dependencies:
          - {from: machining, to: assembly, type: serial}
          - {from: assembly, to: quality_check, type: serial}
    next: wait_complete

  - id: wait_complete
    type: interrupt
    required_params: [confirm]
    transitions:
      - condition: confirm == true
        next: done

  - id: done
    type: terminal
    status: completed
```

## 7. 实现优先级

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 数据库表结构 | P0 | 基础设施 |
| 依赖关系 CRUD | P0 | 核心接口 |
| 任务完成触发器 | P0 | 自动化执行 |
| 工作流批量创建 | P1 | 便捷功能 |
| 依赖图可视化 | P2 | 可选功能 |
| 循环依赖检测 | P2 | 安全特性 |

## 8. 技术风险

| 风险 | 缓解措施 |
|------|---------|
| 循环依赖导致死锁 | 创建时检测环，拒绝非法依赖图 |
| 并发竞争条件 | 使用数据库事务锁 |
| 级联失败传播 | 支持失败策略配置（继续/停止） |
| 性能问题 | 批量查询，缓存依赖关系 |

## 9. 扩展考虑

### 9.1 条件依赖
```json
{"from": "A", "to": "B", "type": "conditional", "condition": "A.status == 'approved'"}
```

### 9.2 动态任务
```json
{"from": "A", "to": "*", "type": "dynamic", "template": "review_{user}"}
```

### 9.3 超时处理
```json
{"from": "A", "to": "B", "type": "serial", "timeout": "24h"}
```
