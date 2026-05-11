# Setup guide

End-to-end install for a fresh cluster.

## 0. Prerequisites

Each Pi should already have:

- Raspberry Pi OS Bookworm (64-bit) installed.
- The hostname set to match the inventory (`supervisor`, `node-1`, `node-2`,
  `node-3`, `ai`). This is typically done from Raspberry Pi Imager.
- SSH enabled, with user `eachan` / password `w00dhill`.
- Network connectivity and resolvable LAN DNS for the hostnames above.
- For cluster nodes: the 1 TB USB drive plugged in (it will be wiped during
  GlusterFS setup if it's blank).

The supervisor's HDMI0 should be connected to a display.

## 1. Choose addresses for the Samba VIP

CTDB needs:

- An unused address on your LAN (the **VIP** that Windows clients use).
- The three cluster nodes' fixed addresses.

Edit `ansible/group_vars/all.yml` and set `ctdb_public_addresses` and
`ctdb_nodes`. Defaults assume a `192.168.1.0/24` LAN.

> Tip: assign the cluster nodes' fixed IPs via DHCP reservation so the
> hostnames keep working but the IPs stay constant.

## 2. Push the repo to GitHub

```bash
cd PiCluster
git init -b main
git add .
git commit -m "Initial PiCluster"
gh repo create your-user/PiCluster --public --source=. --push   # or use the web UI
```

Update `project_repo` in `ansible/group_vars/all.yml` and `REPO` in
`scripts/bootstrap-supervisor.sh` to point at the URL you just created.

## 3. Bootstrap the supervisor

SSH in once and run:

```bash
ssh eachan@supervisor
curl -fsSL https://raw.githubusercontent.com/your-user/PiCluster/main/scripts/bootstrap-supervisor.sh | bash
```

This installs Ansible, clones the repo to `/opt/picluster`, installs
`piclusterctl`, and creates an SSH key for the `eachan` user if one didn't
exist.

(Optional but recommended) copy the supervisor's key to every node so future
deploys don't need passwords:

```bash
for h in supervisor node-1 node-2 node-3 ai; do
  ssh-copy-id eachan@$h
done
```

## 4. Run the first deploy

From the supervisor:

```bash
piclusterctl deploy
```

This runs the entire `site.yml` playbook against every host:

1. **common** - sets hostnames, installs base packages, configures UFW, installs
   `node_exporter`.
2. **storage** - prepares the USB drives, builds the GlusterFS volume, mounts
   it on every cluster node at `/mnt/storage`.
3. **cluster** - installs K3s on `node-1` (`--cluster-init`), then joins
   `node-2` and `node-3` as additional HA servers (`serial: 1`).
4. **samba** - installs Samba + CTDB, configures the share, starts CTDB to
   manage the VIP.
5. **ai** - installs Ollama on the AI node and pulls the configured models.
6. **supervisor** - installs Prometheus, Grafana, the dashboard backend,
   nginx, the kiosk Chromium session, and `piclusterctl`.

First run takes ~20-30 minutes depending on network speed (Ollama model
download is the slowest single step). Subsequent runs are typically <2 minutes.

## 5. Verify

- Open `http://supervisor/` in a browser - you should see the dashboard with
  every host green.
- The HDMI display attached to the supervisor should be showing the same
  dashboard fullscreen after a reboot (or after `sudo systemctl restart lightdm`).
- From a Windows machine: `Win+R` -> `\\<VIP>\storage` -> auth as `eachan` /
  `w00dhill` -> the share opens.
- From the supervisor: `kubectl get nodes` should list all three nodes Ready.
- Ollama: `curl http://ai:11434/api/tags` should return JSON with your models.

## 6. Day-2 operations

| Want to…                              | Command                                          |
| ------------------------------------- | ------------------------------------------------ |
| Re-deploy everything                  | `piclusterctl deploy`                            |
| Only storage / samba                  | `piclusterctl deploy --tags storage,samba`       |
| Only the cluster (K3s)                | `piclusterctl deploy --tags cluster`             |
| Only the dashboard                    | `piclusterctl deploy --tags dashboard`           |
| Dry-run (show changes only)           | `piclusterctl deploy --check`                    |
| Restrict to one host                  | `piclusterctl deploy --target node-2`            |
| Show cluster status                   | `piclusterctl status`                            |
| Run a command on all hosts            | `piclusterctl run --target all -- uptime`        |
| Tail the deploy log                   | `piclusterctl logs -f`                           |
| Enable auto-deploy every 10 min       | set `auto_deploy_enabled: true` and re-deploy    |

## 7. Secrets

The defaults shipped in `group_vars/all.yml` are placeholders that work for a
home-lab setup. Before exposing this to anything sensitive:

- Replace `ansible_password`, `ansible_become_password`, `samba_password`,
  `grafana_admin_password`, and the `k3s_token`.
- Move them into a vaulted file:
  ```bash
  cd ansible
  ansible-vault create group_vars/secret.yml
  ```
  Then put the sensitive variables in that file. Run deploys with
  `--ask-vault-pass` (or set `ANSIBLE_VAULT_PASSWORD_FILE`).
