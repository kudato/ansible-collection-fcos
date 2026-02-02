# kudato.fcos.install

Action plugin for installing Fedora CoreOS with Ignition configuration.

## Description

This plugin renders Butane templates into Ignition configuration files, validates them, and installs Fedora CoreOS on the target disk.

**Workflow:**

1. Renders Butane templates with Ansible variables (Jinja2)
2. Compiles Butane → Ignition locally via `butane --strict`
3. Validates Ignition files via `ignition-validate`
4. Merges all Ignition files into one
5. Transfers the final Ignition to the target host
6. Executes `coreos-installer install` on the target host
7. Creates `/etc/metadata.json` with installation info

On subsequent runs (without `force: true`), installation is skipped if `/etc/metadata.json` exists.

## Requirements

**Locally (where Ansible runs):**
- `butane` — for compiling Butane to Ignition
- `ignition-validate` — for validating Ignition configuration

**On target host:**
- `coreos-installer` — for installing FCOS to disk
- Booted from Fedora CoreOS Live ISO

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `butane_version` | str | yes | — | Version of the Butane specification to use |
| `target_device` | str | yes | — | Target block device for FCOS installation (e.g., `/dev/sda`, `/dev/nvme0n1`) |
| `templates` | list | no | `[]` | List of paths to Butane template files to render and merge |
| `force` | bool | no | `false` | Force reinstallation even if FCOS is already installed |

## Examples

### Basic installation

```yaml
- name: Install Fedora CoreOS with custom configuration
  kudato.fcos.install:
    butane_version: "1.6.0"
    target_device: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
      - "{{ playbook_dir }}/templates/network.bu"
```

### Force reinstallation

```yaml
- name: Force reinstall Fedora CoreOS
  kudato.fcos.install:
    butane_version: "1.6.0"
    target_device: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
    force: true
```

### With role templates

When using with the `install` role, templates are automatically provided:

```yaml
- name: Install Fedora CoreOS
  hosts: all
  gather_facts: false
  roles:
    - kudato.fcos.install
```

## Return Values

| Key | Type | Description |
|-----|------|-------------|
| `changed` | bool | Whether the installation was performed |
| `msg` | str | Status message describing the result |

## Notes

- This plugin runs locally and transfers the ignition file to the remote host
- The plugin requires sudo privileges on the remote host for installation
- Supports check mode (`--check`) to validate configuration without installing
- Butane templates support Jinja2 templating with all Ansible variables
- Custom filter `b64encode` is available for base64 encoding in templates

## See Also

- [install role](../../roles/install/README.md) — Complete role for FCOS installation with predefined templates
