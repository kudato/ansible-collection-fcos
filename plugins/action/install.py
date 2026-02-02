#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Aleksander Shevchenko <kudato@me.com>
# SPDX-License-Identifier: MIT

"""Action plugin for installing Fedora CoreOS with Ignition configuration.

This action plugin renders Butane templates into Ignition configuration,
validates them, and installs Fedora CoreOS on the target disk.
"""

from __future__ import annotations

DOCUMENTATION = r"""
---
action: install
short_description: Install Fedora CoreOS with Ignition configuration
description:
  - Renders Butane templates into Ignition configuration files.
  - Validates generated Ignition files using ignition-validate.
  - Installs Fedora CoreOS on the specified disk using coreos-installer.
  - Requires butane and ignition-validate to be installed locally.
  - Requires coreos-installer to be available on the target host.
version_added: "0.1.0"
author:
  - Aleksander Shevchenko (@kudato)
options:
  butane_version:
    description:
      - Version of the Butane specification to use.
    type: str
    required: true
  target_device:
    description:
      - Target block device for FCOS installation (e.g., /dev/sda, /dev/nvme0n1).
    type: str
    required: true
  templates:
    description:
      - List of paths to Butane template files to render and merge.
    type: list
    elements: str
    default: []
  force:
    description:
      - Force reinstallation even if FCOS is already installed.
    type: bool
    default: false
notes:
  - This plugin runs locally and transfers the ignition file to the remote host.
  - The plugin requires sudo privileges on the remote host for installation.
  - Supports check mode (--check) to validate configuration without installing.
  - Template files are validated for existence before processing begins.
requirements:
  - butane (local)
  - ignition-validate (local)
  - coreos-installer (remote)
"""

EXAMPLES = r"""
- name: Install Fedora CoreOS with custom configuration
  kudato.fcos.install:
    butane_version: "1.6.0"
    target_device: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
      - "{{ playbook_dir }}/templates/network.bu"

- name: Force reinstall Fedora CoreOS
  kudato.fcos.install:
    butane_version: "1.6.0"
    target_device: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
    force: true
"""

RETURN = r"""
changed:
  description: Whether the installation was performed.
  type: bool
  returned: always
msg:
  description: Status message describing the result.
  type: str
  returned: always
"""

import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from ansible.errors import AnsibleActionFail, AnsibleError, AnsibleOptionsError
from ansible.template import Templar, trust_as_template
from ansible.plugins.action import ActionBase
from ansible.utils.display import Display
from ansible_collections.kudato.fcos.plugins.module_utils.temp_file_manager import (  # type: ignore[import-not-found]
    TempFileManager,
)

display = Display()

SUBPROCESS_TIMEOUT = 120  # seconds
METADATA_FILE = "/etc/metadata.json"

BUTANE_BASE_TEMPLATE = """variant: fcos
version: "{{ butane_version }}"
storage:
  files:
    - path: "{{ metadata_file }}"
      mode: 0644
      overwrite: true
      contents:
        inline: |
          {
            "installed_at": "{{ installed_at }}",
            "installed_to": "{{ installed_to }}"
          }
ignition:
  config:
    merge:
    {% for ignition_file in ignition_files %}
    - local: "{{ ignition_file }}"
    {% endfor %}
"""


