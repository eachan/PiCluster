# Deploy guide

The PiCluster repo is the single source of truth for how every node is
configured. To roll out a change you:

1. Edit files in the repo (locally on your workstation or directly on the
   supervisor).
2. Push them to GitHub on the branch the supervisor is tracking (default `main`).
3. SSH into the supervisor and run `piclusterctl deploy`.

`piclusterctl deploy`:

1. `git fetch && git pull --ff-only` on `/opt/picluster`.
2. Runs `ansible-playbook site.yml -i inventory/hosts.yml` with any tags or
   limits you specified.
3. Writes a timestamped entry to `/var/log/picluster-deploy.log`.

Because the playbook is **idempotent**, deploying when nothing has changed is
safe and fast.

## Common deploys

### Push a new website / app

Apps are just Kubernetes manifests. Drop them under `apps/<name>/` (create the
directory) and add a small play that runs `kubectl apply -f` for that
directory. The supervisor's kubeconfig is at
`/home/eachan/.kube/config`.

A minimal example to deploy a website:

```yaml
# ansible/playbooks/apps.yml
- name: Deploy user apps
  hosts: supervisor
  gather_facts: false
  tags: [apps]
  tasks:
    - name: Apply manifests
      ansible.builtin.command: >
        kubectl --kubeconfig /home/{{ ansible_user }}/.kube/config
        apply -f {{ project_root }}/apps/
      register: out
      changed_when: "'configured' in out.stdout or 'created' in out.stdout"
```

Add `- import_playbook: playbooks/apps.yml` to `site.yml`, drop your YAML
under `apps/`, push, then `piclusterctl deploy --tags apps`.

### Change Samba password

1. Edit `ansible/group_vars/all.yml` -> `samba_password`.
2. `piclusterctl deploy --tags samba` (or vault-edit `secret.yml` if you
   moved it there).

### Upgrade K3s

1. Edit `k3s_version` in `group_vars/all.yml`.
2. `piclusterctl deploy --tags cluster` - the play runs `serial: 1` so nodes
   upgrade one at a time, preserving quorum.

### Add or remove a model on the AI node

1. Edit `ollama_models` in `group_vars/all.yml`.
2. `piclusterctl deploy --tags ai`.

## Automated deploys

Setting `auto_deploy_enabled: true` in `group_vars/all.yml` (and re-deploying)
turns on a `picluster-autodeploy.timer` systemd unit that runs
`piclusterctl deploy` every `auto_deploy_interval` (default 10 min). Use this
sparingly - explicit deploys are usually preferable so you can read the diff
first.

## Recovery

If a node has drifted:

```bash
# Drag everything back to the desired state on node-2 only.
piclusterctl deploy --target node-2
```

If you need to redo a single role:

```bash
piclusterctl deploy --tags storage --target cluster
```

If a Pi was reimaged and you need to re-join it: just put the same hostname
back, give it the right credentials, and run `piclusterctl deploy`. The
playbooks will see the missing services and reinstall them.
