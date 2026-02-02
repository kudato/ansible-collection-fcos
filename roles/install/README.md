# Install Role

Installs Fedora CoreOS on the specified disk with predefined Ignition configuration.

## How It Works

The role uses the `kudato.fcos.install` action plugin which performs the following steps:

1. **Configuration validation** — checks all required parameters
2. **Template rendering** — processes Butane templates with Ansible variables
3. **Butane → Ignition compilation** — locally via `butane --strict`
4. **Ignition validation** — locally via `ignition-validate`
5. **Configuration merging** — merges all Ignition files into one
6. **Transfer to host** — copies the final Ignition to the target host
7. **Installation** — executes `coreos-installer install` on the target host

After installation, a `/etc/metadata.json` file is created with installation info. On subsequent runs (without `force: true`), installation is skipped.

## Requirements

**Locally (where Ansible runs):**
- `butane` — for compiling Butane to Ignition
- `ignition-validate` — for validating Ignition configuration

**On target host:**
- `coreos-installer` — for installing FCOS to disk
- Booted from Fedora CoreOS Live ISO

## Variables

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `system_disk` | string | Target device for FCOS installation (e.g., `/dev/vda`) |
| `core_user_ssh_keys` | list | SSH public keys for `core` user (admin) |
| `ansible_user_ssh_keys` | list | SSH public keys for `ansible` user (automation) |

### Templates

| Variable | Default | Description |
|----------|---------|-------------|
| `fcos_templates` | (see below) | List of Butane template paths |
| `fcos_extra_templates` | `[]` | Additional templates to append |

**Default templates** (in collection path `roles/install/templates/`):

| Template | Description |
|----------|-------------|
| `users.bu.j2` | User accounts (core, ansible) |
| `ssh.bu.j2` | SSH server configuration |
| `system.bu.j2` | System settings, sysctl, limits |
| `updates.bu.j2` | Zincati auto-updates |
| `network.bu.j2` | NetworkManager configuration |
| `firewall.bu.j2` | nftables rules |
| `storage.bu.j2` | Disk partitioning and mounts |
| `podman.bu.j2` | Container runtime settings |

**Customization examples:**

Add extra template to defaults:

```yaml
fcos_extra_templates:
  - "{{ playbook_dir }}/templates/my-app.bu.j2"
```

Replace all templates with custom ones:

```yaml
fcos_templates:
  - "{{ playbook_dir }}/templates/my-users.bu.j2"
  - "{{ playbook_dir }}/templates/my-system.bu.j2"
```

Mix default and custom templates:

```yaml
fcos_templates:
  # Use some defaults from collection
  - "~/.ansible/collections/ansible_collections/kudato/fcos/roles/install/templates/users.bu.j2"
  - "~/.ansible/collections/ansible_collections/kudato/fcos/roles/install/templates/ssh.bu.j2"
  # Add your own
  - "{{ playbook_dir }}/templates/my-network.bu.j2"
```

### Installation

| Variable | Default | Description |
|----------|---------|-------------|
| `force` | `false` | Force reinstallation even if FCOS is already installed |
| `butane_version` | `"1.6.0"` | Butane specification version |

### Users

Two users are created:

| User | UID | Groups | Description |
|------|-----|--------|-------------|
| `core` | 1000 (builtin) | wheel, adm, systemd-journal (default) | Admin user (FCOS builtin) |
| `ansible` | 1001 | wheel, systemd-journal | Automation user with passwordless sudo |

### SSH

| Variable | Default | Description |
|----------|---------|-------------|
| `ssh_port` | `22` | SSH server port |

SSH server is configured with hardened security:
- Public key authentication only (passwords disabled)
- Ed25519 algorithms only
- Modern ciphers and MACs

### System

#### General

| Variable | Default | Description |
|----------|---------|-------------|
| `timezone` | `UTC` | Timezone |
| `ip_forward` | `false` | Enable IP forwarding (for routing between interfaces) |

#### Journal

| Variable | Default | Description |
|----------|---------|-------------|
| `journal_max_size` | `500M` | Maximum journal size |
| `journal_max_file_size` | `50M` | Maximum journal file size |
| `journal_retention` | `1month` | Journal retention period |

#### Process Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `max_open_files_soft` | `65535` | Soft limit for open files |
| `max_open_files_hard` | `65535` | Hard limit for open files |
| `max_processes_soft` | `65535` | Soft limit for processes |
| `max_processes_hard` | `65535` | Hard limit for processes |

#### Network Buffers

| Variable | Default | Description |
|----------|---------|-------------|
| `net_rmem_max` | `16777216` | Maximum receive buffer size (16 MB) |
| `net_wmem_max` | `16777216` | Maximum send buffer size (16 MB) |
| `tcp_rmem` | `"4096 87380 16777216"` | TCP receive buffer: min, default, max |
| `tcp_wmem` | `"4096 87380 16777216"` | TCP send buffer: min, default, max |

