#!/usr/bin/env python3
"""Build the native series API against pinned MuLIB and compare to rational arithmetic."""
import ctypes as C
from fractions import Fraction
from math import ceil
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 10**12
I64 = C.c_int64
SIZE = C.c_size_t


class Prediction(C.Structure):
    _fields_ = [("point", I64), ("lower", I64), ("upper", I64),
                ("calibration_count", SIZE), ("has_interval", C.c_int)]


class Fold(C.Structure):
    _fields_ = [("target", SIZE), ("training_count", SIZE), ("actual", I64),
                ("has_point", C.c_int), ("prediction", Prediction)]


class Metrics(C.Structure):
    _fields_ = [("point_count", SIZE), ("interval_count", SIZE), ("covered_count", SIZE),
                ("absolute_error_sum", I64), ("interval_width_sum", I64), ("interval_score_sum", I64)]


def median(values):
    values = sorted(values)
    size = len(values)
    return (values[(size - 1) // 2] + values[size // 2]) / 2


def oracle_point(values, train, target, season):
    xy = [(index, Fraction(value)) for index, value in enumerate(values[:train])
          if (target - index) % season == 0][-24:]
    if len(xy) < 3:
        return None
    # Use raw indices and exact rational slopes; no native keys or cycle rebasing.
    slope = median((yj - yi) / (xj - xi) for j, (xj, yj) in enumerate(xy)
                   for xi, yi in xy[:j])
    forecast = median(y + slope * (target - x) for x, y in xy)
    rounded = abs(forecast) + Fraction(1, 2)
    return (1 if forecast >= 0 else -1) * (rounded.numerator // rounded.denominator)


def oracle_case(values, horizon, season, coverage, first):
    points = [oracle_point(values, max(0, t - horizon + 1), t, season)
              for t in range(len(values))]
    points.append(oracle_point(values, len(values), len(values) - 1 + horizon, season))
    metrics = [0] * 6
    rows = []
    future = None
    for target in range(first, len(values) + 1):
        train = len(values) if target == len(values) else max(0, target - horizon + 1)
        point = points[target]
        errors = sorted(abs(values[t] - points[t]) for t in range(train) if points[t] is not None)
        rank = ceil(Fraction((len(errors) + 1) * coverage, 100))
        bounds = None
        if point is not None and rank <= len(errors):
            radius = errors[rank - 1]
            bounds = point - radius, point + radius
        prediction = None if point is None else (point, len(errors), bounds)
        if target == len(values):
            future = prediction
            break
        actual = values[target]
        rows.append((target, train, actual, prediction))
        if prediction is not None:
            metrics[0] += 1
            metrics[3] += abs(point - actual)
        if bounds is not None:
            lower, upper = bounds
            metrics[1] += 1
            metrics[2] += lower <= actual <= upper
            metrics[4] += upper - lower
            metrics[5] += upper - lower + 200 * max(lower - actual, actual - upper, 0) // (100 - coverage)
    return rows, metrics, future


def canonical(prediction):
    bounds = (prediction.lower, prediction.upper) if prediction.has_interval else None
    if bounds is None:
        assert (prediction.lower, prediction.upper) == (0, 0)
    return prediction.point, prediction.calibration_count, bounds


class Native:
    def __init__(self, library):
        self.predict = library.finpred_series_predict
        self.predict.argtypes = [C.POINTER(I64), SIZE, SIZE, SIZE, C.c_uint, C.POINTER(Prediction)]
        self.predict.restype = C.c_int
        self.evaluate = library.finpred_series_evaluate
        self.evaluate.argtypes = [C.POINTER(I64), SIZE, SIZE, SIZE, C.c_uint, SIZE,
                                  C.POINTER(Fold), SIZE, C.POINTER(Metrics)]
        self.evaluate.restype = C.c_int

    def run(self, values, horizon, season, coverage, first):
        observations = (I64 * len(values))(*values)
        folds = (Fold * (len(values) - first))()
        metrics = Metrics()
        assert self.evaluate(observations, len(values), horizon, season, coverage, first,
                             folds, len(folds), C.byref(metrics)) == 1
        rows = []
        for fold in folds:
            prediction = canonical(fold.prediction)
            if not fold.has_point:
                assert prediction == (0, 0, None), prediction
                prediction = None
            rows.append((fold.target, fold.training_count, fold.actual, prediction))

        future = Prediction(-7, -2, 2, 88, 1)
        original = bytes(future)
        status = self.predict(observations, len(values), horizon, season, coverage, C.byref(future))
        if status == 2:
            assert bytes(future) == original
            future = None
        else:
            assert status == 1
            future = canonical(future)
        return rows, [getattr(metrics, name) for name, _ in Metrics._fields_], future

    def compare(self, values, horizon=1, season=1, coverage=90, first=0):
        result = self.run(values, horizon, season, coverage, first)
        reference = oracle_case(values, horizon, season, coverage, first)
        assert result == reference, (horizon, season, coverage, first, result, reference)
        return result


def test(native):
    assert native.compare([0, 1, 1])[2] == (2, 0, None)
    assert native.compare([0, -1, -1])[2] == (-2, 0, None)
    assert native.compare([-LIMIT, 0, LIMIT], 365)[2] == (366 * LIMIT, 0, None)
    assert native.compare([LIMIT], 365, 256)[2] is None
    constant = [8] * 23
    for coverage, need in ((80, 4), (90, 9), (95, 19)):
        assert native.compare(constant[:need + 2], coverage=coverage)[2] == (8, need - 1, None)
        assert native.compare(constant[:need + 3], coverage=coverage)[2] == (8, need, (8, 8))
    rows, metrics, future = native.compare([8] * 7 + [21], coverage=80, first=7)
    assert rows == [(7, 7, 21, (8, 4, (8, 8)))]
    assert metrics == [1, 1, 0, 13, 0, 130]
    assert future == (8, 5, (-5, 21))

    seasonal = [110, -25, 7]
    values = [seasonal[t % 3] + t * 2 for t in range(53)]
    values[30] = LIMIT
    _, _, next_point = native.compare(values, horizon=5, season=3, first=14)
    assert next_point[0] == seasonal[57 % 3] + 57 * 2
    # For target 35, the first unseen index is 31: even matured-looking residuals
    # indexed 31..34 must not calibrate the interval, and 35 is the target itself.
    target = 35
    earlier, _, _ = native.compare(values, horizon=5, season=3)
    changed = [value if t < 31 else value + 1000 for t, value in enumerate(values)]
    later, _, _ = native.compare(changed, horizon=5, season=3)
    assert earlier[target][2] != later[target][2]
    assert earlier[target][3] == later[target][3]
    assert earlier[target][3][2] is not None
    assert any(earlier[t][3] != later[t][3] for t in range(target + 1, len(values)))
    prefix = native.compare(values[:31], horizon=5, season=3)[2]
    assert earlier[target][3] == prefix

    alternating = [(-1) ** t * (LIMIT - 973 * t) for t in range(256)]
    native.compare(alternating, horizon=19, season=2, coverage=95, first=172)
    # A changed old same-phase sample falls outside the latest-24 fit window.
    assert native.compare(alternating, horizon=365, season=1)[2][0] == native.compare(
        [value // 23 for value in alternating[:232]] + alternating[232:], horizon=365, season=1
    )[2][0]
    rng = random.Random(0xF149)
    for _ in range(22):
        size = rng.randrange(15, 54)
        step = rng.randrange(1, 10)
        native.compare([rng.choice((-LIMIT, LIMIT, rng.randrange(-999, 999))) for _ in range(size)],
                       step, rng.randrange(1, 7), rng.choice((80, 90, 95)), rng.randrange(size))

    observations = (I64 * 4)(3, 3, LIMIT + 1, 3)
    future = Prediction(2, 3, 4, 5, 1)
    original = bytes(future)
    for args in ((observations, 4, 1, 1, 90), (observations, 1, 0, 1, 90),
                 (observations, 1, 366, 1, 90), (observations, 1, 1, 0, 90),
                 (observations, 1, 1, 257, 90), (observations, 1, 1, 1, 81),
                 (observations, 257, 1, 1, 90), (None, 1, 1, 1, 90)):
        assert native.predict(*args, C.byref(future)) == 0
        assert bytes(future) == original
    folds = (Fold * 2)(Fold(123), Fold(321))
    metrics = Metrics(11, 12, 13, 14, 15, 16)
    saved = bytes(folds), bytes(metrics)
    for count, first, cap in ((4, 2, 2), (2, 2, 2), (2, 0, 1)):
        assert native.evaluate(observations, count, 1, 1, 90, first, folds, cap, C.byref(metrics)) == 0
        assert (bytes(folds), bytes(metrics)) == saved


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib"))
    assert (mulib / "kernels/mulib-statsproc.h").is_file(), f"MuLIB kernels missing at {mulib}"
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-numerics-", dir=scratch) as directory:
        library = Path(directory) / "series.so"
        subprocess.run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-O2", "-Wall",
                        "-Wextra", "-Wpedantic", "-Werror", "-shared", "-fPIC",
                        *shlex.split(os.environ.get("SERIES_CFLAGS", "")), "-I", mulib / "kernels",
                        ROOT / "source/algorithms/series_forecast.c", "-x", "c", "-", "-lm", "-o", library],
                       input=b'#define MULIB_IMPL_STATSPROC\n#include <mulib-statsproc.h>\n', check=True)
        test(Native(C.CDLL(str(library))))
    print("core_numerics_ok=true")


if __name__ == "__main__":
    main()
