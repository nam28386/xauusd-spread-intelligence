"""Bounded, strict configuration; never log local file contents or paths."""

import json
import ntpath
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from xbsis.models import Contract, Identifier


class LiveSource(Contract):
    source_id: Identifier
    broker_id: Identifier
    server_alias: Identifier
    terminal_path: Annotated[str, Field(min_length=1, max_length=1024)]
    symbol: Identifier
    expected_account_environment: Literal["REAL", "DEMO"]
    account_type_user_label: Literal["STANDARD", "RAW", "RAZOR", "UNKNOWN"] = "UNKNOWN"
    confirm_usd_per_oz: Annotated[bool, Field(strict=True)]
    poll_interval_ms: Annotated[int, Field(strict=True, ge=50, le=10_000)] = 250

    @field_validator("source_id", "broker_id", "server_alias")
    @classmethod
    def alias_not_numeric(cls, value: str) -> str:
        if value.isdigit():
            raise ValueError("numeric-only aliases are not allowed")
        return value

    @field_validator("confirm_usd_per_oz")
    @classmethod
    def explicitly_confirm_unit(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("explicit confirmation is required")
        return value

    @field_validator("terminal_path")
    @classmethod
    def valid_terminal(cls, value: str) -> str:
        normalized = value.replace("/", "\\")
        drive, tail = ntpath.splitdrive(normalized)
        if (
            not re.fullmatch(r"[A-Za-z]:", drive)
            or not tail.startswith("\\")
            or ntpath.basename(normalized).lower() != "terminal64.exe"
            or "\x00" in value
        ):
            raise ValueError("terminal must be an absolute local Windows terminal64.exe path")
        return value


class LiveSources(Contract):
    sources: Annotated[tuple[LiveSource, ...], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def unique(self):
        ids = [s.source_id.casefold() for s in self.sources]
        paths = [ntpath.normcase(ntpath.normpath(s.terminal_path)) for s in self.sources]
        if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
            raise ValueError("source IDs and terminal installations must be distinct")
        return self


def load_local_sources(path: Path) -> LiveSources:
    cwd = Path.cwd().resolve()
    allowed = (cwd / "data" / "config").resolve()
    resolved = path.resolve()
    if allowed != cwd / "data" / "config" or not resolved.is_relative_to(allowed):
        raise ValueError("Source configuration must be in the ignored data/config directory.")
    try:
        if resolved.stat().st_size > 32_768:
            raise ValueError("Source configuration exceeds the size limit.")
        content = resolved.read_text(encoding="utf-8")
        return LiveSources.model_validate(json.loads(content))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
        raise ValueError("Source configuration is missing or invalid; check the runbook.") from None
