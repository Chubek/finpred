#!/usr/bin/env python3
"""Executable native API check against an independent rational model (test only)."""

import ctypes as C
from fractions import Fraction as Q
import math
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LIMIT = 10**12
ERROR, OK, INSUFFICIENT = range(3)


class Config(C.Structure):
    _fields_ = [(key, C.c_double) for key in ("alpha", "beta", "gamma", "phi")]


class Prediction(C.Structure):
    _fields_ = [(key, C.c_double) for key in ("point", "level", "trend", "seasonal")] + [
        ("candidate_index", C.c_size_t), ("selection_count", C.c_size_t),
        ("selection_absolute_error_sum", C.c_double),
    ]


class Fold(C.Structure):
    _fields_ = [("target", C.c_size_t), ("training_count", C.c_size_t), ("actual", C.c_int64),
                ("has_point", C.c_int), ("prediction", Prediction)]


class Metrics(C.Structure):
    _fields_ = [("point_count", C.c_size_t), ("absolute_error_sum", C.c_double)]


class HistPrice(C.Structure):
    _fields_ = [("point", C.c_double), ("variance", C.c_double)]


def bind(lib):
    lib.finpred_hw_predict.restype = C.c_int
    common = [C.POINTER(C.c_int64), C.c_size_t, C.c_size_t, C.c_size_t,
              C.POINTER(Config), C.c_size_t]
    lib.finpred_hw_predict.argtypes = common + [C.POINTER(Prediction)]
    lib.finpred_hw_evaluate.restype = C.c_int
    lib.finpred_hw_evaluate.argtypes = common + [
        C.c_size_t, C.POINTER(Fold), C.c_size_t, C.POINTER(Metrics)]
    lib.mulib_histprice_seasonal.argtypes = [
        C.POINTER(C.c_double), C.c_size_t, C.c_size_t, C.c_double, C.c_double, C.c_double,
        C.c_size_t, C.POINTER(HistPrice)]
    lib.mulib_histprice_seasonal.restype = C.c_int
    return lib


def args(samples, horizon, season, grid):
    return ((C.c_int64 * len(samples))(*samples), len(samples), horizon, season,
            (Config * len(grid))(*(Config(*c) for c in grid)), len(grid))


def predict(lib, samples, horizon, season, grid):
    p = Prediction(12, 23, 34, 45, 56, 67, 78)
    saved = bytes(p)
    status = lib.finpred_hw_predict(*args(samples, horizon, season, grid), C.byref(p))
    if status != OK:
        assert bytes(p) == saved
    return status, p


def evaluate(lib, samples, horizon, season, grid, first=0):
    folds = (Fold * (len(samples) - first))()
    metrics = Metrics()
    assert lib.finpred_hw_evaluate(*args(samples, horizon, season, grid), first, folds,
                                   len(folds), C.byref(metrics))
    return list(folds), metrics


def rational_fit(xs, h, s, config):
    """Batch refit using weighted averages and a closed-form damping sum."""
    a, b, g, phi = map(Q, config)
    base = Q(sum(xs[:s]), s)
    slope = Q(sum(xs[s:2*s]), s*s) - base / s
    # Starting line passes through the first cycle's mean at its midpoint.
    intercept = base - slope * Q(s - 1, 2)
    phases = [Q(xs[j] + xs[s + j], 2) - (intercept + slope * (j + Q(s, 2))) for j in range(s)]
    level = intercept + (2*s - 1) * slope
    for i, y in enumerate(xs[2*s:], 2*s):
        j = i % s
        previous = level
        level = a * (y - phases[j]) + (1-a) * (previous + phi * slope)
        slope = b * (level - previous) + (1-b) * phi * slope
        phases[j] = g * (y - level) + (1-g) * phases[j]
    phase = phases[(len(xs) - 1 + h) % s]
    drift = h if phi == 1 else phi * (1 - phi**h) / (1 - phi)
    return level + drift * slope + phase, level, slope, phase


def inner_oracle(xs, h, s, grid):
    # Fit each origin independently; never compute a residual without its actual.
    start = 2*s + h - 1
    losses = [
        sum(abs(Q(float(rational_fit(xs[:t-h+1], h, s, c)[0])) - xs[t])
            for t in range(start, len(xs)))
        for c in grid
    ]
    count = max(0, len(xs) - start)
    if len(xs) < 2*s or (len(grid) > 1 and count < 3):
        return None
    winner = min(range(len(grid)), key=lambda i: losses[i])
    return *rational_fit(xs, h, s, grid[winner]), winner, count, losses[winner]


