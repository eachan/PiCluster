# Open WebUI

A ChatGPT-style web UI for the Ollama LLM running on the **ai** Pi. Deployed
as the first user-facing app on the K3s cluster.

## URL

| Audience      | URL                            |
| ------------- | ------------------------------ |
| LAN users     | `http://node-1:30080`          |
|               | `http://node-2:30080`          |
|               | `http://node-3:30080`          |

(Any of the three works - if one node is down, just use another. NodePort
routes traffic to whichever pod is running.)

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
