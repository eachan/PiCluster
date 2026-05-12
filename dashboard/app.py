"""
PiCluster supervisor dashboard.

A small FastAPI app that:
  * Aggregates live telemetry from the local Prometheus instance.
  * Calls the K3s API (via kubectl-style HTTP) to list nodes, pods, services.
  * Probes Ollama on the AI host and the Samba share.
  * Streams everything to a single-page UI over a WebSocket every 2 seconds.

The endpoint surface intentionally stays simple:
    GET  /                    -> static index.html (the dashboard UI)
    GET  /api/state           -> latest snapshot (one-shot JSON)
    GET  /api/state/history   -> recent samples for sparklines (~5 min)
    GET  /metrics             -> Prometheus metrics for this app
    WS   /ws                  -> push snapshots every refresh_interval seconds
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Config (env-driven; sensible defaults match the Ansible deployment)
# ---------------------------------------------------------------------------

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ai:11434")
SAMBA_VIP = os.environ.get("SAMBA_VIP", "192.168.1.50")
SAMBA_SHARE = os.environ.get("SAMBA_SHARE", "storage")
CLUSTER_HOSTS = [
    h.strip() for h in os.environ.get("CLUSTER_HOSTS", "node-1,node-2,node-3").split(",") if h.strip()
]
SUPERVISOR_HOST = os.environ.get("SUPERVISOR_HOST", "supervisor")
AI_HOST = os.environ.get("AI_HOST", "ai")
REFRESH_INTERVAL = float(os.environ.get("REFRESH_INTERVAL", "2.0"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "150"))  # ~5 min at 2s
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).parent / "static"))

KUBECONFIG = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config"))

log = logging.getLogger("picluster.dashboard")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------------------------------------------------------------------------
# Prometheus metrics (for the dashboard's own /metrics endpoint)
# ---------------------------------------------------------------------------

m_snapshot_built = Counter("picluster_dashboard_snapshots_total",
                           "Number of telemetry snapshots built")
m_snapshot_duration = Gauge("picluster_dashboard_snapshot_duration_seconds",
                            "Time to build the last snapshot")
m_ws_clients = Gauge("picluster_dashboard_ws_clients",
                     "Currently-connected WebSocket clients")
m_host_up = Gauge("picluster_dashboard_host_up",
                  "1 if the dashboard last saw the host as up", ["host"])

# ---------------------------------------------------------------------------
# Snapshot building
# ---------------------------------------------------------------------------


@dataclass
class HostSample:
    host: str
    role: str
    up: bool = False
    cpu_percent: float | None = None
    mem_percent: float | None = None
    disk_percent: float | None = None
    temperature_c: float | None = None
    load1: float | None = None
    uptime_seconds: float | None = None


@dataclass
class ServiceStatus:
    name: str
    ok: bool
    detail: str = ""
    url: str = ""


@dataclass
class Snapshot:
    timestamp: float
    hosts: list[HostSample] = field(default_factory=list)
    services: list[ServiceStatus] = field(default_factory=list)
    cluster: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)
    apps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "hosts": [h.__dict__ for h in self.hosts],
            "services": [s.__dict__ for s in self.services],
            "cluster": self.cluster,
            "ai": self.ai,
            "storage": self.storage,
            "apps": self.apps,
        }


HOST_ROLE = {SUPERVISOR_HOST: "supervisor", AI_HOST: "ai"}
for h in CLUSTER_HOSTS:
    HOST_ROLE[h] = "cluster"

ALL_HOSTS = [SUPERVISOR_HOST, *CLUSTER_HOSTS, AI_HOST]


# Cache of the most recent snapshot and a short rolling history.
class State:
    def __init__(self) -> None:
        self.latest: Snapshot | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LENGTH)
        self.subscribers: set[asyncio.Queue] = set()


state = State()


async def _prom_query(client: httpx.AsyncClient, expr: str) -> dict[str, float]:
    """Run an instant query and return {host: value}."""
    try:
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
                             params={"query": expr},
                             timeout=3.0)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return {}
        out: dict[str, float] = {}
        for sample in data["data"]["result"]:
            host = sample["metric"].get("host") or sample["metric"].get("instance", "")
            host = host.split(":")[0]
            try:
                out[host] = float(sample["value"][1])
            except (TypeError, ValueError):
                pass
        return out
    except Exception as exc:  # network errors, prom not ready, etc.
        log.debug("prometheus query failed (%s): %s", expr, exc)
        return {}


async def _collect_host_samples(client: httpx.AsyncClient) -> list[HostSample]:
    queries = {
        "up":   "up{job=\"node\"}",
        "cpu":  "100 - (avg by (host) (rate(node_cpu_seconds_total{mode=\"idle\"}[1m])) * 100)",
        "mem":  "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
        "disk": "(1 - (node_filesystem_avail_bytes{mountpoint=\"/\"} / node_filesystem_size_bytes{mountpoint=\"/\"})) * 100",
        "temp": "avg by (host) (node_hwmon_temp_celsius)",
        "load": "node_load1",
        "boot": "node_boot_time_seconds",
    }
    results = await asyncio.gather(*[_prom_query(client, q) for q in queries.values()])
    by_name = dict(zip(queries.keys(), results))

    now = time.time()
    samples: list[HostSample] = []
    for host in ALL_HOSTS:
        up = by_name["up"].get(host, 0.0) >= 1.0
        boot = by_name["boot"].get(host)
        samples.append(HostSample(
            host=host,
            role=HOST_ROLE.get(host, "unknown"),
            up=up,
            cpu_percent=round(by_name["cpu"].get(host), 1) if host in by_name["cpu"] else None,
            mem_percent=round(by_name["mem"].get(host), 1) if host in by_name["mem"] else None,
            disk_percent=round(by_name["disk"].get(host), 1) if host in by_name["disk"] else None,
            temperature_c=round(by_name["temp"].get(host), 1) if host in by_name["temp"] else None,
            load1=round(by_name["load"].get(host), 2) if host in by_name["load"] else None,
            uptime_seconds=(now - boot) if boot else None,
        ))
        m_host_up.labels(host=host).set(1 if up else 0)
    return samples


async def _probe_tcp(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(loop.run_in_executor(None,
                                                   lambda: socket.create_connection((host, port), timeout=timeout).close()),
                               timeout=timeout)
        return True
    except Exception:
        return False


async def _check_services(client: httpx.AsyncClient) -> list[ServiceStatus]:
    out: list[ServiceStatus] = []

    # Samba (SMB / port 445) on the VIP
    smb_ok = await _probe_tcp(SAMBA_VIP, 445, timeout=1.5)
    out.append(ServiceStatus(
        name="Samba (Windows share)",
        ok=smb_ok,
        detail=f"\\\\{SAMBA_VIP}\\{SAMBA_SHARE}" if smb_ok else "VIP unreachable on :445",
        url=f"smb://{SAMBA_VIP}/{SAMBA_SHARE}",
    ))

    # Ollama
    try:
        r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        ok = r.status_code == 200
        if ok:
            models = [m.get("name") for m in r.json().get("models", [])]
            detail = ", ".join(models) if models else "no models loaded"
        else:
            detail = f"HTTP {r.status_code}"
    except Exception as exc:
        ok = False
        detail = f"unreachable: {exc.__class__.__name__}"
    out.append(ServiceStatus(name="Ollama (LLM)", ok=ok, detail=detail, url=OLLAMA_URL))

    # Prometheus
    try:
        r = await client.get(f"{PROMETHEUS_URL}/-/ready", timeout=2.0)
        ok = r.status_code == 200
    except Exception:
        ok = False
    out.append(ServiceStatus(name="Prometheus", ok=ok, url=PROMETHEUS_URL))

    # Grafana
    try:
        r = await client.get("http://localhost:3000/api/health", timeout=2.0)
        ok = r.status_code == 200
    except Exception:
        ok = False
    out.append(ServiceStatus(name="Grafana", ok=ok, url="http://localhost:3000"))

    return out


async def _kubectl(args: list[str]) -> dict[str, Any] | None:
    """Run a kubectl JSON-output command and return parsed JSON, or None."""
    if not Path(KUBECONFIG).exists():
        return None
    proc = await asyncio.create_subprocess_exec(
        "kubectl", "--kubeconfig", KUBECONFIG, *args, "-o", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


async def _collect_cluster() -> dict[str, Any]:
    nodes = await _kubectl(["get", "nodes"])
    pods = await _kubectl(["get", "pods", "--all-namespaces"])
    info: dict[str, Any] = {"nodes": [], "pods_total": 0, "pods_running": 0, "namespaces": []}

    if nodes:
        for n in nodes.get("items", []):
            meta = n.get("metadata", {})
            status = n.get("status", {})
            conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}
            info["nodes"].append({
                "name": meta.get("name"),
                "ready": conditions.get("Ready") == "True",
                "version": status.get("nodeInfo", {}).get("kubeletVersion"),
                "os": status.get("nodeInfo", {}).get("osImage"),
                "arch": status.get("nodeInfo", {}).get("architecture"),
                "roles": [k.split("/")[-1] for k in meta.get("labels", {})
                          if k.startswith("node-role.kubernetes.io/")],
            })

    if pods:
        namespaces: set[str] = set()
        for p in pods.get("items", []):
            phase = p.get("status", {}).get("phase")
            info["pods_total"] += 1
            if phase == "Running":
                info["pods_running"] += 1
            namespaces.add(p.get("metadata", {}).get("namespace", "default"))
        info["namespaces"] = sorted(namespaces)
    return info


async def _collect_apps() -> list[dict[str, Any]]:
    """List cluster-hosted apps: any Service in non-system namespaces."""
    svcs = await _kubectl(["get", "services", "--all-namespaces"])
    if not svcs:
        return []
    apps: list[dict[str, Any]] = []
    system_namespaces = {"kube-system", "kube-public", "kube-node-lease"}
    primary_host = CLUSTER_HOSTS[0] if CLUSTER_HOSTS else "node-1"
    for s in svcs.get("items", []):
        ns = s["metadata"]["namespace"]
        if ns in system_namespaces:
            continue
        spec = s.get("spec", {})
        if spec.get("type") not in {"ClusterIP", "NodePort", "LoadBalancer"}:
            continue
        if spec.get("clusterIP") == "None":
            continue
        ports = spec.get("ports", []) or []
        port = ports[0].get("port") if ports else None
        node_port = ports[0].get("nodePort") if ports else None
        annotations = s.get("metadata", {}).get("annotations", {}) or {}
        title = annotations.get("picluster.dashboard/title") or s["metadata"]["name"]
        description = annotations.get("picluster.dashboard/description") or ""
        ingress = (s.get("status", {}).get("loadBalancer", {}).get("ingress") or [])
        lb_ip = ingress[0].get("ip") if ingress and isinstance(ingress[0], dict) else None

        def _http(host: str, p: int | None) -> str:
            if not host or not p:
                return ""
            return f"http://{host}" if p == 80 else f"http://{host}:{p}"

        if lb_ip:
            endpoint_url = _http(lb_ip, port)
        elif node_port:
            endpoint_url = _http(primary_host, node_port)
        elif spec.get("clusterIP") and port:
            endpoint_url = _http(spec["clusterIP"], port)
        else:
            endpoint_url = ""
        apps.append({
            "namespace": ns,
            "name": s["metadata"]["name"],
            "title": title,
            "description": description,
            "type": spec.get("type"),
            "cluster_ip": spec.get("clusterIP"),
            "lb_ip": lb_ip,
            "port": port,
            "node_port": node_port,
            "endpoint_url": endpoint_url,
        })
    return apps


async def _collect_storage(client: httpx.AsyncClient) -> dict[str, Any]:
    # Sum brick free bytes across nodes by mountpoint = /mnt/storage
    free = await _prom_query(client,
                             "node_filesystem_avail_bytes{mountpoint=\"/mnt/storage\"}")
    size = await _prom_query(client,
                             "node_filesystem_size_bytes{mountpoint=\"/mnt/storage\"}")
    if not free or not size:
        # Fall back to /srv/brick
        free = await _prom_query(client,
                                 "node_filesystem_avail_bytes{mountpoint=\"/srv/brick\"}")
        size = await _prom_query(client,
                                 "node_filesystem_size_bytes{mountpoint=\"/srv/brick\"}")
    # Pick max across nodes - replica volume so they should match.
    total = max(size.values(), default=0)
    avail = max(free.values(), default=0)
    used = total - avail if total else 0
    pct = (used / total * 100) if total else 0
    return {
        "total_bytes": int(total),
        "used_bytes": int(used),
        "free_bytes": int(avail),
        "used_percent": round(pct, 1),
        "share": f"\\\\{SAMBA_VIP}\\{SAMBA_SHARE}",
    }


async def _collect_ai(client: httpx.AsyncClient) -> dict[str, Any]:
    try:
        r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        if r.status_code == 200:
            return {
                "ok": True,
                "url": OLLAMA_URL,
                "models": [m.get("name") for m in r.json().get("models", [])],
            }
    except Exception:
        pass
    return {"ok": False, "url": OLLAMA_URL, "models": []}


async def build_snapshot() -> Snapshot:
    start = time.perf_counter()
    async with httpx.AsyncClient() as client:
        hosts, services, cluster, ai, storage, apps = await asyncio.gather(
            _collect_host_samples(client),
            _check_services(client),
            _collect_cluster(),
            _collect_ai(client),
            _collect_storage(client),
            _collect_apps(),
        )
    snap = Snapshot(timestamp=time.time(),
                    hosts=hosts, services=services,
                    cluster=cluster, ai=ai, storage=storage, apps=apps)
    m_snapshot_built.inc()
    m_snapshot_duration.set(time.perf_counter() - start)
    return snap


# ---------------------------------------------------------------------------
# Background refresh loop + fan-out
# ---------------------------------------------------------------------------


async def refresh_loop() -> None:
    backoff = 1.0
    while True:
        try:
            snap = await build_snapshot()
            payload = snap.to_dict()
            state.latest = snap
            state.history.append({
                "ts": payload["timestamp"],
                "hosts": [{"host": h["host"],
                           "cpu": h["cpu_percent"],
                           "mem": h["mem_percent"],
                           "temp": h["temperature_c"]}
                          for h in payload["hosts"]],
            })
            for q in list(state.subscribers):
                if q.full():
                    # drop the oldest for slow consumers
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)
            backoff = 1.0
        except Exception:
            log.exception("snapshot loop error")
            await asyncio.sleep(min(backoff, 10.0))
            backoff *= 2
            continue
        await asyncio.sleep(REFRESH_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(refresh_loop())
    log.info("dashboard backend ready; refresh interval=%.1fs", REFRESH_INTERVAL)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# HTTP / WS app
# ---------------------------------------------------------------------------

app = FastAPI(title="PiCluster Dashboard", lifespan=lifespan)


@app.get("/api/state")
async def api_state() -> JSONResponse:
    if state.latest is None:
        # Build one on demand if startup hasn't ticked yet
        snap = await build_snapshot()
        state.latest = snap
    return JSONResponse(state.latest.to_dict())


@app.get("/api/state/history")
async def api_history() -> JSONResponse:
    return JSONResponse(list(state.history))


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    state.subscribers.add(q)
    m_ws_clients.set(len(state.subscribers))
    try:
        # send current snapshot immediately if we have one
        if state.latest is not None:
            await ws.send_json(state.latest.to_dict())
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        state.subscribers.discard(q)
        m_ws_clients.set(len(state.subscribers))


# Static files (the UI) at the root.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    async def favicon() -> FileResponse:
        path = STATIC_DIR / "favicon.svg"
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
        return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app",
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                log_level=os.environ.get("LOG_LEVEL", "info").lower())
