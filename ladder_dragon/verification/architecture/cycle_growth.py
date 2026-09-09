# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: reject new direct cyclic edges against verified release lineage.
"""Read immutable Git source without importing historical application code."""

import ast
import re
import subprocess
from pathlib import Path

from ladder_dragon.verification.architecture.dependency_graph import dependency_graph


def historical_trees(root: Path, sha: str) -> dict:
    """Bound immutable source reads; missing or ambiguous history blocks callers."""
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("invalid baseline identity")
    def git(*args: str, input_data: bytes | None = None) -> bytes:
        return subprocess.run(["git", "--no-replace-objects", *args], cwd=root,
                              input=input_data, capture_output=True, check=True, timeout=30).stdout
    if git("cat-file", "-t", sha).strip() != b"commit":
        raise ValueError("baseline is not a commit")
    listing = git("ls-tree", "-r", "-l", "-z", sha)
    if len(listing) > 2 * 1024 * 1024:
        raise ValueError("baseline inventory exceeds ceiling")
    records, trees, total = [], {}, 0
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if not path.endswith(".py") or path.startswith("tests/"):
            continue
        mode, kind, oid, size = metadata.split()
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            raise ValueError("invalid baseline source type")
        length = int(size)
        total += length
        if length > 1024 * 1024 or total > 32 * 1024 * 1024 or len(records) >= 4096:
            raise ValueError("baseline source exceeds ceiling")
        records.append((path, oid, length))
    # Object sizes come from the immutable tree; batch output is bounded by their sum.
    data = git("cat-file", "--batch", input_data=b"".join(oid + b"\n" for _, oid, _ in records))
    offset = 0
    for path, oid, length in records:
        end = data.index(b"\n", offset)
        if data[offset:end] != oid + b" blob " + str(length).encode("ascii"):
            raise ValueError("baseline object identity mismatch")
        offset = end + 1
        source = data[offset:offset + length]
        offset += length
        if data[offset:offset + 1] != b"\n":
            raise ValueError("baseline object framing mismatch")
        offset += 1
        trees[path] = ast.parse(source.decode("utf-8"))
        trees[path].source_lines = len(source.decode("utf-8").splitlines())
    if offset != len(data):
        raise ValueError("unexpected baseline output")
    if not trees:
        raise ValueError("baseline source missing")
    return trees


def historical_graph(root: Path, sha: str) -> dict:
    """Keep graph interpretation separate from immutable source reads."""
    return dependency_graph(historical_trees(root, sha))


def cyclic_edges(graph: dict, *, combined: bool = False) -> set[tuple[str, str]]:
    """Include every direct edge inside a strongly connected cyclic group."""
    groups, edges = ("cycles", "edges") if combined else ("direct_cycles", "direct_edges")
    return {(source, target) for group in graph[groups] for source in group
            for target in graph[edges][source] if target in group}


def compare_cycle_growth(previous: dict, current: dict) -> dict:
    """Shrinking is allowed; new, merged, restored, or expanded cycles fail."""
    baseline, observed = cyclic_edges(previous), cyclic_edges(current)
    added = sorted(observed - baseline)
    combined_baseline = cyclic_edges(previous, combined=True)
    combined_observed = cyclic_edges(current, combined=True)
    combined_added = sorted(combined_observed - combined_baseline)
    # Separate comparisons prevent initializer debt from licensing direct cycles.
    return {"status": "FAILED" if added or combined_added else "PASS", "rule": "A03-static",
            "baseline_cyclic_edges": len(baseline), "current_cyclic_edges": len(observed),
            "new_cyclic_edges": [{"source": source, "target": target} for source, target in added],
            "baseline_combined_cyclic_edges": len(combined_baseline),
            "current_combined_cyclic_edges": len(combined_observed),
            "new_combined_cyclic_edges": [{"source": source, "target": target} for source, target in combined_added],
            "scope": "Direct and initializer-inclusive static cycles are enforced separately in every observed context. Dynamic cycles and runtime reachability remain unproved."}
