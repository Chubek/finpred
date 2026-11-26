#!/usr/bin/env python3
"""Plan and report on competitor observations or run one approved sandbox probe."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

if __package__:
    from .caravansary_core import booking_pilot, credentials, inputs, scheduler, script
    from .caravansary_core import coverage as coverage_lib
else:
    # Also support a standalone invocation and spec_from_file_location callers.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from caravansary_core import booking_pilot, credentials, inputs, scheduler, script
        from caravansary_core import coverage as coverage_lib
    finally:
        sys.path.pop(0)

parse = script.parse
coverage = coverage_lib.coverage
Scheduler = scheduler.Scheduler
resolve_credentials = credentials.resolve


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _identity(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _input_path(parent, value, allowed_roots):
    requested = parent / value

    def authorize(path):
        if not any(path.is_relative_to(root) for root in allowed_roots):
            raise ValueError("referenced input is outside the host-approved directories")

    authorize(Path(os.path.abspath(requested)))
    path = _resolve(requested, strict=False)
    authorize(path)
    if not path.is_file():
        raise ValueError("referenced input must be a regular file")
    return path


def _resolve(path, *, strict=True):
    try:
        return path.resolve(strict=strict)
    except RuntimeError as exc:
        raise ValueError("cannot resolve path") from exc


def _utc(now):
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be an aware datetime")
    try:
        return now.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("now is outside the supported UTC calendar") from exc


def _rows(config_id, config, start, guests, properties, weights):
    search = config["search"]
    stays = [(days, timedelta(days=days)) for days in search["stay_lengths"]]
    for source in config["sources"]:
        for competitor in properties:
            mapping = competitor["providers"].get(source, {"mapping_status": "missing"})
            reason = {"missing": "mapping_missing", "unverified": "mapping_unverified",
                      "verified": None}[mapping["mapping_status"]]
            for offset in range(search["horizon_days"]):
                checkin = start + timedelta(days=offset)
                checkin_text = checkin.isoformat()
                checkouts = [(stay, (checkin + duration).isoformat()) for stay, duration in stays]
                for guest_id in search["guest_configurations"]:
                    guest = guests[guest_id]
                    for stay, checkout_text in checkouts:
                        context = {
                            "source": source,
                            "checkin": checkin_text,
                            "checkout": checkout_text,
                            "guest_configuration": guest,
                            "booker_country": search["booker_country"],
                            "locale": search["locale"],
                            "currency": config["property"]["currency"],
                        }
                        cell_key = _identity([config_id, source, competitor["id"],
                                              checkin_text, checkout_text, guest_id])
                        yield {
                            "cell_key": cell_key,
                            "config_id": config_id,
                            "source": source,
                            "competitor_id": competitor["id"],
                            "checkin": checkin_text,
                            "checkout": checkout_text,
                            "guest_configuration": guest,
                            "stay_length": stay,
                            "request_context": context,
                            "provider_property_id": mapping.get("provider_property_id"),
                            "provider_url": mapping.get("url"),
                            "status": "pending" if reason is None else "unsupported",
                            "reason": reason,
                            "weight": weights[guest_id, stay],
                        }


def load_plan(path, on_date=None, *, now=None, input_roots=()):
    """Validate all inputs, returning (script config, iterator of initial rows).

    on_date supplies the property's civil date for ``today`` only. Additional
    input roots are grants made by the caller, not by CaravanScript. The
    returned dictionaries are read-only by convention; callers should not
    mutate them, including nested guest objects shared by the iterator.
    """
    instant = _utc(now)
    if on_date is not None and type(on_date) is not date:
        raise ValueError("on_date must be a civil date")
    # Resolve inputs relative to the path used to select the script. If that
    # script itself is a symlink, it does not grant access to the target's directory.
    path = Path(path)
    parent = _resolve(path.absolute().parent)
    roots = (parent, *(_resolve(Path(root)) for root in input_roots))
    if not all(root.is_dir() for root in roots):
        raise ValueError("host-approved input roots must be directories")
    if not path.is_file():
        raise ValueError("script must be a regular file")
    config = parse(path.read_text(encoding="utf-8"))
    search = config["search"]
    guest_ids = search["guest_configurations"]
    stays = search["stay_lengths"]
    guests, properties = inputs.load_competitors(_input_path(parent, config["competitors"], roots))
    weights = inputs.load_weights(_input_path(parent, config["refresh"]["weights"], roots),
                                  guest_ids, stays)
    for guest_id in guest_ids:
        if guest_id not in guests:
            raise ValueError(f"undefined guest configuration: {guest_id!r}")
    if search["start"] == "today":
        try:
            start = on_date or instant.astimezone(ZoneInfo(config["property"]["timezone"])).date()
        except OverflowError as exc:
            raise ValueError("now is outside the property's supported local calendar") from exc
    else:
        start = date.fromisoformat(search["start"])
    if start.toordinal() + search["horizon_days"] - 1 + max(stays) > date.max.toordinal():
        raise ValueError("checkout exceeds the supported Gregorian calendar")

    # Bind acquisition semantics, not report transformations, disk paths,
    # queue policy or a rolling local date. Each row separately binds its
    # exact check-in and checkout.
    selected = sorted(config["sources"])
    config_id = _identity({
        "kind": "caravansary.config@1",
        "name": config.get("name"),
        # Preserve existing acquisition digests; not a CaravanScript field.
        "version": 1,
        "property": config["property"],
        "search": {**search, "guest_configurations": sorted(guest_ids), "stay_lengths": sorted(stays)},
        "sources": selected,
        "guest_configurations": {key: guests[key] for key in guest_ids},
        "mappings": {
            prop["id"]: {source: prop["providers"].get(source, {"mapping_status": "missing"})
                         for source in selected}
            for prop in properties
        },
    })
    return config, _rows(config_id, config, start, guests, properties, weights)


def plan(path, on_date=None, *, now=None, input_roots=()):
    """Return validated, deterministic initial rows without collecting anything."""
    return load_plan(path, on_date, now=now, input_roots=input_roots)[1]


def _apply_transform(config, report):
    """Attach optional metrics without modifying the host's base report."""
    if "transform" not in config:
        return report
    if __package__:
        from .caravansary_core import transform_check, transform_eval
    else:
        # Load siblings the same way as the standalone entry point does.
        from caravansary_core import transform_check, transform_eval

    ast = config["transform"]
    metrics = transform_eval.evaluate(transform_check.compile_transform(ast), report)
    return {
        **report,
        "transformation": {
            "kind": "caravansary.transformation@1",
            "program_digest": _identity(ast),
            "base_report_digest": _identity(report),
            "metrics": metrics,
        },
    }


