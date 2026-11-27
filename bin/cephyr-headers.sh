#!/bin/sh
# Provision the one external source tree Cephyr uses at the LibStone pin.
set -eu

die() { printf '%s\n' "$*" >&2; exit 2; }
[ "$#" -eq 2 ] || die "Usage: $0 check|fetch LIBSTONE_ROOT"
case "$1" in check|fetch) ;; *) die "Expected check or fetch" ;; esac
mode=$1
libstone=$(realpath -- "$2")
dest="$libstone/third_party/nlohmann-json"
pin=322063822f66533bb81ef8e938fd07e5f6394917
test -f "$libstone/third_party/valijson/include/valijson/validator.hpp" ||
  die "Missing LibStone's tracked Valijson headers"

if [ "$mode" = fetch ] && [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
  stage=$(mktemp -d "$libstone/third_party/.nlohmann-json.XXXXXXXX")
  trap 'rm -rf -- "$stage"' EXIT
  git -C "$stage" init -q
  git -C "$stage" fetch --depth 1 https://github.com/nlohmann/json.git "$pin"
  git -C "$stage" checkout --detach "$pin"
  # GNU mv -T prevents moving inside a directory created concurrently.
  mv -T --no-clobber -- "$stage" "$dest"
fi

top=$(git -C "$dest" rev-parse --show-toplevel 2>/dev/null) || top=
[ "$top" = "$dest" ] ||
  die "Missing pinned nlohmann-json checkout; run $0 fetch $libstone"
[ "$(git -C "$dest" rev-parse HEAD)" = "$pin" ] ||
  die "Expected nlohmann-json $pin at $dest; existing checkout left unchanged"
[ -z "$(git -C "$dest" status --porcelain --untracked-files=all)" ] ||
  die "Dirty nlohmann-json checkout at $dest"
test -f "$dest/include/nlohmann/json.hpp" || die "Missing nlohmann-json headers"
printf 'nlohmann-json=%s\n' "$pin"