def close(actual, expected):
    assert math.isclose(actual, float(expected), rel_tol=2e-14, abs_tol=2e-11), (actual, expected)


def check_prediction(p, expected):
    for key, value in zip(("point", "level", "trend", "seasonal"), expected):
        close(getattr(p, key), value)
    assert (p.candidate_index, p.selection_count) == expected[4:6]
    close(p.selection_absolute_error_sum, expected[6])


def check_folds(lib, xs, h, s, grid, first=0):
    folds, metrics = evaluate(lib, xs, h, s, grid, first)
    errors, winners = [], set()
    for t, row in enumerate(folds, first):
        n = max(0, t - h + 1)
        assert (row.target, row.training_count, row.actual) == (t, n, xs[t])
        expected = inner_oracle(xs[:n], h, s, grid)
        assert row.has_point == int(expected is not None)
        if not row.has_point:
            assert bytes(row.prediction) == bytes(Prediction())
            continue
        check_prediction(row.prediction, expected)
        status, live = predict(lib, xs[:n], h, s, grid)
        assert status == OK and bytes(live) == bytes(row.prediction)
        errors.append(abs(float(expected[0]) - xs[t]))
        winners.add(row.prediction.candidate_index)
    assert metrics.point_count == len(errors)
    close(metrics.absolute_error_sum, math.fsum(errors))
    return winners


def test_upstream(lib):
    # Check the upstream executable, not the discovered foreign header alone.
    # On pure positive periodic data the compatible undamped case agrees;
    # the pinned HistPrice entry then rejects the shifted signed input.
    xs = [50, 40, 60] * 5
    grid = [(0.5, 0.25, 0.75, 1)]
    upstream = HistPrice()
    for offset in (0, -100):
        samples = [v + offset for v in xs]
        c_double_samples = (C.c_double * len(xs))(*samples)
        assert lib.mulib_histprice_seasonal(c_double_samples, len(xs), 3, *grid[0][:3], 7,
                                            C.byref(upstream)) == int(offset == 0)
        status, p = predict(lib, samples, 7, 3, grid)
        assert status == OK and p.point == 50 + offset
        if offset == 0:
            assert upstream.point == p.point


def test_model(lib):
    for season, n, step in [(2, 4, 7), (5, 23, -11), (128, 256, -3)]:
        xs = [-300 + step*i + (i % season)**2 for i in range(n)]
        for h in (1, 12, 365):
            for phi in (1, 0.75, math.nextafter(1., 0.)):
                grid = [(0.25, 0.5, 0.75, phi)]
                status, p = predict(lib, xs, h, season, grid)
                assert status == OK
                for actual, exact in zip((p.point, p.level, p.trend, p.seasonal),
                                         rational_fit(xs, h, season, grid[0])):
                    if phi == 1:
                        # Exact affine trend with phase offsets, including partial seasons.
                        t = n - 1 + h
                        assert p.point == -300 + step*t + (t % season)**2
                    close(actual, exact)
        assert predict(lib, xs[:2*season-1], 1, season, grid)[0] == INSUFFICIENT

    xs = [LIMIT, -LIMIT] * 128
    grid = [(1, 1, 1, 0.5)]
    for h in (1, 365):
        status, p = predict(lib, xs, h, 2, grid)
        assert status == OK
        check_prediction(p, (*rational_fit(xs, h, 2, grid[0]), 0, max(0, 256-(4+h-1)), 0))


