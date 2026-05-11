# Architecture

```
            ┌────────────────────────────────────────────────────────────┐
            │                          LAN                               │
            └─┬────────┬────────────┬────────────┬─────────────┬─────────┘
              │        │            │            │             │
        ┌─────┴─┐ ┌────┴────┐ ┌─────┴────┐ ┌─────┴────┐  ┌─────┴────┐
        │super- │ │ node-1  │ │  node-2  │ │  node-3  │  │    ai    │
        │visor  │ │  Pi 5   │ │  Pi 5    │ │  Pi 5    │  │ Pi+Hailo │
        │ Pi 4  │ │ 16GB    │ │  16GB    │ │  16GB    │  │          │
        └───┬───┘ │ +1TB USB│ │  +1TB USB│ │  +1TB USB│  └────┬─────┘
            │     └────┬────┘ └─────┬────┘ └─────┬────┘       │
            │          │            │            │            │
            │          └────────────┼────────────┘            │
            │                       │                         │
            │       GlusterFS replica-3 volume "storage"      │
            │       mounted on every cluster node at          │
            │           /mnt/storage                          │
            │                       │                         │
            │       Samba + CTDB exposes /mnt/storage/share   │
            │       to Windows clients at \\<VIP>\storage     │
            │                       │                         │
            │     K3s HA control plane (embedded etcd)        │
            │     Traefik ingress comes with K3s              │
            │                       │                         │
            │                       │                         │
   ┌────────┴────────┐               │                         │
   │ Prometheus      │◀───── /metrics from every host ────────┤
   │ Grafana         │                                         │
   │ Dashboard       │◀───── kubectl + ollama probe ───────────┘
   │ piclusterctl    │
   │ Chromium kiosk  │
   │ (HDMI0)         │
   └─────────────────┘
```

## Components

### Supervisor (`supervisor`, Pi 4)
- **Ansible control node** - holds the inventory and runs all playbooks.
- **Prometheus** scrapes `node_exporter` on every host plus K3s metrics and the dashboard's own metrics.
- **Grafana** is provisioned with the Prometheus data source and a pre-built
  "PiCluster - Nodes Overview" dashboard.
- **Dashboard** (FastAPI + WebSocket) aggregates Prometheus + kubectl + Ollama
  data and renders a single-page UI behind nginx on port 80.
- **Chromium kiosk** (autostarted by LightDM/openbox) shows the dashboard
  fullscreen on HDMI0.
- **`piclusterctl`** CLI - single-command deploy / status / SSH / run-on-all.

### Cluster nodes (`node-1`, `node-2`, `node-3`, Pi 5)
- Each runs a **K3s server** in HA mode (embedded etcd, three voters).
- Each owns a 1 TB USB disk formatted XFS and mounted at `/srv/brick`.
- A **GlusterFS replica-3** volume named `storage` is built from those bricks
  and mounted on every node at `/mnt/storage`.
- **Samba** exports `/mnt/storage/share`. **CTDB** clusters the Samba
  instances and floats a virtual IP (set in `group_vars/all.yml`).
- Apps deployed into Kubernetes can mount the same volume by referencing the
  hostPath `/mnt/storage/apps` (or via a HostPath PV).

### AI node (`ai`)
- Runs **Ollama** listening on `:11434` and pre-pulls models.
- The Hailo runtime is installed if a Hailo PCIe device is detected; apps that
  want Hailo acceleration can talk to it directly. Ollama itself uses CPU by
  default (or the Pi GPU when supported).

## Storage flow

1. Apps in the cluster write to `/mnt/storage` (a Gluster mount).
2. Gluster synchronously replicates writes to the brick on every node.
3. Windows clients connect to `\\<VIP>\storage` (CTDB's public address); CTDB
   ensures a surviving Samba node always owns that IP.
4. If a node dies, Gluster self-heal repairs the brick when it returns.

## Failure behaviour

| Failure                | Effect                                                              |
| ---------------------- | ------------------------------------------------------------------- |
| 1 cluster node down    | K3s stays up (etcd quorum 2/3). Samba VIP moves to a surviving node. Gluster keeps serving from 2 replicas. |
| 2 cluster nodes down   | K3s API loses quorum; reads still possible on remaining node. Samba degrades. Restore one node to recover. |
| Supervisor down        | Apps and file share keep working. Dashboard / Prometheus / Grafana / kiosk unavailable until supervisor returns. |
| AI node down           | LLM API unavailable; apps must degrade gracefully.                  |

## Network ports

| Host(s)    | Port  | Service              |
| ---------- | ----- | -------------------- |
| all        | 9100  | node_exporter        |
| supervisor | 80    | dashboard (nginx)    |
| supervisor | 3000  | Grafana              |
| supervisor | 9090  | Prometheus           |
| supervisor | 8000  | dashboard (internal) |
| cluster    | 6443  | K3s API              |
| cluster    | 10250 | Kubelet              |
| cluster    | 8472  | Flannel VXLAN (UDP)  |
| cluster    | 2379/2380 | etcd             |
| cluster    | 24007-24108 | GlusterFS      |
| cluster    | 445, 139 | SMB               |
| cluster    | 4379  | CTDB                 |
| ai         | 11434 | Ollama               |
