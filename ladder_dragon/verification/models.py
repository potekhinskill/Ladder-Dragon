# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: define immutable verification report and check models.
"""Versioned, non-secret verification harness data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable


class Status(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


EXIT_CODES = {
    Status.PASS: 0,
    Status.BLOCKED: 2,
    Status.FAILED: 1,
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    required: bool
    duration_ms: int
    summary: str
    exit_code: int | None = None
    metrics: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "required": self.required,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "metrics": self.metrics,
        }


CheckCallable = Callable[["HarnessContext"], CheckResult]


@dataclass(frozen=True)
class CheckSpec:
    name: str
    required: bool = True
    argv: tuple[str, ...] | None = None
    timeout_sec: int = 900
    blocked_reason: str | None = None
    check: CheckCallable | None = None


@dataclass(frozen=True)
class HarnessOptions:
    profile: str
    output: Path
    expected_sha: str | None = None
    github_sha: str | None = None
    symbol: str = "SOLUSDT"
    confirm_authenticated_testnet: bool = False
    confirm_testnet_mutation: bool = False
    confirm_mainnet_canary: bool = False
    release_report: Path | None = None
    replay_validation: Path | None = None
    latency_log: Path | None = None
    source_paths: tuple[Path, ...] = ()
    runtime_status: Path = Path("/run/mybot/ai_status.json")
    user_stream_status: Path = Path("/run/mybot/user_stream_SOLUSDT.json")
    risk_status: Path = Path("/run/mybot/risk_state.json")
    order_journal: Path = Path("db/order_intents.sqlite3")
    prediction_db: Path = Path("db/prediction_shadow.sqlite3")
    ai_decisions_db: Path = Path("db/ai_decisions.sqlite3")


@dataclass(frozen=True)
class HarnessContext:
    root: Path
    python: str
    options: HarnessOptions


@dataclass(frozen=True)
class HarnessReport:
    schema_version: int
    product_version: str
    commit_sha: str
    generated_at: str
    profile: str
    status: Status
    checks: tuple[CheckResult, ...]
    input_hashes: dict[str, str]
    tests: dict[str, int]
    replay: dict[str, object]
    latency_ms: dict[str, int] | None
    unresolved_fills: int | None
    exact_lifecycles: dict[str, int]
    block_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_version": self.product_version,
            "commit_sha": self.commit_sha,
            "generated_at": self.generated_at,
            "profile": self.profile,
            "status": self.status.value,
            "checks": [item.as_dict() for item in self.checks],
            "input_hashes": self.input_hashes,
            "tests": self.tests,
            "replay": self.replay,
            "latency_ms": self.latency_ms,
            "unresolved_fills": self.unresolved_fills,
            "exact_lifecycles": self.exact_lifecycles,
            "block_reasons": list(self.block_reasons),
        }