class IgnitionBuilder:
    """Builder for Ignition configuration files from Butane templates.

    This class implements the context manager protocol for automatic cleanup
    of temporary files. Recommended usage:

        with IgnitionBuilder(templar) as builder:
            ignition_file = builder.render(templates, target)

    Attributes:
        REQUIRED_TOOLS: Tuple of required CLI tools (butane, ignition-validate).
        file_manager: TempFileManager instance for temporary file handling.
        ignition_files: List of generated ignition file names.
    """

    REQUIRED_TOOLS = ("butane", "ignition-validate")

    def __init__(self, templar: Templar) -> None:
        self._check_required_tools()
        self._templar = templar
        self.file_manager = TempFileManager(prefix="fcos_install_")
        self.ignition_files: list[str] = []

    def __enter__(self) -> "IgnitionBuilder":
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager and cleanup resources."""
        self.cleanup()

    def _check_required_tools(self) -> None:
        """Verify that required tools are installed."""
        missing = [tool for tool in self.REQUIRED_TOOLS if shutil.which(tool) is None]
        if missing:
            raise AnsibleActionFail(
                f"Required tools not found in PATH: {', '.join(missing)}"
            )

    def _run_command(self, cmd: list[str], error_prefix: str) -> None:
        """Run a command with timeout handling.

        Args:
            cmd: Command and arguments to execute.
            error_prefix: Prefix for error messages (e.g., "Butane compilation").

        Raises:
            AnsibleActionFail: If command times out or returns non-zero exit code.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as e:
            raise AnsibleActionFail(f"{error_prefix} timed out after {e.timeout}s")
        if result.returncode != 0:
            raise AnsibleActionFail(
                f"{error_prefix} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

    def render(
        self,
        templates: list[str],
        installed_to: str,
    ) -> str:
        """Render Butane templates into a merged Ignition configuration.

        Args:
            templates: List of paths to Butane template files.
            installed_to: Target device path for metadata.

        Returns:
            Path to the generated Ignition configuration file.

        Raises:
            AnsibleActionFail: If template files are not found or compilation fails.
        """
        display.v(f"Starting butane generation with {len(templates)} template(s)")

        # Validate all templates exist before processing
        missing = [t for t in templates if not os.path.isfile(t)]
        if missing:
            raise AnsibleActionFail(
                f"Template files not found: {', '.join(missing)}"
            )

        for template in templates:
            ign_path = self._render_template(template)
            self.ignition_files.append(os.path.basename(ign_path))

        # Render base template with metadata
        base_vars = {
            "ignition_files": self.ignition_files,
            "metadata_file": METADATA_FILE,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "installed_to": installed_to,
        }
        return self._render_template(
            self.file_manager.write_to_file(BUTANE_BASE_TEMPLATE, suffix=".bu"),
            extra_vars=base_vars,
        )

    def _render_template(
        self,
        template_path: str,
        extra_vars: dict[str, Any] | None = None,
    ) -> str:
        """Render a Butane template to Ignition configuration.

        Args:
            template_path: Path to the Butane template file.
            extra_vars: Additional variables to merge with templar variables.

        Returns:
            Path to the generated Ignition configuration file.

        Raises:
            AnsibleActionFail: If butane compilation or ignition validation fails.
        """
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        if extra_vars:
            templar = self._templar.copy_with_new_env(
                available_variables={**self._templar.available_variables, **extra_vars}
            )
        else:
            templar = self._templar

        rendered = templar.template(trust_as_template(template_content))

        display.v(f"Compiling template: {os.path.basename(template_path)}")
        display.vvv(f"Rendered content:\n{rendered}")

        bu_file = self.file_manager.write_to_file(rendered, suffix=".bu")
        ign_file = self.file_manager.write_to_file("", suffix=".ign")

        self._run_command(
            [
                "butane",
                "--strict",
                "--files-dir",
                self.file_manager.temp_dir,
                bu_file,
                "-o",
                ign_file,
            ],
            error_prefix="Butane compilation",
        )

        self._run_command(
            ["ignition-validate", ign_file],
            error_prefix="Ignition validation",
        )

        return ign_file

    def cleanup(self) -> None:
        """Clean up temporary files."""
        self.file_manager.cleanup()


class ActionModule(ActionBase):
    """Action plugin for installing Fedora CoreOS."""

    def _is_installed(self) -> bool:
        """Check if FCOS is already installed."""
        result = self._low_level_execute_command(
            f"test -f {shlex.quote(METADATA_FILE)}"
        )
        return result.get("rc", 1) == 0

    def _install(self, ignition_file: str, target_device: str) -> None:
        """Install Fedora CoreOS on the target device.

        Args:
            ignition_file: Path to the local Ignition configuration file.
            target_device: Target block device for installation.

        Raises:
            AnsibleActionFail: If coreos-installer fails.
        """
        remote_path = f"/tmp/ansible_ignition_{os.getpid()}.ign"
        self._connection.put_file(ignition_file, remote_path)

        result = self._low_level_execute_command(
            f"sudo coreos-installer install "
            f"--ignition-file {shlex.quote(remote_path)} {shlex.quote(target_device)}",
            sudoable=True,
        )

        if result.get("rc", 1) != 0:
            raise AnsibleActionFail(
                f"FCOS installation failed (rc={result.get('rc')}):\n"
                f"stdout: {result.get('stdout', '')}\n"
                f"stderr: {result.get('stderr', '')}"
            )

    def _get_task_arg(self, name: str, default: Any = None) -> Any:
        """Get a task argument with validation.

        Args:
            name: Name of the task argument.
            default: Default value if argument is not provided.

        Returns:
            The argument value or default.

        Raises:
            AnsibleOptionsError: If required argument is missing (no default).
        """
        value = self._task.args.get(name)
        if value is None and default is None:
            raise AnsibleOptionsError(f"Required parameter '{name}' is missing")
        return value if value is not None else default

    def run(
        self,
        tmp: str | None = None,
        task_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the FCOS installation action.

        Args:
            tmp: Temporary directory path (deprecated, unused).
            task_vars: Dictionary of task variables from Ansible.

        Returns:
            Result dictionary with 'changed' and 'msg' keys.

        Raises:
            AnsibleActionFail: If installation fails.
            AnsibleOptionsError: If required parameters are missing.
        """
        result = super().run(tmp, task_vars) or {}
        result.update({"changed": False, "msg": ""})

        butane_version: str = self._get_task_arg("butane_version")
        target_device: str = self._get_task_arg("target_device")
        templates: list[str] = self._get_task_arg("templates", [])
        force: bool = self._get_task_arg("force", False)

        if not force and self._is_installed():
            result["msg"] = "FCOS is already installed (use force=true to reinstall)"
            return result

        # Set task variables in templar's available variables
        if task_vars:
            self._templar.available_variables = task_vars.copy()
        self._templar.available_variables["butane_version"] = butane_version

        try:
            with IgnitionBuilder(self._templar) as builder:
                ignition_file = builder.render(
                    templates,
                    installed_to=target_device,
                )
                display.v(f"Ignition file generated: {ignition_file}")

                if self._play_context.check_mode:
                    result["msg"] = f"Would install Fedora CoreOS on {target_device}"
                else:
                    self._install(ignition_file, target_device)
                    result["msg"] = f"Fedora CoreOS installed on {target_device}"

                result["changed"] = True

        except AnsibleError:
            raise
        except Exception as e:
            raise AnsibleActionFail(f"FCOS installation error: {e}") from e

        return result
