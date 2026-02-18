"""
VaultMaster Plugin System

Plugins extend VaultMaster with custom backup types, storage backends,
and notification channels. Each plugin is a Python module that registers
itself via entry points or by placing files in the plugins/ directory.

Plugin types:
  - BackupPlugin: Custom backup strategies (e.g. WordPress, MySQL, MongoDB)
  - StoragePlugin: Custom storage backends
  - NotificationPlugin: Custom notification channels

Example plugin structure:
  plugins/
    wordpress/
      __init__.py      # Plugin metadata
      backup.py        # BackupPlugin implementation
      manifest.json    # Plugin manifest
"""

import importlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Plugin registry
_backup_plugins: dict[str, "BackupPlugin"] = {}
_storage_plugins: dict[str, "StoragePlugin"] = {}
_notification_plugins: dict[str, "NotificationPlugin"] = {}


class BackupPlugin:
    """Base class for backup plugins."""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    backup_type: str = ""  # Unique identifier, e.g. "wordpress", "mongodb"
    icon: str = "⚡"

    async def validate_config(self, config: dict) -> tuple[bool, str]:
        """Validate source_config before running backup."""
        return True, "OK"

    async def run_backup(self, server: Any, config: dict, work_dir: str) -> tuple[bool, str, str | None]:
        """
        Execute the backup.
        Returns: (success, message, artifact_path_or_none)
        """
        raise NotImplementedError

    async def run_restore(self, server: Any, config: dict, artifact_path: str) -> tuple[bool, str]:
        """
        Execute a restore from an artifact.
        Returns: (success, message)
        """
        raise NotImplementedError

    def get_config_schema(self) -> list[dict]:
        """Return JSON schema for the plugin's configuration fields."""
        return []


class StoragePlugin:
    """Base class for storage plugins."""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    backend_type: str = ""

    async def upload(self, local_path: str, remote_path: str, config: dict) -> tuple[bool, str]:
        raise NotImplementedError

    async def download(self, remote_path: str, local_path: str, config: dict) -> tuple[bool, str]:
        raise NotImplementedError

    async def delete(self, remote_path: str, config: dict) -> tuple[bool, str]:
        raise NotImplementedError

    async def test_connection(self, config: dict) -> tuple[bool, str]:
        raise NotImplementedError

    def get_config_schema(self) -> list[dict]:
        return []


class NotificationPlugin:
    """Base class for notification plugins."""
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    channel_type: str = ""

    async def send(self, message: str, config: dict) -> tuple[bool, str]:
        raise NotImplementedError

    def get_config_schema(self) -> list[dict]:
        return []


def register_backup_plugin(plugin: BackupPlugin):
    """Register a backup plugin."""
    _backup_plugins[plugin.backup_type] = plugin
    logger.info(f"Registered backup plugin: {plugin.name} ({plugin.backup_type})")


def register_storage_plugin(plugin: StoragePlugin):
    """Register a storage plugin."""
    _storage_plugins[plugin.backend_type] = plugin
    logger.info(f"Registered storage plugin: {plugin.name} ({plugin.backend_type})")


def register_notification_plugin(plugin: NotificationPlugin):
    """Register a notification plugin."""
    _notification_plugins[plugin.channel_type] = plugin
    logger.info(f"Registered notification plugin: {plugin.name} ({plugin.channel_type})")


def get_backup_plugins() -> dict[str, BackupPlugin]:
    return _backup_plugins.copy()


def get_storage_plugins() -> dict[str, StoragePlugin]:
    return _storage_plugins.copy()


def get_notification_plugins() -> dict[str, NotificationPlugin]:
    return _notification_plugins.copy()


def get_all_plugins() -> list[dict]:
    """Return metadata for all registered plugins."""
    plugins = []
    for p in _backup_plugins.values():
        plugins.append({"type": "backup", "name": p.name, "backup_type": p.backup_type, "description": p.description, "version": p.version, "icon": p.icon})
    for p in _storage_plugins.values():
        plugins.append({"type": "storage", "name": p.name, "backend_type": p.backend_type, "description": p.description, "version": p.version})
    for p in _notification_plugins.values():
        plugins.append({"type": "notification", "name": p.name, "channel_type": p.channel_type, "description": p.description, "version": p.version})
    return plugins


def load_plugins(plugins_dir: str | None = None):
    """Discover and load plugins from the plugins directory."""
    if plugins_dir is None:
        plugins_dir = os.environ.get("VAULTMASTER_PLUGINS_DIR", "/app/plugins")

    plugins_path = Path(plugins_dir)
    if not plugins_path.exists():
        logger.info(f"Plugins directory not found: {plugins_dir}")
        return

    for item in plugins_path.iterdir():
        if item.is_dir() and (item / "__init__.py").exists():
            try:
                module = importlib.import_module(f"plugins.{item.name}")
                if hasattr(module, "register"):
                    module.register()
                    logger.info(f"Loaded plugin: {item.name}")
            except Exception as e:
                logger.error(f"Failed to load plugin {item.name}: {e}")
