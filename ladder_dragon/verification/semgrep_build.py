# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify and install the isolated downstream static analyzer.
"""Rebuild pinned upstream wheels without changing analyzer code or licenses."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

SOURCE_HASHES = {
    "macosx_11_0_arm64": "e6b85d84e815ff86f56dcb6b4a6370b98f1bc0e402144daafa9b41aa00ea9a90",
    "manylinux_2_34_aarch64": "fa22f0a41ee3857ecec1b3883b2920b1d41d07ef1bdd7e216da3c519210ae5fb",
    "manylinux_2_34_x86_64": "09dfacb0530ed4a17bd2deb7914e9a25fc3581d5d84d5365cdac77bbebed8081",
}
WHEEL_TAGS = "cp310.cp311.cp312.cp313.cp314.py310.py311.py312.py313.py314-none-"
SOURCE_VERSION = "1.168.0"
VERSION = "1.168.0+ld.1"
OLD_INFO = f"semgrep-{SOURCE_VERSION}.dist-info/"
NEW_INFO = f"semgrep-{VERSION}.dist-info/"
REPLACEMENTS = {
    "Version: 1.168.0": f"Version: {VERSION}",
    "Requires-Dist: mcp==1.23.3": "Requires-Dist: mcp==1.30.0",
    "Requires-Dist: pyjwt[crypto]~=2.13.0": "Requires-Dist: pyjwt[crypto]==2.15.0",
    "Requires-Dist: opentelemetry-api~=1.37.0": "Requires-Dist: opentelemetry-api==1.45.1",
    "Requires-Dist: opentelemetry-sdk~=1.37.0": "Requires-Dist: opentelemetry-sdk==1.45.1",
    "Requires-Dist: opentelemetry-exporter-otlp-proto-http~=1.37.0": "Requires-Dist: opentelemetry-exporter-otlp-proto-http==1.45.1",
    "Requires-Dist: opentelemetry-instrumentation-requests~=0.58b0": "Requires-Dist: opentelemetry-instrumentation-requests==0.66b1",
    "Requires-Dist: opentelemetry-instrumentation-threading~=0.58b0": "Requires-Dist: opentelemetry-instrumentation-threading==0.66b1",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def target_name(name):
    for suffix in (".dist-info/", ".data/"):
        prefix = f"semgrep-{SOURCE_VERSION}" + suffix
        if name.startswith(prefix):
            return f"semgrep-{VERSION}" + suffix + name[len(prefix):]
    return name


def rebuild(source, destination):
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 96 * 1024**2:
        raise ValueError("invalid source")
    platform = source.name.removeprefix(f"semgrep-{SOURCE_VERSION}-" + WHEEL_TAGS).removesuffix(".whl")
    expected_hash = SOURCE_HASHES.get(platform)
    if expected_hash is None:
        raise ValueError("unsupported source wheel")
    raw = source.read_bytes()
    if digest(raw) != expected_hash:
        raise ValueError("source hash mismatch")
    payloads, modes = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > 512 * 1024**2:
            raise ValueError("archive size limit")
        for item in entries:
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or item.filename in payloads or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("invalid archive entry")
            payloads[item.filename] = archive.read(item)
            modes[item.filename] = item.external_attr
    record_name = OLD_INFO + "RECORD"
    record = list(csv.reader(io.StringIO(payloads[record_name].decode())))
    if {row[0] for row in record} != set(payloads) or len(record) != len(payloads):
        raise ValueError("record coverage mismatch")
    for name, expected, length in record:
        if name == record_name:
            if expected or length:
                raise ValueError("invalid self record")
            continue
        data = payloads[name]
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if expected != "sha256=" + encoded or length != str(len(data)):
            raise ValueError("record digest mismatch")
    metadata = payloads[OLD_INFO + "METADATA"].decode()
    for old, new in REPLACEMENTS.items():
        if metadata.splitlines().count(old) != 1:
            raise ValueError("metadata preimage mismatch: " + old)
        metadata = metadata.replace(old + "\n", new + "\n", 1)
    transformed = {}
    for name, data in payloads.items():
        if name == record_name:
            continue
        target = target_name(name)
        transformed[target] = (metadata.encode() if name == OLD_INFO + "METADATA" else data, modes[name])
    rows = []
    for name, (data, _) in sorted(transformed.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((name, "sha256=" + encoded, str(len(data))))
    rows.append((NEW_INFO + "RECORD", "", ""))
    record_buffer = io.StringIO(newline="")
    csv.writer(record_buffer, lineterminator="\n").writerows(rows)
    transformed[NEW_INFO + "RECORD"] = (record_buffer.getvalue().encode(), modes[record_name])
    output_name = source.name.replace(f"semgrep-{SOURCE_VERSION}-", f"semgrep-{VERSION}-", 1)
    output = destination / output_name
    with output.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, (data, mode) in sorted(transformed.items()):
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = mode
                archive.writestr(item, data)
    with zipfile.ZipFile(output) as archive:
        unchanged = [name for name in payloads if not name.startswith(OLD_INFO)]
        if any(archive.read(target_name(name)) != payloads[name] for name in unchanged):
            raise ValueError("code payload changed")
    return {"source_sha256": expected_hash, "wheel_sha256": digest(output.read_bytes()),
            "wheel": str(output), "version": VERSION, "unchanged_code_entries": len(unchanged),
            "metadata_replacements": REPLACEMENTS, "production_allowed": False}
