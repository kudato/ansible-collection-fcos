#!/usr/bin/env python3
"""FCOS VM management for testing.

Usage:
    ./vm.py status                       Show status of all VMs
    ./vm.py start [--disk|--live] [vm]   Start VM(s)
    ./vm.py stop [vm]                    Stop VM(s)
    ./vm.py restart [vm]                 Restart VM(s) from disk
    ./vm.py wait [vm]                    Wait for SSH to become available
    ./vm.py ssh <vm>                     Open interactive SSH session
    ./vm.py console <vm>                 Open interactive console (serial)
    ./vm.py log <vm>                     Follow console log (tail -f)
    ./vm.py create [vm]                  Create fresh disk images
    ./vm.py delete [vm]                  Delete disk images

Options:
    --disk    Boot from installed disk
    --live    Boot from live ISO (default)

VM can be: min, full, or all (default: all)
"""

from __future__ import annotations

import abc
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal


# =============================================================================
# Types
# =============================================================================


class BootMode(Enum):
    """VM boot mode."""

    LIVE = "live"  # Boot from live ISO
    DISK = "disk"  # Boot from installed disk


Status = Literal["running", "stopped", "not_created"]


# =============================================================================
# Configuration
# =============================================================================

# Paths
TESTENV = Path(".testenv")
KEYS_DIR = TESTENV / "keys"
DISKS_DIR = TESTENV / "disks"
LOGS_DIR = TESTENV / "logs"
SSH_KEY = KEYS_DIR / "test_key"
LIVE_ISO = TESTENV / "live.iso"

# SSH settings
SSH_USER = "core"
SSH_HOST = "localhost"
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=2",
    "-o", "LogLevel=ERROR",
]


@dataclass(frozen=True)
class VMConfig:
    """VM configuration."""

    name: str
    port: int
    mac: str
    has_data_disk: bool = False
    second_nic_mac: str | None = None
    ssh_port: int = 22  # SSH port inside VM (for port forwarding)
    # Resources
    memory: int = 2048  # MB
    cpus: int = 2
    system_disk_size: str = "20G"
    data_disk_size: str = "5G"


# VM definitions
VM_CONFIGS: dict[str, VMConfig] = {
    "min": VMConfig(
        name="min",
        port=3021,
        mac="EA:C5:B8:F5:4E:DF",
    ),
    "full": VMConfig(
        name="full",
        port=3022,
        mac="DE:0C:DF:04:6D:30",
        has_data_disk=True,
        second_nic_mac="DE:0C:DF:04:6D:31",
        ssh_port=2222,  # Non-standard SSH port for testing
    ),
}


# =============================================================================
# Platform Detection
# =============================================================================


@dataclass
class Platform:
    """Platform-specific configuration for QEMU."""

    _system: str = platform.system()
    _machine: str = platform.machine()

    @property
    def arch(self) -> str:
        """CPU architecture for QEMU."""
        machine = self._machine.lower()
        if machine in ("arm64", "aarch64"):
            return "aarch64"
        if machine in ("x86_64", "amd64"):
            return "x86_64"
        raise RuntimeError(f"Unsupported architecture: {self._machine}")

    @property
    def qemu_accel(self) -> str:
        """QEMU accelerator: hvf (macOS) or kvm (Linux)."""
        return "hvf" if self._system == "Darwin" else "kvm"

    @property
    def qemu_binary(self) -> Path:
        """Path to qemu-system-* binary."""
        binary = shutil.which(f"qemu-system-{self.arch}")
        if not binary:
            raise FileNotFoundError(f"qemu-system-{self.arch} not found in PATH")
        return Path(binary)

    @property
    def firmware_path(self) -> Path:
        """Path to UEFI firmware for QEMU."""
        candidates: list[Path] = []

        # macOS (Homebrew)
        if self._system == "Darwin":
            qemu_dir = self.qemu_binary.parent.parent
            candidates.append(qemu_dir / f"share/qemu/edk2-{self.arch}-code.fd")

        # Linux paths
        candidates.extend([
            Path(f"/usr/share/qemu/edk2-{self.arch}-code.fd"),
            Path(f"/usr/share/AAVMF/AAVMF_CODE.fd"),
            Path(f"/usr/share/edk2/aarch64/QEMU_EFI.fd"),
            Path(f"/usr/share/OVMF/OVMF_CODE.fd"),  # x86_64
            Path(f"/usr/share/edk2/x64/OVMF_CODE.fd"),
        ])

        for path in candidates:
            if path.exists():
                return path

        raise FileNotFoundError(
            f"UEFI firmware not found. Tried: {[str(p) for p in candidates]}"
        )

    def check_dependencies(self) -> None:
        """Check that required tools are available."""
        missing = []
        for cmd in [f"qemu-system-{self.arch}", "qemu-img"]:
            if not shutil.which(cmd):
                missing.append(cmd)
        if missing:
            raise RuntimeError(f"Missing dependencies: {', '.join(missing)}")


