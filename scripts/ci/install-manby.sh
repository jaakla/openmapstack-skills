#!/usr/bin/env bash
# Install the reviewed Linux x86_64 manby release at the caller's explicit path.
set -euo pipefail
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo 'This CI installer supports Linux x86_64 only.' >&2
  exit 1
fi
: "${1:?Usage: install-manby.sh /absolute/path/to/manby}"
version=0.2.10
# The Tippecanoe release this manby release ports; install-tippecanoe.sh builds it.
follows=2.82.0
asset="manby-x86_64-unknown-linux-gnu"
sha256=a1bcc488a48ae650171e34045463135a3a33aeb2fcf3eb9dbf6a760c7806f9aa
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
curl --fail --location --retry 3 --connect-timeout 20 --max-time 180 \
  "https://github.com/birkskyum/manby/releases/download/v${version}/${asset}.tar.gz" \
  --output "$stage/archive.tar.gz"
printf '%s  %s\n' "$sha256" "$stage/archive.tar.gz" | sha256sum --check --strict
tar -xzf "$stage/archive.tar.gz" -C "$stage" "$asset/manby"
mkdir -p "$(dirname "$1")"
install -m 0755 "$stage/$asset/manby" "$1"
# Like Tippecanoe, manby prints its version on stderr.
[[ $("$1" --version 2>&1) == "manby $version (tippecanoe v$follows)" ]]
