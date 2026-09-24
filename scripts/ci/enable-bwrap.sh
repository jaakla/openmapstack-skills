#!/usr/bin/env bash
# Enable the rootless Bubblewrap sandbox that live agents and their tests use
# (evals/adapters/isolation.py). Ubuntu 24.04 restricts unprivileged user
# namespaces through AppArmor by default.
set -euo pipefail
sudo apt-get install -y bubblewrap
if sudo sysctl -n kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
fi
bwrap --unshare-user --ro-bind / / true