# =============================================================================
# Console Output
# =============================================================================


def supports_color() -> bool:
    """Check if terminal supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


class Console:
    """Console output with optional color support."""

    COLORS = {
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "gray": "\033[90m",
        "reset": "\033[0m",
    }

    def __init__(self, use_color: bool | None = None) -> None:
        self._use_color = use_color if use_color is not None else supports_color()

    def _colorize(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self._use_color:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def info(self, message: str) -> None:
        """Print info message."""
        print(f"  {message}")

    def success(self, message: str) -> None:
        """Print success message with checkmark."""
        print(f"  {self._colorize('✓', 'green')} {message}")

    def warning(self, message: str) -> None:
        """Print warning message."""
        print(f"  {self._colorize('!', 'yellow')} {message}")

    def error(self, message: str) -> None:
        """Print error message."""
        print(f"{self._colorize('Error:', 'red')} {message}")

    def status(self, icon: str, name: str, state: str, info: str = "", color: str = "") -> None:
        """Print status line."""
        colored_part = self._colorize(f"{icon} {name}: {state}", color)
        print(f"  {colored_part}{info}")

    def progress_start(self, message: str) -> None:
        """Start progress message (no newline)."""
        print(f"  → {message}", end="", flush=True)

    def progress_dot(self) -> None:
        """Print progress dot."""
        print(".", end="", flush=True)

    def progress_end(self, message: str) -> None:
        """End progress with message."""
        print(f" {message}")

    def header(self, message: str) -> None:
        """Print header."""
        print(message)

    def separator(self, char: str = "-", length: int = 60) -> None:
        """Print separator line."""
        print(char * length)


# =============================================================================
# Process Runner
# =============================================================================


class ProcessRunner:
    """Abstraction over subprocess operations."""

    def run(
        self,
        cmd: list[str],
        capture: bool = True,
        text: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run command and return result."""
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=text,
            check=check,
        )

    def run_interactive(self, cmd: list[str]) -> None:
        """Run command interactively (no capture)."""
        subprocess.run(cmd)

    def is_running(self, pid: int) -> bool:
        """Check if process with given PID is running."""
        try:
            subprocess.run(
                ["kill", "-0", str(pid)],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def kill(self, pid: int) -> bool:
        """Send SIGTERM to process. Returns True if signal was sent."""
        try:
            subprocess.run(["kill", str(pid)], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def kill_force(self, pid: int) -> None:
        """Send SIGKILL to process."""
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)


# =============================================================================
# SSH Client
# =============================================================================


class SSHClient:
    """SSH client for VM communication."""

    def __init__(
        self,
        port: int,
        key: Path = SSH_KEY,
        user: str = SSH_USER,
        host: str = SSH_HOST,
        opts: list[str] | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._port = port
        self._key = key
        self._user = user
        self._host = host
        self._opts = opts or SSH_OPTS
        self._runner = runner or ProcessRunner()

    def _base_command(self) -> list[str]:
        """Build base SSH command."""
        return [
            "ssh",
            "-i", str(self._key),
            "-p", str(self._port),
            *self._opts,
            f"{self._user}@{self._host}",
        ]

    def check(self) -> bool:
        """Check if SSH is available."""
        result = self._runner.run(self._base_command() + ["exit"])
        return result.returncode == 0

    def run(self, command: str) -> subprocess.CompletedProcess:
        """Run command via SSH and return result."""
        return self._runner.run(self._base_command() + [command])

    def connect(self) -> None:
        """Open interactive SSH session."""
        self._runner.run_interactive(self._base_command())

    def wait(self, timeout: int, console: Console) -> None:
        """Wait for SSH to become available."""
        console.progress_start("Waiting for SSH...")

        start = time.time()
        while time.time() - start < timeout:
            if self.check():
                elapsed = int(time.time() - start)
                console.progress_end(f"ready ({elapsed}s)")
                return
            time.sleep(2)
            console.progress_dot()

        console.progress_end("timeout!")
        raise TimeoutError(f"SSH timeout after {timeout}s")


# =============================================================================
# Disk Manager
# =============================================================================


class DiskManager:
    """Manages VM disk images."""

    def __init__(
        self,
        name: str,
        system_size: str,
        data_size: str,
        has_data_disk: bool = False,
        disks_dir: Path = DISKS_DIR,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._name = name
        self._system_size = system_size
        self._data_size = data_size
        self._has_data_disk = has_data_disk
        self._disks_dir = disks_dir
        self._runner = runner or ProcessRunner()

    @property
    def system_disk(self) -> Path:
        """Path to system disk."""
        return self._disks_dir / f"{self._name}-system.qcow2"

    @property
    def data_disk(self) -> Path | None:
        """Path to data disk, or None if not configured."""
        if self._has_data_disk:
            return self._disks_dir / f"{self._name}-data.qcow2"
        return None

    @property
    def exists(self) -> bool:
        """Check if system disk exists."""
        return self.system_disk.exists()

    def create(self, console: Console) -> None:
        """Create fresh disk images."""
        self._disks_dir.mkdir(parents=True, exist_ok=True)

        # Remove old disks if exist
        self.delete()

        # Create system disk
        self._runner.run(
            ["qemu-img", "create", "-f", "qcow2", str(self.system_disk), self._system_size],
            check=True,
        )
        console.success(f"Created {self._name} system disk ({self._system_size})")

        # Create data disk if needed
        if self.data_disk:
            self._runner.run(
                ["qemu-img", "create", "-f", "qcow2", str(self.data_disk), self._data_size],
                check=True,
            )
            console.success(f"Created {self._name} data disk ({self._data_size})")

    def delete(self) -> None:
        """Delete disk images."""
        self.system_disk.unlink(missing_ok=True)
        if self.data_disk:
            self.data_disk.unlink(missing_ok=True)


# =============================================================================
# Virtual Machine
# =============================================================================


class VM:
    """QEMU virtual machine manager."""

    def __init__(
        self,
        config: VMConfig,
        platform: Platform,
        console: Console | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._config = config
        self._platform = platform
        self._console = console or Console()
        self._runner = runner or ProcessRunner()
        self._disks = DiskManager(
            name=config.name,
            system_size=config.system_disk_size,
            data_size=config.data_disk_size,
            has_data_disk=config.has_data_disk,
            runner=self._runner,
        )
        self._ssh = SSHClient(port=config.port, runner=self._runner)

    # -------------------------------------------------------------------------
    # Properties: Configuration
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def port(self) -> int:
        return self._config.port

    # -------------------------------------------------------------------------
    # Properties: Paths
    # -------------------------------------------------------------------------

    @property
    def pid_file(self) -> Path:
        return DISKS_DIR / f"{self.name}.pid"

    @property
    def state_file(self) -> Path:
        """State file storing boot mode."""
        return DISKS_DIR / f"{self.name}.state"

    @property
    def console_socket(self) -> Path:
        """Unix socket for interactive console."""
        return DISKS_DIR / f"{self.name}.sock"

    @property
    def log_file(self) -> Path:
        """Console log file path."""
        return LOGS_DIR / f"{self.name}.log"

    # -------------------------------------------------------------------------
    # Properties: State
    # -------------------------------------------------------------------------

    @property
    def pid(self) -> int | None:
        """Get PID from pidfile, or None if not available."""
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            return None

    @property
    def is_running(self) -> bool:
        """Check if QEMU process is running."""
        pid = self.pid
        if pid is None:
            return False
        return self._runner.is_running(pid)

    @property
    def disk_exists(self) -> bool:
        """Check if system disk exists."""
        return self._disks.exists

    @property
    def status(self) -> Status:
        """Get VM status: running, stopped, or not_created."""
        if self.is_running:
            return "running"
        if self.disk_exists:
            return "stopped"
        return "not_created"

    @property
    def boot_mode(self) -> BootMode | None:
        """Get current boot mode from state file, or None if not running."""
        if not self.state_file.exists():
            return None
        try:
            mode_str = self.state_file.read_text().strip()
            return BootMode(mode_str)
        except (ValueError, OSError):
            return None

    # -------------------------------------------------------------------------
    # Operations: Disks (delegated to DiskManager)
    # -------------------------------------------------------------------------

    def create_disks(self) -> None:
        """Create fresh disk images."""
        self._cleanup_state_files()
        self._disks.create(self._console)

    def delete_disks(self) -> None:
        """Delete disk images and state files."""
        self._disks.delete()
        self._cleanup_state_files()
        self._cleanup_console_socket()

    def _cleanup_state_files(self) -> None:
        """Remove state and pid files."""
        self.state_file.unlink(missing_ok=True)
        self.pid_file.unlink(missing_ok=True)

    def _cleanup_console_socket(self) -> None:
        """Remove console socket."""
        self.console_socket.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # Operations: Lifecycle
    # -------------------------------------------------------------------------

    def _build_qemu_command(self, mode: BootMode) -> tuple[list[str], int]:
        """Build QEMU command line.

        Returns:
            Tuple of (command list, internal SSH port for port forwarding).
        """
        cmd = [
            # Base
            str(self._platform.qemu_binary),
            "-name", self.name,
            "-machine", f"virt,accel={self._platform.qemu_accel}",
            "-cpu", "host",
            "-m", str(self._config.memory),
            "-smp", str(self._config.cpus),
            # Firmware
            "-drive", f"if=pflash,format=raw,readonly=on,file={self._platform.firmware_path}",
            # System disk
            "-drive", f"file={self._disks.system_disk},if=virtio,format=qcow2",
        ]

        # Boot mode
        if mode == BootMode.DISK:
            cmd.extend(["-boot", "c"])
            internal_ssh_port = self._config.ssh_port
        else:
            cmd.extend([
                "-cdrom", str(LIVE_ISO),
                "-boot", "d",
            ])
            internal_ssh_port = 22

        # Network (primary NIC with SSH port forwarding)
        cmd.extend([
            "-netdev", f"user,id=net0,hostfwd=tcp::{self.port}-:{internal_ssh_port}",
            "-device", f"virtio-net-pci,netdev=net0,mac={self._config.mac}",
        ])

        # Display and serial
        cmd.extend([
            "-display", "none",
            "-serial", f"file:{self.log_file}",
            "-serial", f"unix:{self.console_socket},server,nowait",
        ])

        # Daemonize and pidfile
        cmd.extend([
            "-daemonize",
            "-pidfile", str(self.pid_file),
        ])

        # Data disk (if exists)
        data_disk = self._disks.data_disk
        if data_disk and data_disk.exists():
            cmd.extend(["-drive", f"file={data_disk},if=virtio,format=qcow2"])

        # Second NIC (if configured)
        if self._config.second_nic_mac:
            cmd.extend([
                "-netdev", "user,id=net1",
                "-device", f"virtio-net-pci,netdev=net1,mac={self._config.second_nic_mac}",
            ])

        return cmd, internal_ssh_port

    def start(self, mode: BootMode = BootMode.LIVE) -> None:
        """Start VM with QEMU.

        Args:
            mode: Boot mode - LIVE (from ISO) or DISK (from installed system).
        """
        if self.is_running:
            current_mode = self.boot_mode
            mode_info = f", {current_mode.value}" if current_mode else ""
            self._console.info(f"• {self.name}: already running (port {self.port}{mode_info})")
            return

        if not self.disk_exists:
            raise RuntimeError(f"{self.name}: disk not found. Run 'create' first.")

        if mode == BootMode.LIVE and not LIVE_ISO.exists():
            raise RuntimeError(f"Live ISO not found: {LIVE_ISO}. Run 'make setup' first.")

        # Ensure directories exist
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        DISKS_DIR.mkdir(parents=True, exist_ok=True)

        # Build and run QEMU command
        cmd, _ = self._build_qemu_command(mode)
        result = self._runner.run(cmd)

        if result.returncode != 0:
            self.pid_file.unlink(missing_ok=True)
            stderr = result.stderr.strip() if result.stderr else ""
            if "Could not set up host forwarding rule" in stderr:
                raise RuntimeError(
                    f"{self.name}: port {self.port} already in use. "
                    f"Run './vm.py stop' or check for stale QEMU processes."
                )
            raise RuntimeError(f"{self.name}: QEMU failed to start: {stderr}")

        # Save boot mode
        self.state_file.write_text(mode.value)
        self._console.success(f"Started {self.name} (port {self.port}, {mode.value})")

    def stop(self) -> None:
        """Stop VM by killing QEMU process."""
        pid = self.pid
        if pid is None:
            return

        if not self.is_running:
            self._cleanup_state_files()
            self._cleanup_console_socket()
            return

        # Send SIGTERM
        self._runner.kill(pid)

        # Wait for graceful shutdown
        for _ in range(20):
            if not self.is_running:
                break
            time.sleep(0.5)
        else:
            # Force kill if still running
            self._runner.kill_force(pid)
            time.sleep(0.5)

        self._cleanup_state_files()
        self._cleanup_console_socket()
        self._console.success(f"Stopped {self.name}")

    def restart(self) -> None:
        """Restart VM, booting from disk."""
        if self.is_running:
            self.stop()
        self.start(mode=BootMode.DISK)

    # -------------------------------------------------------------------------
    # Operations: SSH (delegated to SSHClient)
    # -------------------------------------------------------------------------

    def wait_ssh(self, timeout: int = 120) -> None:
        """Wait for SSH to become available."""
        self._ssh.wait(timeout, self._console)

    def ssh(self) -> None:
        """Open interactive SSH session."""
        if not self.is_running:
            raise RuntimeError(f"{self.name}: not running")
        self._ssh.connect()

    def ssh_run(self, command: str) -> subprocess.CompletedProcess:
        """Run command via SSH and return result."""
        return self._ssh.run(command)

    # -------------------------------------------------------------------------
    # Operations: Console
    # -------------------------------------------------------------------------

    def console(self) -> None:
        """Open interactive console session via serial."""
        if not self.is_running:
            raise RuntimeError(f"{self.name}: not running")

        if not shutil.which("socat"):
            raise RuntimeError("socat not found. Install with: brew install socat")

        if not self.console_socket.exists():
            raise RuntimeError(f"{self.name}: console socket not found")

        self._console.header(f"Connecting to {self.name} console (Ctrl+O to exit)")
        self._console.separator()

        try:
            self._runner.run_interactive([
                "socat",
                "-,raw,echo=0,escape=0x0f",
                f"unix-connect:{self.console_socket}",
            ])
        except KeyboardInterrupt:
            print()

    def log(self) -> None:
        """Follow console log with tail -f."""
        if not self.log_file.exists():
            raise RuntimeError(
                f"{self.name}: no log file. VM was never started or log was deleted."
            )

        self._console.header(f"Following {self.log_file} (Ctrl+C to exit)")
        self._console.separator()

        try:
            self._runner.run_interactive(["tail", "-f", str(self.log_file)])
        except KeyboardInterrupt:
            print()


# =============================================================================
# Commands
# =============================================================================


class Command(abc.ABC):
    """Base class for CLI commands."""

    name: str
    help: str
    single_vm: bool = False  # If True, command requires specific VM

    @abc.abstractmethod
    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        """Execute command for a single VM."""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add command-specific arguments."""


class StartCommand(Command):
    name = "start"
    help = "Start VM(s)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--disk", action="store_true", help="Boot from installed disk")
        group.add_argument("--live", action="store_true", help="Boot from live ISO (default)")

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        mode = BootMode.DISK if args.disk else BootMode.LIVE
        vm.start(mode=mode)


class StopCommand(Command):
    name = "stop"
    help = "Stop VM(s)"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.stop()


class RestartCommand(Command):
    name = "restart"
    help = "Restart VM(s) from disk"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.restart()


class WaitCommand(Command):
    name = "wait"
    help = "Wait for SSH to become available"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.wait_ssh()


class CreateCommand(Command):
    name = "create"
    help = "Create fresh disk images"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.create_disks()


class DeleteCommand(Command):
    name = "delete"
    help = "Delete disk images"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.delete_disks()
        vm._console.success(f"Deleted {vm.name} disks")


class SSHCommand(Command):
    name = "ssh"
    help = "Open interactive SSH session"
    single_vm = True

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.ssh()


class ConsoleCommand(Command):
    name = "console"
    help = "Open interactive console (serial)"
    single_vm = True

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.console()


class LogCommand(Command):
    name = "log"
    help = "Follow console log"
    single_vm = True

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        vm.log()


class StatusCommand(Command):
    name = "status"
    help = "Show status of all VMs"

    def execute(self, vm: VM, args: argparse.Namespace) -> None:
        # Status is handled specially in dispatcher
        pass


# =============================================================================
# Command Dispatcher
# =============================================================================


class CommandDispatcher:
    """Dispatches CLI commands to handlers."""

    STATUS_ICONS = {"running": "●", "stopped": "○", "not_created": "−"}
    STATUS_COLORS = {"running": "green", "stopped": "yellow", "not_created": "gray"}

    def __init__(self, platform: Platform, console: Console) -> None:
        self._platform = platform
        self._console = console
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        """Register a command."""
        self._commands[command.name] = command

    def get_commands(self) -> dict[str, Command]:
        """Get all registered commands."""
        return self._commands

    def _resolve_vms(self, target: str) -> list[VM]:
        """Resolve target to list of VMs."""
        if target == "all":
            return [
                VM(cfg, self._platform, self._console)
                for cfg in VM_CONFIGS.values()
            ]
        if target not in VM_CONFIGS:
            raise ValueError(
                f"Unknown VM '{target}'. Available: {', '.join(VM_CONFIGS.keys())}, all"
            )
        return [VM(VM_CONFIGS[target], self._platform, self._console)]

    def _print_status(self) -> None:
        """Print status table for all VMs."""
        self._console.header("VM Status:")
        for cfg in VM_CONFIGS.values():
            vm = VM(cfg, self._platform, self._console)
            vm_status = vm.status
            icon = self.STATUS_ICONS[vm_status]
            color = self.STATUS_COLORS[vm_status]

            info_parts = []
            if vm_status == "running":
                info_parts.append(f"port {vm.port}")
                boot_mode = vm.boot_mode
                if boot_mode:
                    info_parts.append(boot_mode.value)

            info = f" ({', '.join(info_parts)})" if info_parts else ""
            self._console.status(icon, vm.name, vm_status, info, color)

    def dispatch(self, command_name: str, target: str, args: argparse.Namespace) -> None:
        """Dispatch command to appropriate handler."""
        if command_name == "status":
            self._print_status()
            return

        command = self._commands.get(command_name)
        if not command:
            raise ValueError(f"Unknown command: {command_name}")

        if command.single_vm and target == "all":
            raise ValueError(f"Specify VM for {command_name} (min or full)")

        vms = self._resolve_vms(target)
        for vm in vms:
            command.execute(vm, args)


# =============================================================================
# CLI
# =============================================================================


def create_parser(commands: dict[str, Command]) -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="FCOS VM management for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="VM can be: min, full, or all (default: all)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    for cmd in commands.values():
        if cmd.single_vm:
            sub = subparsers.add_parser(cmd.name, help=cmd.help)
            sub.add_argument("vm", help="VM name (required)")
        else:
            sub = subparsers.add_parser(cmd.name, help=cmd.help)
            if cmd.name != "status":
                sub.add_argument("vm", nargs="?", default="all", help="VM name or 'all'")
        cmd.add_arguments(sub)

    return parser


def get_platform() -> Platform:
    """Get and validate platform."""
    p = Platform()
    p.check_dependencies()
    return p


def main() -> None:
    console = Console()

    # Register commands
    dispatcher_commands = [
        StatusCommand(),
        StartCommand(),
        StopCommand(),
        RestartCommand(),
        WaitCommand(),
        SSHCommand(),
        ConsoleCommand(),
        LogCommand(),
        CreateCommand(),
        DeleteCommand(),
    ]

    # Create parser
    commands = {cmd.name: cmd for cmd in dispatcher_commands}
    parser = create_parser(commands)
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        plat = get_platform()
        dispatcher = CommandDispatcher(plat, console)
        for cmd in dispatcher_commands:
            dispatcher.register(cmd)

        target = getattr(args, "vm", "all")
        dispatcher.dispatch(args.command, target, args)

    except (RuntimeError, TimeoutError, FileNotFoundError, ValueError) as e:
        console.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
