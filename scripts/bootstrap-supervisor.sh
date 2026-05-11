#!/usr/bin/env bash
# bootstrap-supervisor.sh
#
# First-time setup script for the PiCluster *supervisor* node.
# Run this once on a fresh Pi 4 supervisor (as user `eachan`):
#
#     curl -fsSL https://raw.githubusercontent.com/<your-user>/PiCluster/main/scripts/bootstrap-supervisor.sh | bash
#
# or, with a local checkout:
#
#     ./scripts/bootstrap-supervisor.sh
#
# It will:
#   1. Install OS prerequisites (git, python3, ansible, sshpass)
#   2. Clone (or pull) PiCluster into /opt/picluster
#   3. Symlink /usr/local/bin/piclusterctl
#   4. Run `piclusterctl deploy` against every host
#
# Configure the REPO and BRANCH below or via environment variables.

set -euo pipefail

REPO="${PICLUSTER_REPO:-https://github.com/CHANGEME/PiCluster.git}"
BRANCH="${PICLUSTER_BRANCH:-main}"
ROOT="${PICLUSTER_ROOT:-/opt/picluster}"

GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; DIM="\033[2m"; RESET="\033[0m"
log()  { printf "${GREEN}==>${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
fail() { printf "${RED}[error]${RESET} %s\n" "$*" >&2; exit 1; }

if [[ "${EUID}" -eq 0 ]]; then
  fail "Run this as the regular user (eachan), not root. sudo will be requested as needed."
fi

if ! command -v sudo >/dev/null 2>&1; then
  fail "sudo is required"
fi

log "Updating APT package list"
sudo apt-get update -y

log "Installing prerequisites"
sudo apt-get install -y \
  git \
  python3 \
  python3-pip \
  python3-venv \
  ansible \
  sshpass \
  rsync \
  curl \
  ca-certificates

log "Installing ansible collections"
sudo ansible-galaxy collection install --upgrade community.general ansible.posix || true

log "Preparing ${ROOT}"
sudo mkdir -p "${ROOT}"
sudo chown -R "${USER}:${USER}" "${ROOT}"

if [[ -d "${ROOT}/.git" ]]; then
  log "Repo already present - pulling latest"
  git -C "${ROOT}" fetch --all
  git -C "${ROOT}" checkout "${BRANCH}"
  git -C "${ROOT}" pull --ff-only
else
  log "Cloning ${REPO} (${BRANCH}) into ${ROOT}"
  git clone --branch "${BRANCH}" "${REPO}" "${ROOT}"
fi

log "Linking piclusterctl into /usr/local/bin"
sudo ln -sf "${ROOT}/deploy/piclusterctl" /usr/local/bin/piclusterctl
sudo chmod 0755 "${ROOT}/deploy/piclusterctl"

log "Preparing deploy log"
sudo touch /var/log/picluster-deploy.log
sudo chown "${USER}:${USER}" /var/log/picluster-deploy.log

# First-run SSH key check - encourage but don't require key auth.
if [[ ! -f "${HOME}/.ssh/id_ed25519" && ! -f "${HOME}/.ssh/id_rsa" ]]; then
  warn "No SSH key found in ~/.ssh - generating one (no passphrase) so Ansible can"
  warn "distribute it to the nodes. You can re-key later."
  ssh-keygen -t ed25519 -N "" -f "${HOME}/.ssh/id_ed25519" -C "picluster-supervisor"
fi

cat <<EOF

${GREEN}Bootstrap complete.${RESET}

Next steps:
  1. (optional) Copy your SSH key to the cluster:
       for h in node-1 node-2 node-3 ai supervisor; do
         ssh-copy-id eachan@\$h
       done
  2. Run the full deploy:
       piclusterctl deploy

  The dashboard will be at  http://supervisor/
  Grafana is at             http://supervisor:3000/
  Prometheus is at          http://supervisor:9090/

EOF
