"""Configuration loading utilities."""

import json
from pathlib import Path

import pydantic
from loguru import logger

from nanobot.config.schema import Config

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def find_project_dir(cwd: Path | None = None) -> Path | None:
    """Return .nanobot/ in the given directory (default: CWD) if it exists."""
    base = cwd or Path.cwd()
    candidate = base / ".nanobot"
    return candidate if candidate.is_dir() else None


def apply_project_config(config: Config, project_dir: Path) -> None:
    """Merge project-level .nanobot/config.json into the global config (in-place).

    Only additive/non-destructive keys are merged:
    - tools.mcp_servers: project servers are added (project wins on name collision)
    - plugins.modules: project modules are prepended
    - plugins.extra_skill_dirs: project dirs are prepended
    """
    project_config_path = project_dir / "config.json"
    if not project_config_path.exists():
        return
    try:
        with open(project_config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load project config {}: {}", project_config_path, e)
        return

    # Merge MCP servers (project overrides global on name collision)
    from nanobot.config.schema import MCPServerConfig
    raw_tools = data.get("tools", {})
    project_mcps = raw_tools.get("mcpServers", raw_tools.get("mcp_servers", {}))
    for name, srv_data in project_mcps.items():
        try:
            config.tools.mcp_servers[name] = MCPServerConfig.model_validate(srv_data)
        except Exception as e:
            logger.warning("Skipping invalid project MCP server '{}': {}", name, e)

    # Merge plugin modules (project first)
    from nanobot.config.schema import PluginsConfig
    raw_plugins = data.get("plugins", {})
    project_modules = raw_plugins.get("modules", [])
    if project_modules:
        combined = list(project_modules)
        for m in config.plugins.modules:
            if m not in combined:
                combined.append(m)
        config.plugins.modules = combined

    # Merge extra skill dirs (project first)
    project_skill_dirs = raw_plugins.get("extraSkillDirs", raw_plugins.get("extra_skill_dirs", []))
    if project_skill_dirs:
        combined_dirs = list(project_skill_dirs)
        for d in config.plugins.extra_skill_dirs:
            if d not in combined_dirs:
                combined_dirs.append(d)
        config.plugins.extra_skill_dirs = combined_dirs

    logger.info("Applied project config from {}", project_config_path)


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
