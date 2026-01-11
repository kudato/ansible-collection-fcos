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
    """Builder for Ignition configuration files from Butane templates."""

    def __init__(self) -> None:
        self.file_manager = TempFileManager(prefix="fcos_install_")
        self.ignition_files: list[str] = []

    def render(
        self,
        templates: list[str],
        variables: dict[str, Any],
        installed_to: str,
    ) -> str:
        """Render Butane templates into a merged Ignition configuration."""
        display.v(f"Starting butane generation with {len(templates)} template(s)")

        for template in templates:
            ign_path = self._render_template(template, variables)
            self.ignition_files.append(os.path.basename(ign_path))

        return self._render_template(
            self.file_manager.write_to_file(BUTANE_BASE_TEMPLATE, suffix=".bu"),
            variables={
                "ignition_files": self.ignition_files,
                "metadata_file": METADATA_FILE,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "installed_to": installed_to,
                **variables,
            },
        )

    def _render_template(
        self,
        template_path: str,
        variables: dict[str, Any],
    ) -> str:
        """Render a Butane template to Ignition configuration."""
        env = Environment()
        env.filters["b64encode"] = lambda x: base64.b64encode(x.encode()).decode()
        env.filters["yaml"] = lambda x: yaml.safe_load(x) if isinstance(x, str) else x

        with open(template_path, "r", encoding="utf-8") as f:
            template = env.from_string(f.read())
        rendered = template.render(**variables)

        display.v(f"Compiling template: {os.path.basename(template_path)}")
        display.vvv(f"Rendered content:\n{rendered}")

        bu_file = self.file_manager.write_to_file(rendered, suffix=".bu")
        ign_file = self.file_manager.write_to_file("", suffix=".ign")

        result = subprocess.run(
            [
                "butane",
                "--strict",
                "--files-dir",
                self.file_manager.temp_dir,
                bu_file,
                "-o",
                ign_file,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AnsibleActionFail(
                f"Butane compilation failed:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        result = subprocess.run(
            ["ignition-validate", ign_file],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AnsibleActionFail(
                f"Ignition validation failed:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
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
        """Install Fedora CoreOS on the target device."""
        remote_path = f"/tmp/ansible_ignition_{os.getpid()}.ign"
        self._connection.put_file(ignition_file, remote_path)

        result = self._low_level_execute_command(
            f"sudo coreos-installer install "
            f"--ignition-file {shlex.quote(remote_path)} {shlex.quote(target_device)}",
            sudoable=True,
        )

        if result.get("rc", 1) != 0:
            raise AnsibleActionFail(
                f"FCOS installation failed: {result.get('stderr', 'Unknown error')}"
            )

    def _get_task_arg(self, name: str, default: Any = None) -> Any:
        """Get a task argument with validation."""
        value = self._task.args.get(name)
        if value is None and default is None:
            raise AnsibleOptionsError(f"Required parameter '{name}' is missing")
        return value if value is not None else default

    def run(
        self,
        tmp: str | None = None,
        task_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the FCOS installation action."""
        result = super().run(tmp, task_vars) or {}
        result.update({"changed": False, "msg": ""})

        butane_version: str = self._get_task_arg("butane_version")
        target_device: str = self._get_task_arg("target_device")
        templates: list[str] = self._get_task_arg("templates", [])
        force: bool = self._get_task_arg("force", False)

        if force is not True and self._is_installed():
            result["msg"] = "FCOS is already installed (use force=true to reinstall)"
            return result

        template_vars = (task_vars or {}).copy()
        template_vars["butane_version"] = butane_version

        builder: IgnitionBuilder | None = None

        try:
            builder = IgnitionBuilder()

            ignition_file = builder.render(
                templates,
                variables=template_vars,
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
        finally:
            if builder:
                builder.cleanup()

        return result
