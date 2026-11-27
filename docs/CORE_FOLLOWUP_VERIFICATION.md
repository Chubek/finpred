# Core follow-up verification

## Poindexter GUI: real X11 window smoke test

The [core overhaul verification](CORE_OVERHAUL_VERIFICATION.md) recorded an
explicit skip because Xvfb was unavailable. The follow-up used genuine Xorg
Xvfb on Linux x86-64, without installing host packages or changing plugins or
dependency pins. The checkout was FinPRED
`7f2d13ca59134fa4bb7f8c6804bf9ce685ae733d`, with MuLIB
`cbb7d66f217f188493f25b38c10101aa26469c48`, LibStone
`4e60694e341977ebf39b3344cb5fb3bcb2684af2`, and the same compiler, GrammarEmbed
and schema fingerprints recorded in the core overhaul verification.

The test used the Arch Linux `xorg-server-xvfb-21.1.26-1-x86_64.pkg.tar.zst`
package. Its SHA-256 matched the local Arch `extra` repository metadata:
`67fb3d52b7658bf610449cb83b97a224ea683d7486b612995b4d10ec26a1a9af`.
The detached signature also verified against the packager key from the
installed Arch keyring (fingerprint `ADC8A1FCC15E01D45310419E94657AB20F2A092B`).
Both `Xvfb` and `xvfb-run` were extracted into worktree scratch; `xauth`,
X11 libraries and the build tools were already present.

To reproduce on the same host class, place the verified package in
`build/x11-verify/`, and export `MULIB_ROOT` and `ON1XC` with absolute paths
to the pinned dependencies and compiler. Run from the checkout root in Bash:

```sh
set -euo pipefail
umask 077
scratch="$PWD/build/x11-verify"
package="$scratch/xorg-server-xvfb-21.1.26-1-x86_64.pkg.tar.zst"
printf '%s  %s\n' \
  67fb3d52b7658bf610449cb83b97a224ea683d7486b612995b4d10ec26a1a9af "$package" \
  | sha256sum -c -
mkdir -p "$scratch/root" "$scratch/tmp" "$scratch/home" "$scratch/cache" "$scratch/xdg"
bsdtar -xf "$package" -C "$scratch/root" usr/bin/Xvfb usr/bin/xvfb-run
bwrap --die-with-parent --unshare-net --ro-bind / / --dev /dev --proc /proc \
  --bind "$PWD/build" "$PWD/build" --bind "$scratch/tmp" /tmp --chdir "$PWD" \
  --unsetenv DISPLAY --unsetenv WAYLAND_DISPLAY --unsetenv XAUTHORITY \
  --unsetenv POINDEXTER_EXE --setenv PATH "$scratch/root/usr/bin:/usr/bin:/bin" \
  --setenv HOME "$scratch/home" --setenv XDG_CACHE_HOME "$scratch/cache" \
  --setenv XDG_RUNTIME_DIR "$scratch/xdg" --setenv TMPDIR /tmp \
  --setenv PYTHONDONTWRITEBYTECODE 1 \
  -- make poindexter-gui-test |& tee "$scratch/gui.log"
grep -Fx 'poindexter_gui_x11=passed private_xvfb' "$scratch/gui.log"
```

The explicit marker is required because the target can exit successfully
after skipping X11. Bubblewrap gives the server a private network namespace
and `/tmp`, and keeps source and third-party trees read-only. The existing
legacy MuLIB header view is created in scratch. The traced run confirmed
that the extracted Xvfb started with `-nolisten tcp` and that the test
client connected to its Unix-domain X11 socket.

The consumer opens a real X11 window, presents a worksheet frame, and reads
back the background and selected-cell pixel values with `XGetImage`. The
gate rebuilds the On1x worksheet worker and also checks formula recalculation
and local save behavior separately, without a window. This is not a physical
desktop or window-manager test: the live X11 branch does not exercise keyboard
or pointer delivery, and it does not qualify the full plugin suite or a
non-C11 compiler backend.
