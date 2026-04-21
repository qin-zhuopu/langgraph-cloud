"""FastAPI application factory and startup configuration.

This module creates the FastAPI application with all routes,
startup/shutdown events, and dependency injection setup.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.deps import set_task_service, set_workflow_repo
from app.api.routes import router
from app.api.adapter import adapter_router
from app.config import AppConfig, load_config
from app.domain.interfaces import IMessageBus
from app.infrastructure.database import Database
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.kafka_producer import KafkaEventProducer
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


async def _load_workflow_configs(
    builder: WorkflowBuilder,
    workflow_repo: "SQLiteWorkflowRepo",
) -> None:
    """Load all YAML workflow configurations into the database.

    Scans the workflow config directory for .yml files and saves each one
    as the active version in the workflow_versions table.
    """
    from pathlib import Path

    config_dir = Path(__file__).parent.parent / "workflow" / "config"
    for yml_file in config_dir.glob("*.yml"):
        workflow_name = yml_file.stem
        config = builder.load_config(workflow_name)
        # Save as v1 active version (idempotent via INSERT OR REPLACE)
        await workflow_repo.save_version(
            version="v1",
            workflow_name=workflow_name,
            config=config,
            active=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager handling startup and shutdown."""
    # Load configuration
    app_config: AppConfig = getattr(app, "_app_config", None) or load_config()

    # Initialize database
    database = Database(app_config.db_path)
    conn = await database.connect()
    await database.init_tables(conn)
    await conn.close()

    # Initialize repositories
    task_repo = SQLiteTaskRepository(database)
    message_bus = SQLiteMessageBus(database)
    event_store = SQLiteEventStore(database)
    workflow_repo = SQLiteWorkflowRepo(database)

    # Initialize Kafka producer (optional)
    kafka_producer = None
    if app_config.kafka_brokers:
        kafka_producer = KafkaEventProducer()
        await kafka_producer.start(app_config.kafka_brokers)

    # Initialize workflow components
    builder = WorkflowBuilder()
    executor = WorkflowExecutor(
        message_bus,
        kafka_producer=kafka_producer,
        kafka_topic=app_config.kafka_topic,
    )

    # Load workflow configurations from YAML files into the database
    await _load_workflow_configs(builder, workflow_repo)

    # Initialize task service
    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )

    # Set global dependencies
    set_task_service(task_service)
    set_workflow_repo(workflow_repo)

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

    # Shutdown
    if kafka_producer:
        await kafka_producer.stop()
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
    app.include_router(adapter_router)

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
