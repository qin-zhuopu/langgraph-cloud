# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run server
python -m scripts.run_server
# or: uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

# Run client (WebSocket mode by default)
python -m scripts.run_client
python -m scripts.run_client --poll  # polling mode
python -m scripts.run_client --user=my_user_id

# Tests
pytest                              # all tests
pytest tests/unit/                  # unit tests only
pytest tests/integration/           # integration tests only
pytest tests/e2e/                   # e2e tests only
pytest tests/unit/test_schemas.py -v  # specific file
pytest --cov=app --cov-report=html  # with coverage

# If network issues occur, use proxy: export http_proxy=http://192.168.0.106:8080 https_proxy=http://192.168.0.106:8080
```

## Architecture Overview

This is a **DDD-lite** (Domain-Driven Design) layered architecture designed for evolvability. The key design principle: infrastructure (SQLite, message buses) is abstracted behind domain interfaces, making migration to production technologies (PostgreSQL, Kafka) straightforward.

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer (FastAPI)        ← REST + WebSocket endpoints    │
├─────────────────────────────────────────────────────────────┤
│  Service Layer (TaskService) ← Orchestration, no domain logic│
├─────────────────────────────────────────────────────────────┤
│  Domain Layer                 ← Interfaces + DTOs only      │
│  - interfaces.py: ITaskRepository, IMessageBus, IEventStore │
│  - schemas.py: Pydantic DTOs                                │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer         ← SQLite implementations       │
│  - sqlite_repository.py, sqlite_bus.py, event_store.py      │
├─────────────────────────────────────────────────────────────┤
│  Workflow Layer               ← LangGraph orchestration     │
│  - builder.py: YAML → StateGraph                            │
│  - executor.py: execute/resume with interrupt handling       │
└─────────────────────────────────────────────────────────────┘
```

## Key Architectural Patterns

### 1. Dependency Inversion
All service dependencies are injected as abstract interfaces (`ITaskRepository`, `IMessageBus`, etc.). The concrete implementations live in `infrastructure/`. See `app/api/deps.py` for dependency injection setup.

### 2. TaskService Orchestration
`TaskService` is the single entry point for task operations. It coordinates:
- Task creation → loads workflow config → builds graph → executes
- Callback → validates event not consumed → marks consumed → resumes workflow

### 3. Workflow Execution
- `thread_id` == `task_id` for LangGraph checkpointing
- Workflows snapshot their config version at creation time (`workflow_version` field)
- Tasks created with config v1 continue using v1 even if v2 is deployed

### 4. Message Bus Dual Mode
- **WebSocket (primary)**: Real-time push via `/ws?user_id={id}`
- **Polling (fallback)**: Clients can poll `GET /v1/tasks/{id}` and consume from `IMessageBus.subscribe()`

### 5. Event Replay Protection
Each callback includes an `event_id`. `IEventStore.mark_consumed()` uses SQLite transaction locks to ensure each event is processed exactly once. Returns `False` if already consumed.

### 6. YAML Workflow Configuration
Workflows are defined in `app/workflow/config/*.yaml`:
- Node types: `action`, `interrupt` (waits for human input), `terminal`
- `transitions` with `condition` expressions for branching
- Loaded via `WorkflowBuilder`, versioned in `workflow_versions` table

## Adding a New Workflow

1. Create YAML file in `app/workflow/config/`
2. Define nodes with `type: action|interrupt|terminal`
3. Add `transitions` with Jinja-style `condition: "{{ field == value }}"`
4. No code changes needed—`WorkflowBuilder` auto-loads from config

## Human-in-the-Loop Flow

1. Client creates task via `POST /v1/tasks`
2. Workflow runs until hitting `type: interrupt` node
3. `WorkflowExecutor` publishes `EventMessage` to `IMessageBus`
4. Client receives via WebSocket or polling
5. Client calls `POST /v1/tasks/{id}/callback` with `event_id`, `node_id`, `user_input`
6. `TaskService.callback()` validates `event_id` not consumed, marks consumed, resumes workflow

## Production Migration Path

The architecture is designed for easy migration:

| Current (MVP) | Production Target |
|---------------|-------------------|
| SQLite | PostgreSQL |
| SQLiteMessageBus | Kafka/RabbitMQ |
| BEGIN IMMEDIATE locks | Redis locks / PostgreSQL advisory locks |

To migrate: implement new classes in `infrastructure/` that satisfy the domain interfaces—no changes to service/logic layers needed.
