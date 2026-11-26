# Reopen a recurring offline job

Build Caravansary and choose a disposable, trusted parent directory. The
state directory must not already exist. The example uses injected clocks,
a fictional source, and a child that verifies the registered source's
integrity. It sends no provider requests.

```sh
make caravansary
parent=$(mktemp -d)
state="$parent/state"
jobs() { bin/caravansary jobs --state "$state" "$@"; }
jobs init
jobs source-add frozen-hotel < plugins/caravansary/examples/jobs/frozen-source.json
jobs profile-add check-frozen frozen-hotel
jobs schedule check-frozen --at 2026-12-01T00:00:00Z --every 60
jobs next
jobs dispatch --at 2026-12-01T00:01:00Z
jobs next
```

Each command reopens the same private state. `next` after successful
dispatch reports the next minute, not a second run of the previous deadline.
Use the ID returned when scheduling to cancel a pending job.

## Schedule a frozen Probe scrape

In a freshly initialized state, register the existing fictional script and
its Booking profile capture. The manifest binds their registered keys to the
exact bytes, and fixes the source alias, URL, capture time and replay clock.

```sh
examples=plugins/caravansary/examples
script="$examples/workflows/canal-market.caf"
capture="$examples/providers/booking-profile.html"
jobs source-add CanalScript < "$script"
jobs source-add CanalProfile < "$capture"
script_sha=$(sha256sum < "$script" | cut -d' ' -f1)
capture_sha=$(sha256sum < "$capture" | cut -d' ' -f1)
jobs source-add CanalManifest <<EOF
CVSCRAPE1
booking_profile booking-profile booking https://booking.example/fixtures/profile 2026-11-26T09:50:00Z 2026-11-26T10:00:00Z
CanalScript $script_sha
CanalProfile $capture_sha
EOF
jobs market-profile-add CanalScrape CanalManifest
jobs schedule CanalScrape --at 2026-11-26T10:01:00Z --once 2026-11-26T10:01:01Z
jobs dispatch --at 2026-11-26T10:01:01Z
jobs result-show 1 2026-11-26T10:01:01Z
```

Use the scheduled ID in `result-show` if the state already contained other
jobs. Persisting the result is distinct from a child exiting successfully.
An uncertain commit must be inspected rather than rerun blindly.
