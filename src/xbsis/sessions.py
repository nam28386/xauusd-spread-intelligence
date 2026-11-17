"""Local sealed segments and bounded read-only session access.

Only closed segments named in an atomically updated manifest are readable. The
active writer file is never opened by readers. A crash leaves an INCOMPLETE marker.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import duckdb

from xbsis.models import Observation
from xbsis.storage import ObservationStore

SEGMENT_ROWS = 1000
MAX_SEGMENTS = 600
MAX_SESSION_BYTES = 1_073_741_824
SESSION_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class SessionLimitError(RuntimeError):
    """Storage stopped before creating another segment."""


def code_revision() -> str:
    try:
        result = subprocess.run(  # noqa: S603 -- fixed command and no shell
            ["git", "rev-parse", "--verify", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
        return result if re.fullmatch(r"[0-9a-f]{40}", result) else "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def code_dirty():
    try:
        result = subprocess.run(  # noqa: S603 -- fixed git command
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return bool(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


class SessionRecorder:
    """One worker, sequential bounded segments, immutable closed-file handoff."""

    def __init__(
        self,
        output: Path,
        *,
        stop_event=None,
        segment_rows=SEGMENT_ROWS,
        max_segments=MAX_SEGMENTS,
        max_bytes=MAX_SESSION_BYTES,
    ):
        if not 1 <= segment_rows <= SEGMENT_ROWS or not 1 <= max_segments <= MAX_SEGMENTS:
            raise ValueError("invalid segment limits")
        self.output = output
        self.stop_event = stop_event
        self.segment_rows = segment_rows
        self.max_segments = max_segments
        self.max_bytes = max_bytes
        self.manifest = {
            "schema_version": "session-v1",
            "session_id": output.name,
            "state": "INCOMPLETE",
            "created_ns": str(time.time_ns()),
            "code_revision": code_revision(),
            "code_dirty": code_dirty(),
            "segments": [],
            "source": None,
            "total_observations": 0,
            "storage_limit_bytes": max_bytes,
        }
        self.store = None
        self.rows = 0
        self.low = None
        self.high = None
        self.total_bytes = 0

    def __enter__(self):
        _atomic_json(self.output / "manifest.json", self.manifest)
        self._open()
        return self

    def _open(self):
        if (
            len(self.manifest["segments"]) >= self.max_segments
            or self.total_bytes >= self.max_bytes
        ):
            raise SessionLimitError("session storage limit reached")
        if shutil.disk_usage(self.output).free < 268_435_456:
            raise SessionLimitError("insufficient local free space")
        self.active = self.output / f"active-{len(self.manifest['segments']):06d}.duckdb"
        self.store = ObservationStore(self.active)
        self.rows = 0
        self.low = self.high = None

    def append(self, record: Observation):
        if self.store is None:
            self._open()
        raw = record.quote.raw
        source = {
            "source_id": raw.source_id,
            "broker_id": raw.broker_id,
            "server_id": raw.server_id,
            "environment": raw.account_environment.value,
            "symbol_raw": raw.symbol_raw,
            "ingestion_mode": raw.ingestion_mode.value,
        }
        if self.manifest["source"] is None:
            self.manifest["source"] = source
        elif source != self.manifest["source"]:
            raise ValueError("session source identity changed")
        self.store.append(record)
        self.rows += 1
        self.low = raw.received_time_ns if self.low is None else min(self.low, raw.received_time_ns)
        self.high = (
            raw.received_time_ns if self.high is None else max(self.high, raw.received_time_ns)
        )
        if self.rows >= self.segment_rows:
            self._seal()

    def _seal(self):
        if self.store is None:
            return
        actual_rows = self.store._connection.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0]
        self.store.close()
        self.store = None
        wal = Path(str(self.active) + ".wal")
        if wal.exists():
            raise RuntimeError("closed segment has an unresolved WAL")
        if actual_rows == 0:
            self.active.unlink()
            return
        number = len(self.manifest["segments"])
        name = "observations.duckdb" if number == 0 else f"segment-{number:06d}.duckdb"
        target = self.output / name
        if target.exists():
            raise FileExistsError("segment already exists")
        os.replace(self.active, target)
        size = target.stat().st_size
        self.total_bytes += size
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        self.manifest["segments"].append(
            {
                "index": number,
                "file": name,
                "rows": actual_rows,
                "bytes": size,
                "sha256": digest,
                "min_receive_ns": str(self.low),
                "max_receive_ns": str(self.high),
            }
        )
        self.manifest["total_observations"] += actual_rows
        _atomic_json(self.output / "manifest.json", self.manifest)

    def __exit__(self, exc_type, exc, traceback):
        try:
            self._seal()
            if exc_type is None and not (self.stop_event and self.stop_event.is_set()):
                self.manifest["state"] = "COMPLETE"
            else:
                self.manifest["state"] = "INTERRUPTED"
            self.manifest["closed_ns"] = str(time.time_ns())
            _atomic_json(self.output / "manifest.json", self.manifest)
        except Exception:
            if self.store is not None:
                self.store.close()
            raise


def session_root() -> Path:
    cwd = Path.cwd().resolve()
    data = (cwd / "data").resolve()
    root = (data / "mt5").resolve()
    if data != cwd / "data" or not root.is_relative_to(data):
        raise ValueError("unsafe session root")
    return root


def _directory(session_id: str) -> Path:
    if not SESSION_NAME.fullmatch(session_id):
        raise ValueError("invalid session id")
    root = session_root()
    directory = root / session_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError("invalid session directory")
    return directory


def read_manifest(session_id: str) -> dict:
    directory = _directory(session_id)
    path = directory / "manifest.json"
    if path.is_symlink():
        raise FileNotFoundError("session manifest unavailable")
    if not path.is_file():
        return legacy_manifest(session_id)
    if path.stat().st_size > 1_000_000:
        raise ValueError("session manifest exceeds limit")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "session-v1" or manifest.get("session_id") != session_id:
        raise ValueError("invalid session manifest")
    if not isinstance(manifest.get("segments"), list) or len(manifest["segments"]) > MAX_SEGMENTS:
        raise ValueError("invalid segment manifest")
    return manifest


def legacy_manifest(session_id: str) -> dict:
    """Recognize older single-file sessions only after their completion summary exists."""
    directory = _directory(session_id)
    db = directory / "observations.duckdb"
    summary = directory / "summary.json"
    if (
        db.is_symlink()
        or summary.is_symlink()
        or not db.is_file()
        or not summary.is_file()
        or Path(str(db) + ".wal").exists()
        or summary.stat().st_size > 16384
    ):
        raise FileNotFoundError("legacy session is not safely sealed")
    try:
        parsed = json.loads(summary.read_text(encoding="utf-8"))
        if parsed.get("mode") not in {"MOCK", "MOCK_REPLAY", "READ_ONLY_POLLING"}:
            raise ValueError("unrecognized legacy summary")
        with duckdb.connect(str(db), read_only=True) as connection:
            count, low, high = connection.execute(
                "SELECT count(*), min(try_cast(json_extract_string(payload, "
                "'$.quote.raw.received_time_ns') AS HUGEINT)), "
                "max(try_cast(json_extract_string(payload, "
                "'$.quote.raw.received_time_ns') AS HUGEINT)) FROM observations"
            ).fetchone()
            first = connection.execute(
                "SELECT payload FROM observations ORDER BY ordinal LIMIT 1"
            ).fetchone()
        if count > 640_000 or (count and (low is None or high is None)):
            raise ValueError("invalid legacy session")
        source = None
        if first:
            raw = Observation.model_validate_json(first[0]).quote.raw
            source = {
                "source_id": raw.source_id,
                "broker_id": raw.broker_id,
                "server_id": raw.server_id,
                "environment": raw.account_environment.value,
                "symbol_raw": raw.symbol_raw,
                "ingestion_mode": raw.ingestion_mode.value,
            }
        with db.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        segments = (
            []
            if not count
            else [
                {
                    "index": 0,
                    "file": "observations.duckdb",
                    "rows": count,
                    "bytes": db.stat().st_size,
                    "sha256": digest,
                    "min_receive_ns": str(low),
                    "max_receive_ns": str(high),
                }
            ]
        )
        return {
            "schema_version": "session-v1",
            "session_id": session_id,
            "state": "LEGACY_COMPLETENESS_UNKNOWN",
            "legacy": True,
            "created_ns": str(db.stat().st_mtime_ns),
            "code_revision": "UNKNOWN",
            "code_dirty": None,
            "segments": segments,
            "source": source,
            "total_observations": count,
        }
    except (duckdb.Error, OSError, json.JSONDecodeError):
        raise ValueError("legacy session is unavailable") from None


def list_sessions(limit=100):
    root = session_root()
    if not root.is_dir():
        return []
    entries = []
    for directory in root.iterdir():
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or not SESSION_NAME.fullmatch(directory.name)
        ):
            continue
        try:
            manifest = read_manifest(directory.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        entries.append(
            {
                k: manifest.get(k)
                for k in (
                    "session_id",
                    "state",
                    "created_ns",
                    "closed_ns",
                    "source",
                    "total_observations",
                    "code_revision",
                    "code_dirty",
                )
            }
            | {"segments": len(manifest["segments"])}
        )
        entries.sort(key=lambda row: (row["created_ns"] or "", row["session_id"]), reverse=True)
        del entries[limit:]
    return entries


def segment_path(session_id: str, number: int) -> Path:
    manifest = read_manifest(session_id)
    if number < 0 or number >= len(manifest["segments"]):
        raise FileNotFoundError("sealed segment unavailable")
    name = "observations.duckdb" if number == 0 else f"segment-{number:06d}.duckdb"
    if manifest["segments"][number].get("file") != name:
        raise ValueError("invalid segment name")
    path = _directory(session_id) / name
    if path.is_symlink() or not path.is_file() or Path(str(path) + ".wal").exists():
        raise FileNotFoundError("sealed segment unavailable")
    item = manifest["segments"][number]
    if path.stat().st_size != item.get("bytes"):
        raise ValueError("sealed segment integrity mismatch")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != item.get("sha256"):
        raise ValueError("sealed segment integrity mismatch")
    return path


def page(session_id: str, segment: int, after: int, limit: int, start_ns=None, end_ns=None):
    if segment < 0 or after < 0 or not 1 <= limit <= 1000:
        raise ValueError("invalid page bounds")
    if start_ns is not None and end_ns is not None and start_ns > end_ns:
        raise ValueError("invalid time window")
    path = segment_path(session_id, segment)
    query = "SELECT ordinal, payload FROM observations WHERE ordinal > ?"
    values = [after]
    if start_ns is not None:
        query += (
            " AND try_cast(json_extract_string(payload, "
            "'$.quote.raw.received_time_ns') AS HUGEINT) >= ?"
        )
        values.append(start_ns)
    if end_ns is not None:
        query += (
            " AND try_cast(json_extract_string(payload, "
            "'$.quote.raw.received_time_ns') AS HUGEINT) <= ?"
        )
        values.append(end_ns)
    query += " ORDER BY ordinal LIMIT ?"
    values.append(limit)
    with duckdb.connect(str(path), read_only=True) as connection:
        rows = connection.execute(query, values).fetchall()
    return [
        {
            "ordinal": row[0],
            "observation": Observation.model_validate_json(row[1]).model_dump(mode="json"),
        }
        for row in rows
    ]


def iter_observations(session_id: str):
    """Stream sealed records in ingestion order without loading a full database."""
    manifest = read_manifest(session_id)
    limit = 640_000 if manifest.get("legacy") else SEGMENT_ROWS
    expected_source = manifest.get("source")
    for number in range(len(manifest["segments"])):
        path = segment_path(session_id, number)
        with duckdb.connect(str(path), read_only=True) as connection:
            cursor = connection.execute("SELECT payload FROM observations ORDER BY ordinal")
            count = 0
            while rows := cursor.fetchmany(1000):
                count += len(rows)
                if count > limit:
                    raise ValueError("segment exceeds row limit")
                for row in rows:
                    observation = Observation.model_validate_json(row[0])
                    raw = observation.quote.raw
                    actual_source = {
                        "source_id": raw.source_id,
                        "broker_id": raw.broker_id,
                        "server_id": raw.server_id,
                        "environment": raw.account_environment.value,
                        "symbol_raw": raw.symbol_raw,
                        "ingestion_mode": raw.ingestion_mode.value,
                    }
                    if actual_source != expected_source:
                        raise ValueError("session source identity mismatch")
                    yield observation


def mark_forced_termination(session_id: str) -> None:
    """Called only after a forcibly stopped worker has fully exited."""
    manifest = read_manifest(session_id)
    manifest["state"] = "INTERRUPTED"
    manifest["termination_reason"] = "FORCED_TERMINATION"
    manifest["closed_ns"] = str(time.time_ns())
    _atomic_json(_directory(session_id) / "manifest.json", manifest)
