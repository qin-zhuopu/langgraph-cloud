"""Unit tests for SQLiteWorkflowRepo."""
import pytest
import aiosqlite
from app.domain.interfaces import IWorkflowRepo
from app.infrastructure.database import Database


class TestSQLiteWorkflowRepo:
    """Tests for SQLiteWorkflowRepo implementation."""

    def test_implements_interface(self, workflow_repo):
        """Verify SQLiteWorkflowRepo implements IWorkflowRepo interface."""
        assert isinstance(workflow_repo, IWorkflowRepo)

    @pytest.mark.asyncio
    async def test_save_and_get_active(self, workflow_repo, db):
        """Test saving a workflow version and retrieving the active one."""
        # Arrange
        workflow_name = "test_workflow"
        version = "v1"
        config = {"graph": {"nodes": ["a", "b"]}, "entry_point": "a"}

        # Act - save the workflow version
        await workflow_repo.save_version(version, workflow_name, config, active=True)

        # Assert - retrieve the active version
        result = await workflow_repo.get_active(workflow_name)

        assert result is not None
        assert result["version"] == version
        assert result["workflow_name"] == workflow_name
        assert result["config"] == config
        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_get_by_version(self, workflow_repo, db):
        """Test retrieving a specific workflow version."""
        # Arrange
        workflow_name = "version_test_workflow"
        version = "v2"
        config = {"graph": {"nodes": ["x", "y"]}, "entry_point": "x"}

        await workflow_repo.save_version(version, workflow_name, config, active=True)

        # Act - retrieve specific version
        result = await workflow_repo.get_by_version(workflow_name, version)

        # Assert
        assert result is not None
        assert result["version"] == version
        assert result["workflow_name"] == workflow_name
        assert result["config"] == config

    @pytest.mark.asyncio
    async def test_get_active_returns_latest(self, workflow_repo, db):
        """Test that get_active returns the latest version marked as active."""
        # Arrange
        workflow_name = "multi_version_workflow"
        config_v1 = {"graph": {"nodes": ["a"]}, "entry_point": "a"}
        config_v2 = {"graph": {"nodes": ["a", "b"]}, "entry_point": "a"}
        config_v3 = {"graph": {"nodes": ["a", "b", "c"]}, "entry_point": "a"}

        # Act - save multiple versions, only v3 is active
        await workflow_repo.save_version("v1", workflow_name, config_v1, active=False)
        await workflow_repo.save_version("v2", workflow_name, config_v2, active=False)
        await workflow_repo.save_version("v3", workflow_name, config_v3, active=True)

        # Assert - active should be v3
        result = await workflow_repo.get_active(workflow_name)

        assert result is not None
        assert result["version"] == "v3"
        assert result["config"] == config_v3

    @pytest.mark.asyncio
    async def test_get_active_nonexistent_workflow(self, workflow_repo):
        """Test getting active version for a non-existent workflow."""
        # Act
        result = await workflow_repo.get_active("nonexistent_workflow")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_version_nonexistent(self, workflow_repo):
        """Test getting a non-existent version."""
        # Act
        result = await workflow_repo.get_by_version("some_workflow", "v999")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_save_version_updates_existing(self, workflow_repo, db):
        """Test that saving a version updates existing entry."""
        # Arrange
        workflow_name = "update_test_workflow"
        version = "v1"
        config_old = {"graph": {"nodes": ["a"]}, "entry_point": "a"}
        config_new = {"graph": {"nodes": ["a", "b", "c"]}, "entry_point": "a"}

        # Save first version
        await workflow_repo.save_version(version, workflow_name, config_old, active=True)

        # Act - update with new config
        await workflow_repo.save_version(version, workflow_name, config_new, active=True)

        # Assert - should have the new config
        result = await workflow_repo.get_by_version(workflow_name, version)
        assert result is not None
        assert result["config"] == config_new

    @pytest.mark.asyncio
    async def test_save_version_inserts_row(self, workflow_repo, db):
        """Test that save_version inserts a row in the workflow_versions table."""
        # Arrange
        workflow_name = "insert_test_workflow"
        version = "v1"
        config = {"graph": {"nodes": ["test"]}, "entry_point": "test"}

        # Act
        await workflow_repo.save_version(version, workflow_name, config, active=True)

        # Assert - verify row was inserted
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT version, workflow_name, config, active FROM workflow_versions WHERE version = ? AND workflow_name = ?",
                (version, workflow_name)
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == version
            assert row[1] == workflow_name
            # config is stored as JSON string
            assert "test" in row[2]
            assert row[3] == 1  # active flag should be 1
