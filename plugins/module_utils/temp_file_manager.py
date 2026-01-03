# -*- coding: utf-8 -*-

# Copyright: Aleksander Shevchenko <kudato@me.com>
# SPDX-License-Identifier: MIT

"""Temporary File Manager for Ansible Action Plugins.

This module provides a utility class for managing temporary files and
directories in Ansible action plugins. It creates a temporary directory
and provides methods to create files within it, with automatic cleanup
capabilities.

The TempFileManager is designed to be used within Ansible action plugins
where temporary files need to be created, managed, and cleaned up after
plugin execution.

Example:
    from ansible_collections.kudato.fcos.plugins.module_utils.temp_file_manager import TempFileManager

    manager = TempFileManager(prefix="my_plugin_")
    temp_file = manager.write_to_file("content", suffix=".txt")
    # ... use temp_file ...
    manager.cleanup()

Note:
    Always call cleanup() when done to remove temporary files and
    directories. The cleanup method is idempotent and safe to call
    multiple times.
"""

from __future__ import annotations

import shutil
import tempfile


class TempFileManager:
    """Temporary file manager for Ansible action plugins.

    Creates a temporary directory and manages files within it. Provides
    methods to create temporary files and clean them up when done.

    Attributes:
        temp_dir: Path to the temporary directory.
    """

    def __init__(self, prefix: str = "ansible_") -> None:
        """Initialize the temporary file manager.

        Args:
            prefix: Prefix for the temporary directory name. Defaults to
                "ansible_".

        Raises:
            OSError: If temporary directory cannot be created.
        """
        self.temp_dir: str = tempfile.mkdtemp(prefix=prefix)

    def write_to_file(self, content: str, suffix: str = ".tmp") -> str:
        """Write content to a temporary file.

        Creates a temporary file within the managed temporary directory
        and writes the provided content to it.

        Args:
            content: Content to write to the file.
            suffix: File suffix/extension. Defaults to ".tmp".

        Returns:
            Path to the created temporary file.

        Raises:
            OSError: If the file cannot be created or written.
        """
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            dir=self.temp_dir,
        ) as temp_file:
            temp_file.write(content.encode("utf-8"))
            return temp_file.name

    def cleanup(self) -> None:
        """Clean up temporary directory and all its contents.

        Removes the temporary directory and all files within it.
        This method is idempotent and safe to call multiple times.
        Errors during cleanup are silently ignored.
        """
        try:
            shutil.rmtree(self.temp_dir)
        except OSError:
            # Directory may have been already removed
            pass