def test_selection(lib):
    rng = random.Random(10301)
    xs = [i*2 + [12, -14, -1][i % 3] + rng.randrange(-5, 6) + (55 if 17 <= i < 22 else 0)
          for i in range(35)]
    grid = [(0.25, 0.5, 0.5, 1), (0.75, 0.25, 0.5, 0.75), (0.5, 0.5, 0, 0.5)]
    winners = check_folds(lib, xs, 4, 3, grid, 1)
    assert len(winners) > 1  # Not merely a constant winner or the first-listed candidate.
    check_folds(lib, xs[:19], 6, 2, grid[:1], 5)

    # An inner forecast may have been made already but cannot be scored until
    # its actual arrives. Mutating the gap and target must not change a fold.
    horizon, season, target = 4, 3, 22
    train = target - horizon + 1
    pristine, _ = evaluate(lib, xs, horizon, season, grid, target)
    changed, _ = evaluate(lib, xs[:train] + [LIMIT] * (len(xs)-train), horizon, season, grid, target)
    assert pristine[0].actual != changed[0].actual and pristine[0].has_point == changed[0].has_point == 1
    assert bytes(pristine[0].prediction) == bytes(changed[0].prediction)
    assert predict(lib, xs[:11], 4, 3, grid)[0] == INSUFFICIENT
    status, first = predict(lib, xs[:12], 4, 3, grid)
    assert status == OK and first.selection_count == 3

    # Exercise full grid capacity and exact deterministic ties.
    rows, totals = evaluate(lib, [-17] * 256, 5, 2, grid[:1] * 16)
    assert rows[14].has_point == 0 and rows[15].has_point == 1
    assert totals.point_count == 241 and totals.absolute_error_sum == 0
    for row in rows[15:]:
        assert row.prediction.candidate_index == 0 and row.prediction.point == -17
    rows, totals = evaluate(lib, xs, 365, 3, grid)
    assert all(not row.has_point and row.training_count == 0 for row in rows)
    assert totals.point_count == 0 and totals.absolute_error_sum == 0


def test_errors(lib):
    grid = [(0.5, 0.5, 0.5, 0.5)]
    bad_args = [([], 1, 2, grid), ([0] * 257, 1, 2, grid), ([0, 0, LIMIT+1], 1, 2, grid),
                ([0, 0, -LIMIT-1], 1, 2, grid), ([0] * 8, 0, 2, grid),
                ([0] * 8, 366, 2, grid), ([0] * 8, 1, 1, grid), ([0] * 8, 1, 129, grid),
                ([0] * 8, 1, 2, []), ([0] * 8, 1, 2, grid * 17)]
    for i, v in [(0, math.nan), (1, math.inf), (2, -0.25), (3, 0), (3, 1.25)]:
        bad = list(grid[0])
        bad[i] = v
        bad_args.append(([0] * 8, 1, 2, [grid[0], bad]))
    # Valid gains, but divergent state on this adversarial signed sequence.
    adverse = [-LIMIT]*12 + [LIMIT]*12 + [LIMIT, -LIMIT]*116
    unstable = [(0.25, 1, 1, 1)]
    assert predict(lib, adverse[:150], 1, 12, unstable)[0] == OK
    assert predict(lib, adverse, 1, 12, grid)[0] == OK
    bad_args.append((adverse, 1, 12, grid + unstable))
    for bad in bad_args:
        assert predict(lib, *bad)[0] == ERROR

    folds = (Fold * 256)(Fold(123), Fold(456))
    metrics = Metrics(32, 17)
    saved = bytes(folds), bytes(metrics)
    for parameters, first, capacity in [
        (args(adverse, 1, 12, grid+unstable), 0, 256),
        (args(adverse, 1, 12, grid), 0, 255),
        (args(adverse, 1, 12, grid), 256, 256),
        (args([0, -LIMIT-1], 1, 2, grid), 0, 256),
    ]:
        assert not lib.finpred_hw_evaluate(*parameters, first, folds, capacity, C.byref(metrics))
        assert saved == (bytes(folds), bytes(metrics))
    assert lib.finpred_hw_predict(None, 4, 1, 2, None, 1, None) == ERROR


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib"))
    assert (mulib / "kernels/mulib-histprice.h").is_file(), f"MuLIB kernels missing at {mulib}"
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="holt-winters-", dir=scratch) as directory:
        library = Path(directory) / "forecast.so"
        subprocess.run([
            *shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2", "-Wall", "-Wextra",
            "-Wpedantic", "-Werror", "-shared", "-fPIC",
            *shlex.split(os.environ.get("SERIES_CFLAGS", "")), "-I", mulib / "kernels",
            ROOT / "source/algorithms/holt_winters.c", "-x", "c", "-", "-lm", "-o", library,
        ], input=b'#define MULIB_IMPL_STATSPROC\n#define MULIB_IMPL_HISTPRICE\n'
                 b'#include <mulib-histprice.h>\n', check=True)
        lib = bind(C.CDLL(str(library)))
        test_upstream(lib)
        test_model(lib)
        test_selection(lib)
        test_errors(lib)
    print("core_holt_winters_forecast_ok=true")


if __name__ == "__main__":
    main()
