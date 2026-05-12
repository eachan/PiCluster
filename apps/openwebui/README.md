# Open WebUI

A ChatGPT-style web UI for the Ollama LLM running on the **ai** Pi. Deployed
as the first user-facing app on the K3s cluster.

## URL

| Audience      | URL                       | Notes                                  |
| ------------- | ------------------------- | -------------------------------------- |
| LAN users     | `http://192.168.1.51`     | **Primary.** MetalLB-managed floating VIP - automatically follows whichever cluster node is up. |
| Fallback      | `http://node-1:30080`     | NodePort - works on `node-2` / `node-3` too if you need a specific node. |

The VIP (`192.168.1.51`) is allocated from the MetalLB pool defined in
`ansible/inventory/group_vars/all.yml` (`metallb_address_pool`). It uses
gratuitous ARP - one node "owns" the IP at any time and answers for it;
when that node fails another node takes over within a few seconds. To
change the VIP, edit the `metallb.universe.tf/loadBalancerIPs` annotation
in `manifest.yaml` (it must lie within `metallb_address_pool`).

## First login

The very first user to sign up at the URL becomes the **admin**. After that:

- Settings -> Admin Settings -> Users to manage who can log in.
- Settings -> Models will already show whatever models are loaded into
  `ollama` on the AI Pi (currently `llama3.2:3b`).

## Storage

All data (SQLite DB, uploaded files, chat history) lives on the GlusterFS
replicated volume at `/mnt/storage/apps/openwebui`. It's backed up
automatically by replication - any single cluster node can be lost without
data loss.

## Resources

| Limit         | Value      |
| ------------- | ---------- |
| CPU request   | 200m       |
| Memory request| 512 Mi     |
| Memory limit  | 2 Gi       |
| Replicas      | 1 (SQLite) |

## Adjusting

Edit `manifest.yaml` and `piclusterctl deploy --tags apps`. Re-applies
the manifest; Kubernetes does a rolling update (or a Recreate, because of
the SQLite volume).

## Removing

```bash
kubectl delete -f apps/openwebui/manifest.yaml
# The PV uses 'Retain' so the data on GlusterFS is left intact.
# Delete it manually if you really want to start over:
sudo rm -rf /mnt/storage/apps/openwebui
```
