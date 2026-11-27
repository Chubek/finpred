#!/usr/bin/env python3
"""Measure real local IPC CLI calls, including process startup and journaling."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter

from check_core_overhaul import ROOT, Session


def main():
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="coord-bench-", dir=scratch) as directory:
        session = Session(ROOT / "bin/overhaul-coord.py", Path(directory))
        try:
            session.invoke(0, "init")
            for concurrency in (1, 8):
                def publish(actor):
                    elapsed = []
                    for i in range(64 // concurrency):
                        start = perf_counter()
                        session.invoke(actor, "status", f"sample {actor}/{i}")
                        elapsed.append(perf_counter() - start)
                    return elapsed

                start = perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    samples = [seconds for worker in pool.map(publish, range(concurrency))
                               for seconds in worker]
                wall = perf_counter() - start
                print(f"status workers={concurrency} samples={len(samples)} "
                      f"median_ms={1000 * median(samples):.3f} ops_s={len(samples) / wall:.1f}")

            trips = []
            for _ in range(16):
                correlation = session.request()
                session.grant(correlation)
                start = perf_counter()
                session.send(1, correlation, "acknowledged benchmark exchange")
                received = session.receive(2)
                assert received["correlation"] == correlation
                session.invoke(2, "ack", correlation)
                trips.append(perf_counter() - start)
            print(f"send_recv_ack samples={len(trips)} median_ms={1000 * median(trips):.3f}")
        finally:
            session.invoke(0, "cleanup")
            session.resources_absent()


if __name__ == "__main__":
    main()
