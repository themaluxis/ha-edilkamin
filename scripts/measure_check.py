"""Measure how the stove publishes its state after a "check" command.

Answers two open questions of the ha-edilkamin freshness work:
  1. How long does the stove keep publishing after a check (publication window)?
  2. Does a check also refresh the nvm block (nvm.timestamp)?

Usage (from the ha-edilkamin repo, so the edilkamin lib is available):

    EDILKAMIN_USERNAME=me@example.com EDILKAMIN_MAC=aa:bb:cc:dd:ee:ff \
        uv run python scripts/measure_check.py --duration 300 --interval 2

The password is read from EDILKAMIN_PASSWORD or asked interactively. The token and
the password are never printed. Use --skip-check to measure a baseline without check.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import getpass
import itertools
import json
import os
from pathlib import Path
import statistics
import sys
import time

import edilkamin


@dataclass
class Sample:
    elapsed: float  # seconds since the check was sent
    status_ts: float | None  # seconds
    nvm_ts: float | None  # seconds
    crc16_nvm: object
    operational_phase: object


def to_seconds(value) -> float | None:
    """Timestamps are in milliseconds; accept seconds just in case."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value / 1000 if value > 1e11 else float(value)


def sample(info: dict, t0: float) -> Sample:
    status = info.get("status") or {}
    nvm = info.get("nvm") or {}
    return Sample(
        elapsed=time.time() - t0,
        status_ts=to_seconds(status.get("timestamp")),
        nvm_ts=to_seconds(nvm.get("timestamp")),
        crc16_nvm=(status.get("diagnostics") or {}).get("crc16_nvm"),
        operational_phase=(status.get("state") or {}).get("operational_phase"),
    )


def age(ts: float | None) -> str:
    return "   n/a" if ts is None else f"{time.time() - ts:6.0f}s"


def fmt_rel(ts: float | None, t0: float) -> str:
    return "n/a" if ts is None else f"{ts - t0:+.1f}s"


async def run(args: argparse.Namespace) -> int:
    username = os.environ.get("EDILKAMIN_USERNAME") or input("Username: ")
    mac = os.environ.get("EDILKAMIN_MAC") or input("MAC address: ")
    password = os.environ.get("EDILKAMIN_PASSWORD") or getpass.getpass("Password: ")

    token = await asyncio.to_thread(edilkamin.sign_in, username, password)
    print("Signed in.")

    before = sample(await edilkamin.device_info(token, mac), time.time())
    print(
        f"Before: status age {age(before.status_ts)}, nvm age {age(before.nvm_ts)}, "
        f"crc16_nvm={before.crc16_nvm}, phase={before.operational_phase}"
    )

    t0 = time.time()
    if args.skip_check:
        print("Baseline mode: no check sent.")
    else:
        result = await edilkamin.mqtt_command(token, mac, {"name": "check"})
        print(f"Check sent at t=0 ({result}).")

    samples: list[Sample] = []
    status_publications: list[float] = []  # status.timestamp values, relative to t0
    nvm_publications: list[float] = []
    crc_changes: list[float] = []
    last = before
    print(f"\nPolling every {args.interval}s for {args.duration}s (changes only):")
    print("   t     status age  nvm age   change")

    while time.time() - t0 < args.duration:
        await asyncio.sleep(args.interval)
        try:
            current = sample(await edilkamin.device_info(token, mac), t0)
        except Exception as err:  # noqa: BLE001 - keep measuring on transient errors
            print(f"{time.time() - t0:6.1f}s  read failed: {type(err).__name__}")
            continue
        samples.append(current)

        changes = []
        if current.status_ts != last.status_ts and current.status_ts is not None:
            status_publications.append(current.status_ts - t0)
            changes.append(f"status published at {fmt_rel(current.status_ts, t0)}")
        if current.nvm_ts != last.nvm_ts and current.nvm_ts is not None:
            nvm_publications.append(current.nvm_ts - t0)
            changes.append(f"nvm published at {fmt_rel(current.nvm_ts, t0)}")
        if current.crc16_nvm != last.crc16_nvm:
            crc_changes.append(current.elapsed)
            changes.append(f"crc16_nvm {last.crc16_nvm} -> {current.crc16_nvm}")
        if current.operational_phase != last.operational_phase:
            changes.append(
                f"phase {last.operational_phase} -> {current.operational_phase}"
            )
        if changes:
            print(
                f"{current.elapsed:6.1f}s  {age(current.status_ts)}  "
                f"{age(current.nvm_ts)}   " + "; ".join(changes)
            )
        last = current

    print_summary(
        args,
        (before, last),
        status_publications,
        nvm_publications,
        crc_changes,
    )

    if args.output:
        payload = {
            "args": {k: v for k, v in vars(args).items() if k != "output"},
            "check_sent_at": None if args.skip_check else t0,
            "before": asdict(before),
            "samples": [asdict(s) for s in samples],
        }
        Path(args.output).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nRaw samples written to {args.output}")
    return 0


def print_summary(args, first_and_last, status_pubs, nvm_pubs, crc_changes) -> None:
    before, last = first_and_last
    print("\n=== Summary ===")
    after_check = [t for t in status_pubs if t >= 0]
    if not after_check:
        print("Status: no new publication seen" + (
            "." if args.skip_check else " after the check (check had no effect?)."
        ))
    else:
        print(f"Status: {len(after_check)} publication(s) after t=0")
        print(f"  first at {after_check[0]:+.1f}s (latency of the check)")
        print(f"  last  at {after_check[-1]:+.1f}s")
        window = after_check[-1] - after_check[0]
        print(f"  publication window: {window:.0f}s")
        typical_gap = 5.0
        if len(after_check) > 1:
            gaps = [b - a for a, b in itertools.pairwise(after_check)]
            typical_gap = statistics.median(gaps)
            print(
                f"  interval between publications: median "
                f"{typical_gap:.1f}s, min {min(gaps):.1f}s, max {max(gaps):.1f}s"
            )
        # Publishing stopped if the final silence is much longer than the usual gap
        silence = args.duration - after_check[-1]
        if silence < max(3 * typical_gap, 3 * args.interval, 15):
            print(
                "  WARNING: still publishing at the end of the run, the window is "
                "at least this long: run again with a longer --duration."
            )
        print(f"  status age at the end: {age(last.status_ts).strip()}")

    if nvm_pubs:
        published = ", ".join(f"{t:+.1f}s" for t in nvm_pubs)
        print(f"nvm: refreshed, publications at {published}")
    else:
        print(
            "nvm: NOT refreshed during the run "
            f"(nvm.timestamp age at the end: {age(last.nvm_ts).strip()})"
        )
    if crc_changes and not nvm_pubs:
        print(
            "  crc16_nvm changed while nvm.timestamp did not: the nvm block is stale "
            "-> do not use nvm to decide freshness."
        )
    if before.crc16_nvm != last.crc16_nvm:
        print(f"  crc16_nvm: {before.crc16_nvm} -> {last.crc16_nvm}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=int, default=300, help="seconds (300)")
    parser.add_argument("--interval", type=float, default=2, help="seconds (2)")
    parser.add_argument("--skip-check", action="store_true", help="baseline run")
    parser.add_argument("--output", help="write raw samples to this JSON file")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
