# 敏捷开发 Sprint 场景设计

## 1. 场景概述

支持多个任务之间的依赖关系和自动化调度，用于敏捷开发 Sprint 管理。

## 2. 任务模型

### 2.1 任务状态
每个任务都有相同的状态流转：
```
todo → doing → done
         ↓
      failed
```

### 2.2 状态定义

| 状态 | 说明 | 超时 |
|------|------|------|
| `todo` | 待执行，等待依赖满足 | - |
| `doing` | 执行中 | 根据节点配置 |
| `done` | 已完成 | - |
| `failed` | 失败，人类接手 | - |

### 2.3 失败恢复

`failed` 状态支持两种操作：

1. **cancel** - 取消任务（最终状态）
2. **restart** → `todo` - 重新开始

**restart 事务回滚：**
```
Task 1 (开发): done → todo
Task 2 (测试): failed → todo
```

## 3. 任务依赖

### 3.1 依赖关系

```
Task A (开发): todo → doing → done
                         ↓ (触发)
Task B (测试): todo → doing → done
```

**规则：** 前序任务 `done` 后，后序任务才能从 `todo` 开始执行。

### 3.2 数据结构

```sql
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    predecessor_id TEXT NOT NULL,
    successor_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (predecessor_id) REFERENCES tasks(id),
    FOREIGN KEY (successor_id) REFERENCES tasks(id),
    UNIQUE(predecessor_id, successor_id)
);
```

## 4. 调度机制

### 4.1 调度器配置

```yaml
scheduler:
  max_concurrent: 3        # 最大并发任务数
  poll_interval: 5         # 轮询间隔（秒）
```

### 4.2 调度逻辑

每5秒执行一次：
```python
# 1. 查询可执行任务（依赖满足且为todo状态）
SELECT * FROM tasks
WHERE status = 'todo'
AND id NOT IN (
  SELECT successor_id FROM task_dependencies
  WHERE predecessor_id NOT IN (
    SELECT id FROM tasks WHERE status = 'done'
  )
)
ORDER BY created_at ASC
LIMIT (max_concurrent - current_running)

# 2. 乐观锁启动
UPDATE tasks
SET status = 'doing', version = version + 1
WHERE id = ? AND status = 'todo' AND version = ?
```

### 4.3 并发控制

使用**乐观锁**避免多实例重复启动：
- 表结构添加 `version` 字段
- 更新时检查 version，失败则跳过

## 5. 超时与重试

### 5.1 节点配置

```yaml
nodes:
  - id: doing
    type: action
    timeout: 30m
    on_timeout: fail/retry
    retry: 3
```

### 5.2 超时处理

| on_timeout | 行为 |
|------------|------|
| `fail` | 超时不重试，标记为 failed |
| `retry` | 超时消耗 retry 次数 |

### 5.3 失败记录

```json
{
  "status": "failed",
  "failure_info": {
    "reason": "timeout",
    "message": "执行超过30分钟",
    "failed_at": "2025-04-20T10:30:00Z",
    "assignee": "human"
  }
}
```

## 6. 通知机制

进入人类值守节点时发送消息通知。

## 7. API 设计

### 7.1 创建任务依赖
```http
POST /v1/tasks/dependencies
{
  "predecessor_id": "task-1",
  "successor_id": "task-2"
}
```

### 7.2 重启失败任务
```http
POST /v1/tasks/{task_id}/restart
{
  "rollback_dependencies": true
}
```

### 7.3 取消任务
```http
POST /v1/tasks/{task_id}/cancel
```

## 8. 数据库修改

```sql
-- 任务依赖表
CREATE TABLE task_dependencies (...);

-- 任务表添加字段
ALTER TABLE tasks ADD COLUMN version INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN started_at TEXT;
ALTER TABLE tasks ADD COLUMN failure_info TEXT;
```
