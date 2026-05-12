// PiCluster dashboard front-end: subscribes to /ws and renders snapshots.

(function () {
  "use strict";

  const els = {
    connection: document.getElementById("connection"),
    clock: document.getElementById("clock"),
    hosts: document.getElementById("hosts"),
    cluster: document.getElementById("cluster"),
    apps: document.getElementById("apps"),
    storage: document.getElementById("storage"),
    services: document.getElementById("services"),
    ai: document.getElementById("ai"),
    lastUpdate: document.getElementById("last-update"),
  };

  // -------------------- helpers --------------------
  const fmtBytes = (n) => {
    if (n == null || isNaN(n)) return "—";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
  };
  const fmtPct = (n) => (n == null ? "—" : `${Math.round(n)}%`);
  const fmtUptime = (s) => {
    if (s == null) return "—";
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  };
  const setText = (el, t) => { if (el) el.textContent = t; };
  const escape = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[c]);

  const barClass = (pct) => {
    if (pct == null) return "";
    if (pct >= 90) return "bad";
    if (pct >= 75) return "warn";
    return "";
  };

  // -------------------- renderers --------------------
  function renderHosts(hosts) {
    const html = hosts.map((h) => `
      <div class="host ${h.up ? "" : "down"}">
        <div class="host-head">
          <div>
            <div class="host-name">${escape(h.host)}</div>
            <div class="host-role">${escape(h.role)}</div>
          </div>
          <span class="pill ${h.up ? "pill-ok" : "pill-bad"}">${h.up ? "up" : "down"}</span>
        </div>
        <div class="host-row"><span class="key">CPU</span>
          <span class="val">${fmtPct(h.cpu_percent)}</span></div>
        <div class="bar ${barClass(h.cpu_percent)}"><span style="width:${Math.min(100, h.cpu_percent || 0)}%"></span></div>
        <div class="host-row"><span class="key">Memory</span>
          <span class="val">${fmtPct(h.mem_percent)}</span></div>
        <div class="bar ${barClass(h.mem_percent)}"><span style="width:${Math.min(100, h.mem_percent || 0)}%"></span></div>
        <div class="host-row"><span class="key">Disk /</span>
          <span class="val">${fmtPct(h.disk_percent)}</span></div>
        <div class="bar ${barClass(h.disk_percent)}"><span style="width:${Math.min(100, h.disk_percent || 0)}%"></span></div>
        <div class="host-row"><span class="key">Load</span>
          <span class="val">${h.load1 != null ? h.load1.toFixed(2) : "—"}</span></div>
        <div class="host-row"><span class="key">Temp</span>
          <span class="val">${h.temperature_c != null ? h.temperature_c.toFixed(1) + "°C" : "—"}</span></div>
        <div class="host-row"><span class="key">Uptime</span>
          <span class="val">${fmtUptime(h.uptime_seconds)}</span></div>
      </div>`).join("");
    els.hosts.innerHTML = html;
  }

  function renderCluster(c) {
    if (!c || !c.nodes || c.nodes.length === 0) {
      els.cluster.innerHTML = `<div class="empty">Cluster not reachable yet.</div>`;
      return;
    }
    els.cluster.innerHTML = c.nodes.map((n) => `
      <div class="k-node">
        <div class="nm">${escape(n.name)}
          <span class="pill ${n.ready ? "pill-ok" : "pill-bad"}">${n.ready ? "ready" : "down"}</span>
        </div>
        <div class="det">${escape(n.version || "")}<br/>${escape(n.arch || "")}</div>
      </div>`).join("");
  }

  function renderApps(apps) {
    if (!apps || apps.length === 0) {
      els.apps.innerHTML = `<div class="empty">No user apps deployed yet.</div>`;
      return;
    }
    els.apps.innerHTML = apps.map((a) => {
      const title = a.title || a.name;
      const endpoint = a.endpoint_url || "";
      const desc = a.description ? `<div class="desc">${escape(a.description)}</div>` : "";
      const ep = endpoint
        ? `<a class="ep" href="${escape(endpoint)}" target="_blank" rel="noopener">${escape(endpoint)}</a>`
        : `<span class="ep">${escape(a.cluster_ip || "")}${a.port ? ":" + a.port : ""}</span>`;
      return `
        <div class="app">
          <div class="nm">${escape(title)}</div>
          <div class="ns">${escape(a.namespace)} · ${escape(a.type)}</div>
          ${desc}
          ${ep}
        </div>`;
    }).join("");
  }

  function renderStorage(s) {
    if (!s || !s.total_bytes) {
      els.storage.innerHTML = `<div class="empty">Storage volume not mounted yet.</div>`;
      return;
    }
    const pct = s.used_percent;
    const angle = (pct / 100) * 360;
    const accent = pct >= 90 ? "#f87171" : pct >= 75 ? "#fbbf24" : "#6ea8ff";
    els.storage.innerHTML = `
      <div class="share-line">${escape(s.share)}</div>
      <div class="donut">
        <svg viewBox="0 0 36 36" aria-hidden="true">
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="3"/>
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="${accent}" stroke-width="3"
                  stroke-dasharray="${(angle / 360) * 97.39} 97.39" transform="rotate(-90 18 18)"
                  stroke-linecap="round" />
        </svg>
        <div>
          <div class="pct">${pct.toFixed(0)}%</div>
          <div class="sub">${fmtBytes(s.used_bytes)} used of ${fmtBytes(s.total_bytes)}</div>
          <div class="sub">${fmtBytes(s.free_bytes)} free</div>
        </div>
      </div>`;
  }

  function renderServices(svcs) {
    els.services.innerHTML = (svcs || []).map((s) => `
      <div class="svc ${s.ok ? "ok" : "bad"}">
        <div class="nm">${escape(s.name)}
          <span class="pill ${s.ok ? "pill-ok" : "pill-bad"}">${s.ok ? "ok" : "down"}</span>
        </div>
        <div class="dt">${escape(s.detail || s.url || "")}</div>
      </div>`).join("");
  }

  function renderAi(ai) {
    if (!ai) {
      els.ai.innerHTML = `<div class="empty">AI node not reachable.</div>`;
      return;
    }
    const status = ai.ok
      ? `<span class="pill pill-ok">online</span>`
      : `<span class="pill pill-bad">offline</span>`;
    const models = (ai.models || []).map((m) => `<span class="model">${escape(m)}</span>`).join("") ||
      `<span class="empty">no models</span>`;
    els.ai.innerHTML = `
      <div class="ai-head">${status}<span class="dt">${escape(ai.url || "")}</span></div>
      <div class="models">${models}</div>`;
  }

  function renderSnapshot(snap) {
    renderHosts(snap.hosts || []);
    renderCluster(snap.cluster || {});
    renderApps(snap.apps || []);
    renderStorage(snap.storage || {});
    renderServices(snap.services || []);
    renderAi(snap.ai || {});
    const dt = new Date(snap.timestamp * 1000);
    setText(els.lastUpdate, `last update ${dt.toLocaleTimeString()}`);
  }

  // -------------------- WebSocket --------------------
  function setConn(state, text) {
    els.connection.className = `pill pill-${state}`;
    els.connection.textContent = text;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    let alive = false;
    setConn("warn", "connecting…");

    ws.onopen = () => { alive = true; setConn("ok", "live"); };
    ws.onmessage = (e) => {
      try { renderSnapshot(JSON.parse(e.data)); }
      catch (err) { console.error("bad payload", err); }
    };
    ws.onclose = () => {
      setConn("bad", "reconnecting…");
      setTimeout(connect, alive ? 1000 : 3000);
    };
    ws.onerror = () => ws.close();
  }

  // Initial render from REST (fast first paint) then live WS.
  fetch("/api/state")
    .then((r) => r.json())
    .then(renderSnapshot)
    .catch(() => {})
    .finally(connect);

  // Clock
  function tick() {
    const d = new Date();
    setText(els.clock, d.toLocaleString());
  }
  tick();
  setInterval(tick, 1000);
})();
