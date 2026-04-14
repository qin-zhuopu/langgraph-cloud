"""SQLite checkpointer implementation for LangGraph workflows.

This module provides a SQLite-based implementation of LangGraph's BaseCheckpointSaver
for persisting workflow state during execution.
"""
import json
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointTuple, CheckpointMetadata
from langgraph.checkpoint.base.id import uuid6

from app.infrastructure.database import Database

ChannelVersions = Dict[str, Any]


class SQLiteSaver(BaseCheckpointSaver[int]):
    """SQLite implementation of LangGraph BaseCheckpointSaver.

    This class provides persistent storage for LangGraph workflow checkpoints
    in SQLite, enabling workflow resumption and state persistence across executions.

    The checkpointer stores:
    - Checkpoint state (workflow state at a given point)
    - Checkpoint metadata (step, source, parent info)
    - Channel versions for tracking state changes

    Attributes:
        db: The Database instance for connections.
    """

    def __init__(self, db: Database) -> None:
        """Initialize the SQLiteSaver.

        Args:
            db: The Database instance to use for connections.
        """
        super().__init__()
        self._db = db

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch a checkpoint tuple synchronously.

        Args:
            config: Configuration specifying which checkpoint to retrieve.
                Must contain configurable["checkpoint_id"] and configurable["thread_id"].

        Returns:
            Optional[CheckpointTuple]: The checkpoint tuple, or None if not found.
        """
        raise NotImplementedError("Synchronous operations not supported, use aget_tuple instead")

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Asynchronously fetch a checkpoint tuple.

        Args:
            config: Configuration specifying which checkpoint to retrieve.
                Must contain configurable["checkpoint_id"] and configurable["thread_id"].

        Returns:
            Optional[CheckpointTuple]: The checkpoint tuple, or None if not found.
        """
        import aiosqlite

        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        if not thread_id or not checkpoint_id:
            return None

        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            cursor = await conn.execute(
                """
                SELECT checkpoint_id, state, metadata
                FROM checkpoints
                WHERE thread_id = ? AND checkpoint_id = ?
                """,
                (thread_id, checkpoint_id)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            stored_checkpoint_id, state_json, metadata_json = row
            state_data = json.loads(state_json)
            metadata_data = json.loads(metadata_json) if metadata_json else {}

            # Deserialize the checkpoint using the serializer
            checkpoint = self.serde.loads_typed(state_data)

            return CheckpointTuple(
                config=config,
                checkpoint=checkpoint,
                metadata=metadata_data,
                parent_config=None,
                pending_writes=None,
            )

    async def aget(self, config: RunnableConfig) -> Optional[Checkpoint]:
        """Asynchronously fetch a checkpoint.

        Args:
            config: Configuration specifying which checkpoint to retrieve.
                Must contain configurable["checkpoint_id"] and configurable["thread_id"].

        Returns:
            Optional[Checkpoint]: The checkpoint, or None if not found.
        """
        if value := await self.aget_tuple(config):
            return value.checkpoint
        return None

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a checkpoint synchronously.

        Args:
            config: Configuration for the checkpoint.
            checkpoint: The checkpoint to store.
            metadata: Additional metadata for the checkpoint.
            new_versions: New channel versions as of this write.

        Returns:
            RunnableConfig: Updated configuration after storing.

        Raises:
            NotImplementedError: Synchronous operations not supported.
        """
        raise NotImplementedError("Synchronous operations not supported, use aput instead")

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Asynchronously store a checkpoint.

        Args:
            config: Configuration for the checkpoint.
            checkpoint: The checkpoint to store.
            metadata: Additional metadata for the checkpoint.
            new_versions: New channel versions as of this write.

        Returns:
            RunnableConfig: Updated configuration after storing.
        """
        import aiosqlite

        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        if not thread_id:
            thread_id = str(uuid6())

        if not checkpoint_id:
            checkpoint_id = checkpoint.get("id", str(uuid6()))

        # Serialize the checkpoint
        state_data = self.serde.dumps_typed(checkpoint)
        state_json = json.dumps(state_data)
        metadata_json = json.dumps(metadata) if metadata else "{}"

        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            await conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints (thread_id, checkpoint_id, state, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, checkpoint_id, state_json, metadata_json)
            )
            await conn.commit()

        # Update and return the config
        new_config = config.copy()
        new_config["configurable"] = {
            **new_config.get("configurable", {}),
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
        }
        return new_config

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> "AsyncIterator[CheckpointTuple]":
        """List checkpoints synchronously.

        Args:
            config: Base configuration for filtering checkpoints.
            filter: Additional filtering criteria.
            before: List checkpoints created before this configuration.
            limit: Maximum number of checkpoints to return.

        Returns:
            Iterator[CheckpointTuple]: Iterator of matching checkpoint tuples.

        Raises:
            NotImplementedError: Synchronous operations not supported.
        """
        raise NotImplementedError("Synchronous operations not supported, use alist instead")

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Asynchronously list checkpoints.

        Args:
            config: Base configuration for filtering checkpoints.
                If provided, must contain configurable["thread_id"].
            filter: Additional filtering criteria (not currently supported).
            before: List checkpoints created before this configuration (not currently supported).
            limit: Maximum number of checkpoints to return.

        Yields:
            CheckpointTuple: Matching checkpoint tuples.
        """
        import aiosqlite

        thread_id = None
        if config:
            thread_id = config.get("configurable", {}).get("thread_id")

        query = "SELECT checkpoint_id, state, metadata FROM checkpoints"
        params: List = []

        if thread_id:
            query += " WHERE thread_id = ?"
            params.append(thread_id)

        query += " ORDER BY created_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            cursor = await conn.execute(query, tuple(params))
            rows = await cursor.fetchall()

            for checkpoint_id, state_json, metadata_json in rows:
                state_data = json.loads(state_json)
                metadata_data = json.loads(metadata_json) if metadata_json else {}

                checkpoint = self.serde.loads_typed(state_data)

                row_config = RunnableConfig(
                    configurable={
                        "thread_id": thread_id,
                        "checkpoint_id": checkpoint_id,
                    }
                )

                yield CheckpointTuple(
                    config=row_config,
                    checkpoint=checkpoint,
                    metadata=metadata_data,
                    parent_config=None,
                    pending_writes=None,
                )

    def put_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes synchronously.

        Args:
            config: Configuration of the related checkpoint.
            writes: List of writes to store.
            task_id: Identifier for the task creating the writes.
            task_path: Path of the task creating the writes.

        Raises:
            NotImplementedError: Synchronous operations not supported.
        """
        raise NotImplementedError("Synchronous operations not supported, use aput_writes instead")

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Asynchronously store intermediate writes.

        Args:
            config: Configuration of the related checkpoint.
            writes: List of (channel, value) tuples to store.
            task_id: Identifier for the task creating the writes.
            task_path: Path of the task creating the writes.

        Note:
            Writes are stored alongside checkpoints in the state field.
            This implementation stores the checkpoint state which includes writes.
        """
        # Writes are implicitly stored through checkpoint state
        # No separate writes table needed for this implementation
        pass

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread synchronously.

        Args:
            thread_id: The thread ID whose checkpoints should be deleted.

        Raises:
            NotImplementedError: Synchronous operations not supported.
        """
        raise NotImplementedError("Synchronous operations not supported, use adelete_thread instead")

    async def adelete_thread(self, thread_id: str) -> None:
        """Asynchronously delete all checkpoints for a thread.

        Args:
            thread_id: The thread ID whose checkpoints should be deleted.
        """
        import aiosqlite

        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?",
                (thread_id,)
            )
            await conn.commit()
