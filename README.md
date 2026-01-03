# Ansible Collection - kudato.fcos

Ansible collection for bootstrapping and managing Fedora CoreOS systems.

## Plugins

### install

Action plugin for installing Fedora CoreOS with Ignition configuration.

**Requirements:**
- `butane`, `ignition-validate` (local)
- `coreos-installer` (remote)

## Installation

```bash
ansible-galaxy collection install kudato.fcos
```

## Usage

```yaml
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
```

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `butane_version` | yes | - | Version of the Butane specification |
| `disk` | yes | - | Target disk device (e.g., `/dev/sda`) |
| `templates` | no | `[]` | List of Butane template files |
| `force` | no | `false` | Force reinstallation |

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
