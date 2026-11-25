#!/usr/bin/env bash
# Build the reviewed Tippecanoe reference (tippecanoe, tile-join) into the
# caller's explicit directory. Needs a C++ toolchain plus SQLite and zlib
# headers; the CI job installs them.
set -euo pipefail
: "${1:?Usage: install-tippecanoe.sh /absolute/path/to/bin-directory}"
version=2.82.0
# Upstream did not tag 2.82.0. This commit sets VERSION "v2.82.0" in version.hpp;
# the content-addressed commit pins the source.
commit=4f2621186acfec33b63ddf636f665623c0fef2dd
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
git -C "$stage" init -q
git -C "$stage" fetch -q --depth 1 https://github.com/felt/tippecanoe "$commit"
git -C "$stage" checkout -q FETCH_HEAD
[[ $(git -C "$stage" rev-parse HEAD) == "$commit" ]]
make -C "$stage" -j"$(nproc)" tippecanoe tile-join
mkdir -p "$1"
install -m 0755 "$stage/tippecanoe" "$stage/tile-join" "$1/"
[[ $("$1/tippecanoe" --version 2>&1) == "tippecanoe v$version" ]]
