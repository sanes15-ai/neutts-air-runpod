"""Append-only JSONL record of evaluations and fills, plus session PnL."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator, Mapping

from .config import LAMPORTS_PER_SOL


class Ledger:
    """Writes one JSON object per line and tracks cumulative PnL.

    JSONL rather than a database: the file stays greppable, appends survive a
    crash mid-write of the *next* record, and post-hoc analysis is a one-liner.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._realized_lamports = 0
        self._fills = 0

    @property
    def realized_lamports(self) -> int:
        return self._realized_lamports

    @property
    def realized_sol(self) -> float:
        return self._realized_lamports / LAMPORTS_PER_SOL

    @property
    def fills(self) -> int:
        return self._fills

    def record(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Append a record. ``kind`` is one of ``scan``, ``fill``, ``error``."""
        entry = {"kind": kind, **payload}
        line = json.dumps(entry, separators=(",", ":"), default=str)
        with self._lock:
            if kind == "fill":
                self._realized_lamports += int(payload.get("net_lamports", 0))
                self._fills += 1
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read(self) -> Iterator[dict]:
        """Yield every record written so far, skipping any truncated tail line."""
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def summary(self) -> dict:
        """Aggregate the on-disk ledger (independent of in-memory counters)."""
        scans = fills = 0
        net = 0
        wins = 0
        for entry in self.read():
            if entry.get("kind") == "scan":
                scans += 1
            elif entry.get("kind") == "fill":
                fills += 1
                value = int(entry.get("net_lamports", 0))
                net += value
                wins += value > 0
        return {
            "scans": scans,
            "fills": fills,
            "wins": wins,
            "net_lamports": net,
            "net_sol": net / LAMPORTS_PER_SOL,
            "hit_rate": wins / fills if fills else 0.0,
        }