def _observations(path):
    if not Path(path).is_file():
        raise ValueError("observation log must be a regular file")
    with open(path, encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            try:
                record = inputs.parse_json(line)
            except ValueError as exc:
                raise ValueError(f"observation log line {line_no}: {exc}") from exc
            yield record


def _civil_arg(text):
    try:
        result = date.fromisoformat(text)
        if text == result.isoformat():
            return result
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected a Gregorian date in YYYY-MM-DD form")


def _utc_arg(text):
    stamp = re.fullmatch(
        r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
        r"(?:\.([0-9]{1,6}))?(?:Z|\+00:00)", text,
    )
    if stamp:
        try:
            seconds, fraction = stamp.groups()
            return datetime.fromisoformat(f"{seconds}.{(fraction or '').ljust(6, '0')}+00:00")
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("expected a UTC timestamp such as 2026-11-26T12:00:00Z")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("plan", "emit initial matrix cells as JSON Lines"),
                            ("report", "emit a coverage report as JSON"),
                            ("pilot-booking", "perform one authorized Booking Demand API sandbox search")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("script", type=Path)
        command.add_argument("--date", type=_civil_arg, help="override the local civil date for 'today'")
        if name != "pilot-booking":
            command.add_argument("--as-of", type=_utc_arg, help="use a fixed UTC clock")
        command.add_argument("--input-root", type=Path, action="append", default=[],
                             help="allow referenced inputs under this additional directory (repeatable)")
    commands.choices["report"].add_argument("--observations", type=Path,
                                           help="host-selected offline observation JSONL for this matrix")
    commands.choices["pilot-booking"].add_argument(
        "--confirm-authorized", action="store_true",
        help="confirm that your partner account permits this one sandbox API request",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "pilot-booking" and not args.confirm_authorized:
            raise ValueError("pilot-booking requires --confirm-authorized before a sandbox request")
        now = _utc(getattr(args, "as_of", None))
        config, rows = load_plan(args.script, args.date, now=now, input_roots=args.input_root)
        if args.command == "plan":
            for row in rows:
                print(_json(row))
        elif args.command == "pilot-booking":
            cells = list(islice(rows, 2))
            if len(cells) != 1:
                raise ValueError("pilot-booking requires a script with exactly one matrix cell")
            today = now.astimezone(ZoneInfo(config["property"]["timezone"])).date()
            names = (booking_pilot.API_TOKEN, booking_pilot.AFFILIATE_ID)
            environ = {name: os.environ.get(name) for name in names}
            result = booking_pilot.run_sandbox(cells[0], today=today, environ=environ)
            print(_json(result))
            return int(result["outcome"] == "failed")
        else:
            rows = list(rows)
            refresh = config["refresh"]
            capacity = Scheduler(refresh, config["sources"]).capacity(rows)
            observations = _observations(args.observations) if args.observations else ()
            report = coverage(rows, observations, now=now,
                              max_age_seconds=refresh["max_age_seconds"], capacity=capacity)
            print(_json(_apply_transform(config, report)))
    except (OSError, ValueError, RecursionError) as exc:
        print(f"caravansary: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
