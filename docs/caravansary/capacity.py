#!/usr/bin/env python3
"""Estimate optimistic acquisition capacity; inputs are assumptions, not measurements."""
import argparse
import json
import math


def positive_float(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a finite positive number")
    return number


def positive_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("properties", "days", "guest-configurations", "stay-lengths"):
        parser.add_argument("--" + name, type=positive_int, required=True)
    parser.add_argument("--cells-per-query", type=positive_float, required=True)
    parser.add_argument("--attempts-per-query", type=positive_float, required=True)
    parser.add_argument("--budget-per-hour", type=positive_float, required=True)
    parser.add_argument("--max-age-hours", type=positive_float, required=True)
    args = parser.parse_args()
    cells = args.properties * args.days * args.guest_configurations * args.stay_lengths
    attempts = cells * args.attempts_per_query / args.cells_per_query
    required = attempts / args.max_age_hours
    print(json.dumps({
        "kind": "caravansary.capacity-estimate@1",
        "scope": "one_provider",
        "cells": cells,
        "estimated_attempts_per_full_pass": attempts,
        "estimated_first_fill_hours": attempts / args.budget_per_hour,
        "required_attempts_per_hour": required,
        "budget_per_hour": args.budget_per_hour,
        "necessary_budget_condition_met": args.budget_per_hour >= required,
        "note": "Optimistic necessary condition only; assumes uniform coverage and excludes additional recovery and scheduling overhead.",
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