**Tuning tips:**
- For 10Gbps+ networks, increase to `67108864` (64 MB)
- For memory-constrained systems, reduce to `4194304` (4 MB)

#### TCP Congestion Control

| Variable | Default | Description |
|----------|---------|-------------|
| `tcp_congestion_control` | `bbr` | TCP congestion control algorithm |
| `default_qdisc` | `fq` | Default queuing discipline |

**Available options:**
- `bbr` + `fq` — Google BBR, best for most cases, excellent on lossy networks
- `cubic` + `fq_codel` — Linux default, good for LAN environments
- `bbr` + `fq_codel` — Alternative, slightly higher CPU usage

#### Connection Queues

| Variable | Default | Description |
|----------|---------|-------------|
| `netdev_max_backlog` | `5000` | Max packets in incoming queue before processing |
| `somaxconn` | `4096` | Max pending connections in listen() backlog |
| `tcp_max_syn_backlog` | `4096` | Max SYN requests queued |

**Tuning tips:**
- High-traffic servers (>10k conn/sec): increase to `16384` or `32768`
- Low-traffic/embedded: default values are fine

#### TIME_WAIT Optimization

| Variable | Default | Description |
|----------|---------|-------------|
| `tcp_max_tw_buckets` | `262144` | Max sockets in TIME_WAIT state |
| `tcp_tw_reuse` | `1` | Reuse TIME_WAIT sockets for new connections |
| `tcp_fin_timeout` | `15` | Seconds to wait for FIN packet |

**Tuning tips:**
- Proxy/load balancer with many outgoing connections: increase `tcp_max_tw_buckets` to `2000000`
- `tcp_tw_reuse=1` is safe for outgoing connections, saves ports

#### Keepalive

| Variable | Default | Description |
|----------|---------|-------------|
| `tcp_keepalive_time` | `600` | Seconds before sending keepalive probes |
| `tcp_keepalive_intvl` | `30` | Seconds between keepalive probes |
| `tcp_keepalive_probes` | `5` | Number of probes before connection is dead |

**Tuning tips:**
- For faster dead connection detection: reduce `tcp_keepalive_time` to `60`
- For mobile/unreliable networks: increase to `1200` to avoid false disconnects

#### Performance Optimizations

| Variable | Default | Description |
|----------|---------|-------------|
| `tcp_slow_start_after_idle` | `0` | Disable slow start after idle |
| `tcp_mtu_probing` | `1` | Enable MTU probing |
| `tcp_fastopen` | `3` | TCP Fast Open (0=off, 1=client, 2=server, 3=both) |

**Notes:**
- `tcp_slow_start_after_idle=0` — keeps congestion window, good for HTTP keepalive
- `tcp_mtu_probing=1` — auto-detects MTU, useful for jumbo frames
- `tcp_fastopen=3` — reduces latency on reconnects, may not work through some NATs

#### Port Range

| Variable | Default | Description |
|----------|---------|-------------|
| `ip_local_port_range` | `"10240 65535"` | Range of local ports for outgoing connections |

**Tuning tips:**
- Default provides ~55k ports
- For systems with many outgoing connections: `"1024 65535"` (~64k ports)

#### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `disable_ipv6_ra` | `false` | Disable IPv6 Router Advertisements (set `true` for static IPv6 config) |

The following security settings are always applied (hardcoded):
- `kernel.dmesg_restrict = 1` — restrict dmesg access
- `kernel.kptr_restrict = 2` — hide kernel pointers
- `kernel.yama.ptrace_scope = 1` — restrict ptrace
- `fs.protected_hardlinks = 1` — protect hardlinks
- `fs.protected_symlinks = 1` — protect symlinks
- `net.ipv4.conf.all.send_redirects = 0` — disable ICMP redirects

#### VM/Memory

| Variable | Default | Description |
|----------|---------|-------------|
| `vm_swappiness` | `10` | Swap usage preference (0-100, lower = prefer RAM) |
| `vm_dirty_ratio` | `40` | Max % of memory for dirty pages before sync |
| `vm_dirty_background_ratio` | `10` | % of memory for background writeback |
| `fs_file_max` | `2097152` | System-wide file descriptor limit |
| `kernel_panic_timeout` | `10` | Seconds before auto-reboot on kernel panic |

**Tuning tips:**
- For database servers: reduce `vm_dirty_ratio` to `15-20` for more frequent writes
- For write-heavy workloads: increase `vm_dirty_ratio` to `60-80`
- `vm_swappiness=10` is good for servers, use `1` for no-swap systems

### Updates (Zincati)

| Variable | Default | Description |
|----------|---------|-------------|
| `maintenance_window_days` | `'["Sun"]'` | Days of week for updates |
| `maintenance_window_start` | `"03:00"` | Update window start time |
| `maintenance_window_length` | `60` | Window duration in minutes |

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `network_interfaces` | `[]` | List of network interfaces |

