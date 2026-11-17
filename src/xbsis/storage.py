"""Local exact-text persistence; never cast raw prices or nanoseconds to DOUBLE."""

import hashlib
from pathlib import Path
from types import TracebackType

import duckdb

from xbsis.models import Observation


class ObservationStore:
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(str(database))
        self._connection.execute("CREATE SEQUENCE IF NOT EXISTS observation_ordinal START 1")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS observations "
            "(ordinal BIGINT DEFAULT nextval('observation_ordinal'), "
            "observation_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL)"
        )

    def append(self, record: Observation) -> str:
        payload = record.model_dump_json()
        identity = hashlib.sha256(payload.encode()).hexdigest()
        self._connection.execute(
            "INSERT INTO observations (observation_id, payload) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            [identity, payload],
        )
        return identity

    def records(self) -> tuple[Observation, ...]:
        # Preserve append order, including regressions in source/receive clocks.
        rows = self._connection.execute(
            "SELECT payload FROM observations ORDER BY ordinal"
        ).fetchall()
        return tuple(Observation.model_validate_json(row[0]) for row in rows)

    def export_parquet(self, destination: Path) -> None:
        # COPY with a bound destination is supported by DuckDB; paths are never SQL fragments.
        if destination.exists():
            raise FileExistsError("refusing to overwrite an existing artifact")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._connection.execute(
            "COPY (SELECT ordinal, observation_id, payload FROM observations ORDER BY ordinal) "
            "TO ? (FORMAT PARQUET)",
            [str(destination)],
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "ObservationStore":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
