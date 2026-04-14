# LangGraph Cloud Client

A LangGraph cloud service with local client integration for Human-in-the-Loop (HITL) scenarios. This project demonstrates a production-ready architecture for workflow orchestration with real-time event streaming and human approval processes.

## Features

- **Workflow Orchestration**: YAML-based workflow configuration for flexible business process definition
- **Human-in-the-Loop**: Built-in support for workflow interrupts requiring human input/approval
- **Dual-Mode Client**: Both WebSocket real-time and HTTP polling modes for event delivery
- **SQLite Persistence**: Local SQLite database for task, event, and workflow state storage
- **Event Streaming**: Real-time WebSocket endpoint for live workflow updates
- **Async Architecture**: Fully async Python implementation using FastAPI and asyncio
- **Type Safety**: Pydantic schemas for all DTOs with full type hints
- **Comprehensive Testing**: Unit, integration, and E2E tests with pytest

## Quick Start

### Prerequisites

- Python 3.10 or higher
- pip (Python package installer)

### Setup

1. **Create a virtual environment:**

```bash
python3 -m venv venv
```

2. **Activate the virtual environment:**

On macOS/Linux:
```bash
source venv/bin/activate
```

On Windows:
```bash
venv\Scripts\activate
```

3. **Install dependencies:**

```bash
pip install -e ".[dev]"
```

### Running the Server

Start the LangGraph Cloud service:

```bash
python -m scripts.run_server
```

Or using uvicorn directly:

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

The server will start at `http://localhost:8000`

### Running the Client

Start the CLI client (WebSocket mode by default):

```bash
python -m scripts.run_client
```

For polling mode:

```bash
python -m scripts.run_client --poll
```

With a custom user ID:

```bash
python -m scripts.run_client --user=my_user_id
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root endpoint with service information |
| GET | `/health` | Health check endpoint |
| POST | `/v1/tasks` | Create a new task |
| GET | `/v1/tasks/{task_id}` | Get task details by ID |
| POST | `/v1/tasks/{task_id}/callback` | Submit user input to resume workflow |
| WS | `/ws?user_id={user_id}` | WebSocket endpoint for real-time events |

### Request/Response Examples

**Create Task:**

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "task": {
      "type": "purchase_request",
      "data": {
        "item_name": "Office Chair",
        "quantity": "5",
        "amount": "2500",
        "requester": "John Doe"
      }
    }
  }'
```

**Get Task:**

```bash
curl http://localhost:8000/v1/tasks/{task_id}
```

**Submit Callback:**

```bash
curl -X POST http://localhost:8000/v1/tasks/{task_id}/callback \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "event_123",
    "node_id": "manager_audit",
    "user_input": {
      "approved": true,
      "approver": "manager_001",
      "timestamp": "2024-01-15T10:30:00Z"
    }
  }'
```

## Architecture

### Project Structure

```
langgraph-cloud/
├── app/
│   ├── api/              # FastAPI application and routes
│   │   ├── main.py       # Application factory and lifespan
│   │   ├── routes.py     # REST and WebSocket endpoints
│   │   └── deps.py       # Dependency injection
│   ├── client_sdk/       # Client library and CLI
│   │   ├── cli.py        # Interactive CLI application
│   │   └── websocket_client.py  # WebSocket client
│   ├── domain/           # Domain models and interfaces
│   │   ├── schemas.py    # Pydantic DTOs
│   │   └── interfaces.py # Abstract interfaces
│   ├── infrastructure/   # Data access and messaging
│   │   ├── database.py           # SQLite connection management
│   │   ├── sqlite_repository.py  # Task repository
│   │   ├── event_store.py        # Event storage
│   │   ├── sqlite_bus.py         # Message bus for events
│   │   └── workflow_repo.py      # Workflow configuration storage
│   └── workflow/         # Workflow execution
│       ├── builder.py    # LangGraph graph builder
│       ├── executor.py   # Workflow execution engine
│       ├── checkpointer.py  # State checkpointing
│       └── config/       # YAML workflow definitions
│           └── purchase_request.yml
├── tests/                # Test suite
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── e2e/              # End-to-end tests
├── scripts/              # Utility scripts
│   ├── run_server.py     # Server startup script
│   └── run_client.py     # Client startup script
├── pyproject.toml        # Project configuration
└── README.md
```

### Component Overview

#### Domain Layer
- **Schemas**: Pydantic models for all data transfer objects (Task, EventMessage, CallbackRequest, etc.)
- **Interfaces**: Abstract base classes for repositories and services

#### Infrastructure Layer
- **Database**: SQLite connection and table initialization
- **Repositories**: CRUD operations for tasks, events, and workflows
- **Message Bus**: In-process pub/sub for event distribution
- **Event Store**: Event sourcing for workflow audit trails

#### Workflow Layer
- **Builder**: Constructs LangGraph StateGraph from YAML configuration
- **Executor**: Manages workflow execution with state persistence
- **Checkpointer**: Saves/restores workflow state for resumption

#### API Layer
- **FastAPI Application**: REST endpoints for task management
- **WebSocket**: Real-time event streaming to clients

#### Client SDK
- **WebSocket Client**: Async client with auto-reconnection
- **CLI Application**: Interactive terminal interface

### Workflow Configuration

Workflows are defined in YAML files under `app/workflow/config/`:

```yaml
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
    transitions:
      - condition: is_approved == true
        next: finance_audit
      - condition: is_approved == false
        next: rejected

  - id: approved
    type: terminal
    status: completed
```

## Running Tests

### Run all tests:

```bash
pytest
```

### Run with coverage:

```bash
pytest --cov=app --cov-report=html
```

### Run specific test categories:

```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# E2E tests only
pytest tests/e2e/
```

### Run specific test file:

```bash
pytest tests/unit/test_schemas.py -v
```

## Development

### Code Style

This project follows standard Python conventions:
- Type hints on all functions
- Docstrings for all modules, classes, and public methods
- Pydantic for data validation
- Async/await for I/O operations

### Adding New Workflows

1. Create a new YAML file in `app/workflow/config/`
2. Define nodes with types: `action`, `interrupt`, or `terminal`
3. Use `transitions` with `condition` for branching logic
4. The workflow will be automatically loaded by `WorkflowBuilder`

## License

MIT

## Contributing

Contributions are welcome! Please ensure all tests pass before submitting a pull request.
