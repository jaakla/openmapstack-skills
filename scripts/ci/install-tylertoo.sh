#!/usr/bin/env bash
# Install the reviewed Linux x86_64 release at the caller's explicit path.
set -euo pipefail
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo 'This CI installer supports Linux x86_64 only.' >&2
  exit 1
fi
: "${1:?Usage: install-tylertoo.sh /absolute/path/to/tylertoo}"
version=0.8.0
asset="tylertoo-${version}-x86_64-unknown-linux-gnu"
sha256=d70592996bf59571842ae29e81780e6186b2f89b36e81dfaae1de7949fa52da6
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
curl --fail --location --retry 3 --connect-timeout 20 --max-time 180 \
  "https://github.com/geoparquet-io/tylertoo/releases/download/v${version}/${asset}.tar.gz" \
  --output "$stage/archive.tar.gz"
printf '%s  %s\n' "$sha256" "$stage/archive.tar.gz" | sha256sum --check --strict
tar -xzf "$stage/archive.tar.gz" -C "$stage" "$asset/tylertoo"
mkdir -p "$(dirname "$1")"
install -m 0755 "$stage/$asset/tylertoo" "$1"
[[ $("$1" --version) == "tylertoo $version" ]]
