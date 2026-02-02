# Ansible Collection - kudato.fcos

Ansible collection for bootstrapping and managing Fedora CoreOS systems.

## Installation

```bash
ansible-galaxy collection install kudato.fcos
```

## Documentation

### Plugins

| Plugin | Description |
|--------|-------------|
| [install](docs/plugins/install.md) | Install Fedora CoreOS with Ignition configuration |

### Roles

| Role | Description |
|------|-------------|
| [install](roles/install/README.md) | Complete FCOS installation with predefined Butane templates |

## Quick Start

### Using the install role (recommended)

The `install` role provides a complete solution with predefined templates for system configuration:

```yaml
# playbook.yml
- name: Install Fedora CoreOS
  hosts: all
  gather_facts: false
  roles:
    - kudato.fcos.install
```

```yaml
# host_vars/server1.yml
system_disk: /dev/sda
wipe_system_disk: true

core_user_ssh_keys:
  - "ssh-ed25519 AAAA... admin@example.com"

ansible_user_ssh_keys:
  - "ssh-ed25519 AAAA... ansible@example.com"

network_interfaces:
  - name: eth0
    type: wan
    dhcp: true
```

```bash
ansible-playbook -i inventory.yml playbook.yml
```

See [install role documentation](roles/install/README.md) for all available variables.

### Using plugins directly

For custom installations without the role:

```yaml
- name: Install Fedora CoreOS with custom templates
  kudato.fcos.install:
    butane_version: "1.6.0"
    target_device: "/dev/sda"
    templates:
      - "{{ playbook_dir }}/templates/base.bu"
      - "{{ playbook_dir }}/templates/network.bu"
```

## Requirements

**Locally (where Ansible runs):**
- `butane` — for compiling Butane to Ignition
- `ignition-validate` — for validating Ignition configuration

**On target host:**
- `coreos-installer` — for installing FCOS to disk
- Booted from Fedora CoreOS Live ISO

## Contributing

### For contributors

1. [Fork](https://github.com/kudato/ansible-collection-fcos/fork) this repository
2. Clone your fork and create a branch:

   ```bash
   git clone https://github.com/YOUR_USERNAME/ansible-collection-fcos.git
   cd ansible-collection-fcos
   git checkout -b feature/your-feature
   ```

3. Make changes and commit using [Conventional Commits](https://www.conventionalcommits.org/):

   ```
   feat: add new feature
   fix: fix bug in install module
   docs: update README
   ```

4. Push to your fork and open a Pull Request:

   ```bash
   git push origin feature/your-feature
   gh pr create  # or use GitHub UI
   ```

### For maintainers

```bash
# Feature development
git checkout -b feature/something
# ... make changes ...
git commit -m "feat: add something"
git push origin feature/something
gh pr create

# Release
git checkout main
sed -i 's/version: .*/version: X.Y.Z/' galaxy.yml
git add galaxy.yml
git commit -m "chore: release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

CI will automatically create GitHub Release and publish to Ansible Galaxy.

## License

[MIT](LICENSE)

## Author

Aleksander Shevchenko ([@kudato](https://github.com/kudato))
