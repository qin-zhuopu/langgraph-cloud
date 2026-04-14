"""Workflow configuration loader module."""

import yaml
from pathlib import Path
from typing import Any, Dict


def load_workflow_config(workflow_name: str) -> Dict[str, Any]:
    """
    Load workflow configuration from YAML file.

    Args:
        workflow_name: Name of the workflow to load (without .yml extension)

    Returns:
        Dict containing the workflow configuration

    Raises:
        FileNotFoundError: If the workflow configuration file does not exist

    Example:
        >>> config = load_workflow_config("purchase_request")
        >>> print(config["display_name"])
        采购申请审批流程
    """
    config_dir = Path(__file__).parent
    config_file = config_dir / f"{workflow_name}.yml"

    if not config_file.exists():
        raise FileNotFoundError(
            f"Workflow configuration not found: {config_file}"
        )

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


__all__ = ["load_workflow_config"]
