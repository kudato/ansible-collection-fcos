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
  disk:
    description:
      - Target disk device for FCOS installation (e.g., /dev/sda).
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
requirements:
  - butane (local)
  - ignition-validate (local)
  - coreos-installer (remote)
"""

EXAMPLES = r"""
- name: Install Fedora CoreOS with custom configuration
  kudato.fcos.install:
    butane_version: "1.6.0"
    disk: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
      - "{{ playbook_dir }}/templates/network.bu"

- name: Force reinstall Fedora CoreOS
  kudato.fcos.install:
    butane_version: "1.6.0"
    disk: "/dev/sda"
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

import base64
import os
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any

import yaml
from jinja2 import Environment

from ansible.errors import AnsibleActionFail, AnsibleError, AnsibleOptionsError
from ansible.plugins.action import ActionBase
from ansible.utils.display import Display
from ansible_collections.kudato.fcos.plugins.module_utils.temp_file_manager import (  # type: ignore[import-not-found]
    TempFileManager,
)

display = Display()

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
            "installed_to": "{{ disk }}"
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

    This class manages the rendering of Butane templates into Ignition
    configuration files, including template processing, butane compilation,
    and validation.

    Attributes:
        file_manager: Temporary file manager for intermediate files.
        ignition_files: List of generated ignition file names.
    """

    def __init__(self) -> None:
        """Initialize the Ignition builder with a temporary file manager."""
        self.file_manager = TempFileManager(prefix="fcos_install_")
        self.ignition_files: list[str] = []

    def render(
        self,
        templates: list[str],
        variables: dict[str, Any] | None = None,
    ) -> str:
        """Render Butane templates into a merged Ignition configuration.

        Args:
            templates: List of paths to Butane template files.
            variables: Variables to pass to the templates.

        Returns:
            Path to the final merged Ignition configuration file.

        Raises:
            AnsibleActionFail: If butane compilation or validation fails.
        """
        variables = variables or {}
        display.v(f"Starting butane generation with {len(templates)} template(s)")

        for template in templates:
            full_path = self._render_template(template, variables=variables)
            self.ignition_files.append(os.path.basename(full_path))

        return self._render_template(
            self.file_manager.write_to_file(BUTANE_BASE_TEMPLATE, suffix=".bu"),
            variables={
                "ignition_files": self.ignition_files,
                "metadata_file": METADATA_FILE,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                **variables,
            },
        )

    def _render_template(
        self,
        template_path: str,
        variables: dict[str, Any] | None = None,
    ) -> str:
        """Render a single Butane template and compile to Ignition.

        Args:
            template_path: Path to the Butane template file.
            variables: Variables to pass to the template.

        Returns:
            Path to the generated Ignition configuration file.

        Raises:
            AnsibleActionFail: If butane compilation or validation fails.
        """
        variables = variables or {}
        env = Environment()

        # Add custom filters
        env.filters["b64encode"] = lambda x: base64.b64encode(x.encode()).decode()
        env.filters["yaml"] = lambda x: yaml.safe_load(x) if isinstance(x, str) else x

        # Read and render template
        with open(template_path, "r", encoding="utf-8") as f:
            template = env.from_string(f.read())
        rendered_content = template.render(**variables)

        display.v(f"Writing butane template to: {os.path.basename(template_path)}")
        display.vvv(f"Rendered content:\n{rendered_content}")
        bu_file_path = self.file_manager.write_to_file(rendered_content, suffix=".bu")

        # Compile with butane
        ign_file_path = self.file_manager.write_to_file("", suffix=".ign")
        result = subprocess.run(
            [
                "butane",
                "--strict",
                "--files-dir",
                self.file_manager.temp_dir,
                bu_file_path,
                "-o",
                ign_file_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise AnsibleActionFail(
                f"Butane failed with exit code {result.returncode}:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # Validate ignition file
        display.v(f"Validating ignition file: {os.path.basename(ign_file_path)}")
        validate_result = subprocess.run(
            ["ignition-validate", ign_file_path],
            capture_output=True,
            text=True,
            check=False,
        )

        if validate_result.returncode != 0:
            raise AnsibleActionFail(
                f"Ignition validation failed with exit code {validate_result.returncode}:\n"
                f"stdout: {validate_result.stdout}\n"
                f"stderr: {validate_result.stderr}"
            )

        return ign_file_path

    def cleanup(self) -> None:
        """Clean up all temporary files and directories."""
        self.file_manager.cleanup()


class ActionModule(ActionBase):
    """Action plugin for installing Fedora CoreOS.

    This plugin handles the complete FCOS installation workflow:
    rendering Butane templates, generating Ignition configuration,
    transferring files, and executing the installation command.
    """

    def _is_installed(self) -> bool:
        """Check if FCOS is already installed by checking metadata file.

        Returns:
            True if metadata file exists, False otherwise.
        """
        result = self._low_level_execute_command(
            f"test -f {shlex.quote(METADATA_FILE)}"
        )
        return result.get("rc", 1) == 0

    def _install(self, ignition_file: str, disk: str) -> None:
        """Install Fedora CoreOS on the target disk.

        Args:
            ignition_file: Path to the local Ignition configuration file.
            disk: Target disk device path.

        Raises:
            AnsibleActionFail: If file transfer or installation fails.
        """
        remote_ignition_path = os.path.join(
            "/tmp",
            f"ansible_ignition_{os.getpid()}_{os.path.basename(ignition_file)}",
        )

        # Transfer ignition file to remote host
        self._connection.put_file(ignition_file, remote_ignition_path)

        # Execute installation command
        install_cmd = (
            f"sudo coreos-installer install "
            f"--ignition-file {shlex.quote(remote_ignition_path)} {shlex.quote(disk)}"
        )

        result = self._low_level_execute_command(install_cmd, sudoable=True)

        if result.get("rc", 1) != 0:
            raise AnsibleActionFail(
                f"FCOS installation error: {result.get('stderr', 'Unknown error')}"
            )

    def _get_task_arg(
        self,
        name: str,
        default: Any = None,
    ) -> Any:
        """Get a task argument with validation.

        Args:
            name: Name of the argument to retrieve.
            default: Default value if argument is not provided.

        Returns:
            The argument value or default.

        Raises:
            AnsibleOptionsError: If required argument is missing.
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
            task_vars: Dictionary of task variables.

        Returns:
            Result dictionary with changed status and message.

        Raises:
            AnsibleActionFail: If any step of the installation fails.
        """
        result = super().run(tmp, task_vars) or {}
        result.update({
            "changed": False,
            "msg": "",
        })

        # Get task arguments
        butane_version: str = self._get_task_arg("butane_version")
        disk: str = self._get_task_arg("disk")
        templates: list[str] = self._get_task_arg("templates", [])
        force: bool = self._get_task_arg("force", False)

        # Check if already installed
        if not force and self._is_installed():
            result["msg"] = "FCOS is already installed, skipping (use force=true to reinstall)"
            return result

        # Prepare template variables
        template_vars = (task_vars or {}).copy()
        template_vars["butane_version"] = butane_version
        template_vars["disk"] = disk

        builder: IgnitionBuilder | None = None

        try:
            builder = IgnitionBuilder()

            # Render ignition configuration
            ignition_file = builder.render(templates, variables=template_vars)
            display.v(f"Ignition file generated: {ignition_file}")

            # Install FCOS (skip in check mode)
            if self._play_context.check_mode:
                result["msg"] = f"Would install Fedora CoreOS on {disk}"
            else:
                self._install(ignition_file, disk)
                result["msg"] = f"Fedora CoreOS installed on {disk}"

            result["changed"] = True

        except AnsibleError:
            raise
        except Exception as e:
            raise AnsibleActionFail(f"Error during FCOS installation: {e}") from e

        finally:
            if builder:
                builder.cleanup()

        return result
