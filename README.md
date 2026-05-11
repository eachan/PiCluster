# PiCluster

A small, production-quality Raspberry Pi cluster that provides:

- A 3-node **K3s** (Kubernetes) cluster on `node-1`, `node-2`, `node-3` for hosting apps and websites.
- A distributed, replicated **GlusterFS** volume across all three nodes' 1 TB USB drives.
- A highly-available **Samba** share (CTDB) on top of GlusterFS that Windows machines mount as a network drive.
- A **supervisor** Pi running monitoring (Prometheus + Grafana), a live HDMI dashboard, and the deployment tooling.
- An **AI** Pi running **Ollama** (with optional Hailo-8 acceleration) that exposes an HTTP LLM API to apps in the cluster.
- A one-command **deploy tool** (`piclusterctl`) running on the supervisor that pulls the latest version of this repo from GitHub and rolls changes out to every node.

## Hosts

| Hostname     | Role               | Hardware                                    |
| ------------ | ------------------ | ------------------------------------------- |
| `supervisor` | Management + UI    | Pi 4, 8 GB RAM, HDMI0 display attached      |
| `node-1`     | Cluster + storage  | Pi 5, 16 GB RAM, 1 TB USB drive             |
| `node-2`     | Cluster + storage  | Pi 5, 16 GB RAM, 1 TB USB drive             |
| `node-3`     | Cluster + storage  | Pi 5, 16 GB RAM, 1 TB USB drive             |
| `ai`         | Local LLM          | Pi + Hailo-8 AI HAT                         |

Resolving all hostnames is assumed to be handled by your LAN DNS.

## Repository layout

```
.
├── ansible/                  # Ansible inventory, playbooks, roles
│   ├── inventory/hosts.yml
│   ├── group_vars/all.yml
│   ├── site.yml              # top-level playbook (everything)
│   ├── playbooks/            # focused per-tier playbooks
│   └── roles/                # idempotent roles
├── dashboard/                # FastAPI + static-HTML supervisor dashboard
├── deploy/                   # piclusterctl CLI + systemd units
├── scripts/                  # bootstrap helpers
└── docs/                     # ARCHITECTURE / SETUP / DEPLOY
```

## Quick start

From a fresh, networked supervisor (with SSH keys to all nodes or password
auth set up):

```bash
# On the supervisor, as user 'eachan'
curl -fsSL https://raw.githubusercontent.com/<your-user>/PiCluster/main/scripts/bootstrap-supervisor.sh | bash
```

That script installs git/ansible/python/etc., clones this repo to
`/opt/picluster`, installs the `piclusterctl` CLI, and runs the full
`piclusterctl deploy` for the first time. Subsequent updates are:

```bash
piclusterctl deploy            # pull latest main, run site.yml everywhere
piclusterctl deploy --tags k3s # roll just the k3s changes
piclusterctl status            # show cluster + node status
piclusterctl ssh node-2        # quick SSH helper
```

See [`docs/SETUP.md`](docs/SETUP.md) for the full step-by-step, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how the pieces fit
together.

## Defaults

| Setting                  | Value                              |
| ------------------------ | ---------------------------------- |
| SSH user                 | `eachan`                           |
| Samba share              | `\\picluster\storage` (VIP)        |
| K3s API VIP              | `node-1` (configurable)            |
| Cluster ingress          | Traefik (bundled with K3s)         |
| Dashboard URL            | `http://supervisor/`               |
| Grafana URL              | `http://supervisor:3000/`          |
| Prometheus URL           | `http://supervisor:9090/`          |
| Ollama URL (cluster-internal) | `http://ai:11434/`            |

Default credentials and other secrets are read from
`ansible/group_vars/all.yml`. **Change them before you deploy in any
shared environment** (see [`docs/SETUP.md`](docs/SETUP.md) for which
values are mandatory).
