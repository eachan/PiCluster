# PiCluster supervisor dashboard

A small FastAPI app that drives the kiosk display attached to the supervisor's
HDMI0 output and the web view at `http://supervisor/`.

It aggregates data from:

- **Prometheus** (`/api/v1/query`) - CPU/mem/disk/temp/uptime/load per host.
- **kubectl** (using the supervisor's kubeconfig) - cluster nodes, pods,
  services.
- **Ollama** (`/api/tags` on the AI host) - loaded models.
- **Direct TCP probes** - Samba (445 on the VIP).

…and streams snapshots to the UI over a WebSocket every `REFRESH_INTERVAL`
seconds.

## Running locally for development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# Point it at a real (or mocked) Prometheus.
export PROMETHEUS_URL=http://supervisor:9090
export OLLAMA_URL=http://ai:11434
export CLUSTER_HOSTS=node-1,node-2,node-3
python app.py
```

Open <http://localhost:8000/>.

## Environment variables

| Variable             | Default                          | Meaning                                              |
| -------------------- | -------------------------------- | ---------------------------------------------------- |
| `PROMETHEUS_URL`     | `http://localhost:9090`          | Prometheus base URL                                  |
| `OLLAMA_URL`         | `http://ai:11434`                | Ollama base URL                                      |
| `SAMBA_VIP`          | `192.168.1.50`                   | Samba VIP for TCP probe                              |
| `SAMBA_SHARE`        | `storage`                        | Share name (display only)                            |
| `CLUSTER_HOSTS`      | `node-1,node-2,node-3`           | comma-separated host list                            |
| `SUPERVISOR_HOST`    | `supervisor`                     | this host's name                                     |
| `AI_HOST`            | `ai`                             | AI host's name                                       |
| `KUBECONFIG`         | `~/.kube/config`                 | kubeconfig path for cluster queries                  |
| `PORT`               | `8000`                           | listen port                                          |
| `STATIC_DIR`         | `./static`                       | path to static UI files                              |
| `REFRESH_INTERVAL`   | `2.0`                            | seconds between snapshots                            |
| `HISTORY_LENGTH`     | `150`                            | rolling sample buffer (~5 min at 2s)                 |

## API

- `GET /` - the dashboard UI (`static/index.html`)
- `GET /api/state` - latest snapshot (JSON)
- `GET /api/state/history` - rolling history of CPU/mem/temp samples
- `GET /metrics` - Prometheus metrics for this app
- `WS  /ws` - subscribes to live snapshots
