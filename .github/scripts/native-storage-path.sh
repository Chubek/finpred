#!/usr/bin/env bash
set -euo pipefail

# CTest runs the native consumer with its build directory as cwd. Its Python
# harness makes stores there, not in TMPDIR. Match native/store.c's allowlist.
case "$(stat -f -c %t "$RUNNER_TEMP")" in
  ef53|9123683e|58465342)
    out="$RUNNER_TEMP/finpred-native-build"
    ;;
  *)
    mount="$RUNNER_TEMP/finpred-native-fs"
    image="$RUNNER_TEMP/finpred-native.ext4"
    mkdir "$mount"
    truncate -s 128M "$image"
    mkfs.ext4 -q -F "$image"
    sudo mount -o loop "$image" "$mount"
    sudo chown "$(id -u):$(id -g)" "$mount"
    out="$mount/build"
    ;;
esac
mkdir "$out"
stat -f -c 'native store filesystem: %T (%t)' "$out"
echo "NATIVE_BUILD_DIR=$out" >> "$GITHUB_ENV"
