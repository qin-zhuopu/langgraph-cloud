"""FastAPI application factory and startup configuration.

This module creates the FastAPI application with all routes,
startup/shutdown events, and dependency injection setup.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.deps import set_task_service
from app.api.routes import router
from app.domain.interfaces import IMessageBus
from app.infrastructure.database import Database
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


@dataclass
class AppState:
    """Application state holding service instances.

    This is stored in app.state for access during request handling.
    """

    database: Database
    task_service: TaskService
    message_bus: IMessageBus


# Global app state reference
_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    """Get the current application state.

    Returns:
        AppState: The current application state.

    Raises:
        RuntimeError: If the app has not been initialized.
    """
    if _app_state is None:
        raise RuntimeError("Application state not initialized")
    return _app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager handling startup and shutdown.

    Startup:
    1. Initialize database connection
    2. Create all repositories and services
    3. Load workflow configurations
    4. Register dependencies

    Shutdown:
    1. Close database connections

    Args:
        app: The FastAPI application instance.
    """
    # Configuration - in production, load from environment
    db_path = "langgraph_cloud.db"

    # Initialize database
    database = Database(db_path)
    conn = await database.connect()
    await database.init_tables(conn)
    await conn.close()

    # Initialize repositories
    task_repo = SQLiteTaskRepository(database)
    message_bus = SQLiteMessageBus(database)
    event_store = SQLiteEventStore(database)
    workflow_repo = SQLiteWorkflowRepo(database)

    # Initialize workflow components
    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    # Initialize task service
    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )

    # Set global dependency
    set_task_service(task_service)

    # Store app state globally
    global _app_state
    _app_state = AppState(
        database=database,
        task_service=task_service,
        message_bus=message_bus,
    )

    # Store state in app for access in routes
    app.state.database = database
    app.state.task_service = task_service
    app.state.message_bus = message_bus

    yield

    # Shutdown: close connections
    # SQLite connections are automatically closed when out of scope
    _app_state = None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: The configured application instance.
    """
    app = FastAPI(
        title="LangGraph Cloud Service",
        description="LangGraph cloud service with local client integration for Human-in-the-Loop scenarios",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include routes
    app.include_router(router)

    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint providing service information."""
        return {
            "service": "LangGraph Cloud Service",
            "version": "0.1.0",
            "status": "running",
        }

    # Health check
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    # Exception handlers
    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc):
        """Handle ValueError exceptions."""
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_value", "message": str(exc)}},
        )

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request, exc):
        """Handle RuntimeError exceptions."""
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "runtime_error", "message": str(exc)}},
        )

    return app


# Application instance for use by ASGI servers
app = create_app()