Each `network_interfaces` element:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | yes | — | Interface name |
| `type` | yes | — | Interface type: `wan` or `lan` |
| `mac_address` | no | — | MAC address for udev renaming |
| `dhcp` | no | `false` | Use DHCP |
| `static_ip` | no | — | Static IP address (required if not DHCP) |
| `network_prefix` | no | — | Network prefix length (required if not DHCP) |
| `gateway` | no | — | Gateway address |
| `dns_servers` | no | `[]` | DNS servers list |
| `default_route` | no | `true` | Use this interface as default gateway |

```yaml
network_interfaces:
  # WAN with DHCP (default gateway)
  - name: eth0
    type: wan
    mac_address: "00:11:22:33:44:55"
    dhcp: true
    default_route: true

  # Secondary WAN (not default gateway)
  - name: eth1
    type: wan
    mac_address: "00:11:22:33:44:66"
    dhcp: true
    default_route: false

  # LAN with static IP
  - name: eth2
    type: lan
    mac_address: "00:11:22:33:44:77"
    static_ip: "192.168.1.1"
    network_prefix: 24
    dns_servers:
      - "8.8.8.8"
```

### Firewall

| Variable | Default | Description |
|----------|---------|-------------|
| `firewall_allow_icmp` | `true` | Allow ICMP (ping) |

Configures nftables with rules based on interface types:
- **Input**: allows SSH, loopback, established/related, ICMP (optional), all traffic from LAN interfaces
- **Forward**: LAN ↔ LAN traffic allowed, LAN → WAN allowed (internet access)
- **Output**: all allowed

Additional rules can be placed in `/etc/nftables.d/*.nft`.

### Storage

The system disk uses predefined partitioning (BIOS-BOOT, EFI, boot, root, swap, var).

#### System Disk

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `system_disk` | yes | — | Target device for installation (e.g., `/dev/vda`) |
| `wipe_system_disk` | no | `false` | Wipe partition table |
| `swap_size` | no | `0` | Swap size in MiB (0 = disabled) |

**Simple example:**

```yaml
system_disk: /dev/vda
wipe_system_disk: true
```

**With swap:**

```yaml
system_disk: /dev/vda
wipe_system_disk: true
swap_size: 2048
```

#### Additional Disks

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `additional_disks` | no | `[]` | List of additional disks to partition and mount |

Each `additional_disks` element:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `device` | yes | — | Block device path (e.g., `/dev/vdb`) |
| `wipe_table` | no | `false` | Wipe partition table before partitioning |
| `partitions` | yes | — | List of partitions to create |

Each `partitions` element:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `label` | yes | — | Partition label |
| `size_mib` | no | `0` | Partition size in MiB (0 = use all remaining space) |
| `mount_path` | no | — | Where to mount the partition |
| `format` | no | — | Filesystem type (required if `mount_path` is set) |

**Example with additional disks:**

```yaml
additional_disks:
  # Data disk - single partition using all space
  - device: /dev/vdb
    wipe_table: true
    partitions:
      - label: data
        size_mib: 0
        mount_path: /var/data
        format: xfs

  # Multi-partition disk
  - device: /dev/vdc
    wipe_table: true
    partitions:
      - label: backup
        size_mib: 51200  # 50 GB
        mount_path: /var/backup
        format: xfs
      - label: logs
        size_mib: 0      # remaining space
        mount_path: /var/log/external
        format: ext4
```

### Podman

The role configures:
- Masks Docker services (docker.service, docker.socket)
- Creates `docker` → `podman` alias
- Disables short-name-mode for container images

## Usage Example

### Inventory

```yaml
# inventory/hosts.yml
all:
  hosts:
    server1:
      ansible_host: 192.168.1.100
    server2:
      ansible_host: 192.168.1.101
```

### Host vars

```yaml
# inventory/host_vars/server1.yml
system_disk: /dev/sda
wipe_system_disk: true
```

### Group vars

```yaml
# inventory/group_vars/all.yml
core_user_ssh_keys:
  - "ssh-ed25519 AAAA... admin@example.com"

ansible_user_ssh_keys:
  - "ssh-ed25519 AAAA... ansible@example.com"

network_interfaces:
  - name: eth0
    type: wan
    dhcp: true
```

### Playbook

```yaml
# install.yml
- name: Install Fedora CoreOS
  hosts: all
  gather_facts: false
  roles:
    - kudato.fcos.install
```

### Running

```bash
# Normal installation
ansible-playbook -i inventory/hosts.yml install.yml

# Dry run (check mode)
ansible-playbook -i inventory/hosts.yml install.yml --check

# Force reinstallation
ansible-playbook -i inventory/hosts.yml install.yml -e force=true
```

## License

MIT
