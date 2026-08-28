#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: recover host networking with bounded, persistent reboot authority.
"""Bounded host recovery; never reads exchange, trading, or Telegram secrets."""

import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time


REBOOT_AFTER = 900
REARM_AFTER = 1800
REBOOT_COOLDOWN = 86400
LOCK = Path("/var/lib/ladder-dragon/network-recovery.lock")
PENDING = Path("/var/lib/pi-watchdog/network-reboot.boot")
MAINTENANCE = Path("/var/lib/ladder-dragon/maintenance.json")


def fresh_state(boot: str) -> dict:
    return dict(schema_version=1, boot=boot, seen=0, failed_since=-1,
                healthy_since=-1, step=0, latched=False, last_reboot=0,
                incident=0, blocked="")


def read_state(path: Path, boot: str) -> dict:
    if not path.exists():
        return fresh_state(boot)
    with path.open() as source:
        state = json.loads(source.read(4097))
    expected = fresh_state(boot)
    if (not isinstance(state, dict) or set(state) != set(expected)
            or any(type(state[k]) is not type(v) for k, v in expected.items())
            or state["schema_version"] != 1 or state["step"] not in range(4)
            or any(state[k] < -1 for k in ("seen", "failed_since", "healthy_since"))
            or state["last_reboot"] < 0 or state["incident"] < 0):
        raise ValueError("invalid recovery state")
    return state


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        os.chmod(temporary, 0o600)
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def advance(state: dict, *, boot: str, now: int, uptime: int,
            reachable: bool, blocked: str) -> tuple[str, list[str]]:
    """Use continuous monotonic observations, with a durable reboot latch."""
    events = []
    if state["boot"] != boot:
        if state["latched"]:
            events.append("boot-observed")
            if reachable:
                events.append("network-restored")
        state.update(boot=boot, seen=0, failed_since=-1, healthy_since=-1, step=0)
    if uptime < state["seen"] or uptime - state["seen"] > 180:
        # A stopped timer or maintenance gap is not evidence of continuous loss.
        state.update(failed_since=-1, healthy_since=-1, step=0)
    state["seen"] = uptime
    if reachable:
        if state["failed_since"] >= 0:
            events.append("network-restored")
        state.update(failed_since=-1, step=0, blocked="")
        if state["healthy_since"] < 0:
            state["healthy_since"] = uptime
        if (uptime - state["healthy_since"] >= REARM_AFTER
                and now - state["last_reboot"] >= REBOOT_COOLDOWN):
            state["latched"] = False
        return "none", events
    state["healthy_since"] = -1
    if blocked:
        if state["blocked"] != blocked:
            events.append("recovery-deferred:" + blocked)
        state["blocked"] = blocked
        # Require a new complete observation window after protected work.
        state.update(failed_since=-1, step=0)
        return "none", events
    state["blocked"] = ""
    if state["failed_since"] < 0:
        state.update(failed_since=uptime, incident=now)
        events.append("network-lost")
    elapsed = uptime - state["failed_since"]
    if elapsed >= REBOOT_AFTER and state["step"] < 3:
        if state["latched"] or (state["last_reboot"] and
                                now - state["last_reboot"] < REBOOT_COOLDOWN):
            if state["step"] != 3:
                events.append("reboot-suppressed")
            state["step"] = 3
            return "none", events
        state.update(step=3, latched=True, last_reboot=now)
        return "reboot", events
    if elapsed >= 480 and state["step"] < 2:
        state["step"] = 2
        return "restart-network", events
    if elapsed >= 180 and state["step"] < 1:
        state["step"] = 1
        return "reconnect", events
    return "none", events


def run(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess:
    # Never expose command stderr, which can contain private connection details.
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=timeout, check=False,
                          env={"PATH": os.defpath + ":/usr/sbin:/sbin", "LC_ALL": "C"})


def tcp_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def network_reachable() -> bool:
    routes = run(["ip", "-j", "-4", "route", "show", "default"])
    if routes.returncode:
        raise RuntimeError("route probe unavailable")
    parsed = json.loads(routes.stdout)
    if not isinstance(parsed, list) or any(not isinstance(row, dict) for row in parsed):
        raise ValueError("invalid route probe")
    for route in parsed:
        gateway = route.get("gateway")
        if gateway:
            gateway = str(ipaddress.IPv4Address(gateway))
            if (run(["ping", "-n", "-c", "1", "-W", "1", gateway]).returncode == 0
                    or tcp_probe(gateway, 443) or tcp_probe(gateway, 80)):
                return True
    # An ICMP-blocking gateway must not trigger a reboot while routing works.
    return tcp_probe("1.1.1.1", 443) or tcp_probe("8.8.8.8", 443)


def safety_blocker() -> str:
    if MAINTENANCE.exists():
        try:
            with MAINTENANCE.open() as source:
                value = json.loads(source.read(4097))
            if value.get("schema_version") != 1 or type(value.get("active")) is not bool:
                return "maintenance-invalid"
            if value["active"]:
                return "maintenance-active"
        except (OSError, ValueError, AttributeError):
            return "maintenance-invalid"
    # Legacy SD imaging lacks the shared lock. Never race its scheduled start.
    units = run(["systemctl", "show", "ladder-dragon-backup.service",
                 "pi-sd-backup.service", "pi-sd-backup.timer",
                 "--property=ActiveState", "--value"])
    if units.returncode or len(units.stdout.split()) != 3:
        return "backup-state-unavailable"
    if any(s not in {"inactive", "failed"} for s in units.stdout.split()):
        return "backup-active"
    for command in (["nmcli", "radio", "wifi"], ["nmcli", "networking"]):
        status = run(command)
        if status.returncode or status.stdout.strip() != "enabled":
            return "network-administratively-disabled"
    return ""


MESSAGES = {
    "network-lost": "⚠️ Pi network lost. Recovery timer started; reboot threshold: 15 minutes.",
    "network-restored": "✅ Pi network restored. No further network recovery action is needed.",
    "boot-observed": "🔁 Pi boot observed after an automatic reboot request. Network is being checked.",
    "reconnect": "🔧 Pi network unavailable for 3 minutes. Reactivating a saved Wi-Fi connection.",
    "restart-network": "🔧 Pi network unavailable for 8 minutes. Restarting NetworkManager.",
    "reboot": "⚠️ Pi network unavailable for 15 minutes. Requesting one controlled reboot.",
    "reboot-suppressed": "🛑 Pi reboot suppressed by the persistent anti-loop limit. Operator check required.",
}


def notify(outbox: Path, event: str, incident: int, now: int) -> None:
    """Derived alerts share the existing 288-file, 24-hour Telegram outbox."""
    outbox.mkdir(mode=0o700, parents=True, exist_ok=True)
    paths = sorted(outbox.glob("*.msg"))
    for path in paths[:-287]:
        path.unlink()
    label = event.replace(":", "-")
    text = MESSAGES.get(event, "⚠️ Pi network recovery: " + event)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now))
    atomic_write(outbox / f"{now}-network-{incident}-{label}.msg", f"{stamp}\n{text}\n")


def cycle(directory: Path, outbox: Path) -> None:
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    uptime = int(time.monotonic())
    now = int(time.time())
    state_path = directory / "network-recovery.json"
    state = read_state(state_path, boot)
    reachable = network_reachable()
    with LOCK.open("a+") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            blocker = "backup-or-update-locked"
        else:
            blocker = safety_blocker() if not reachable else ""
        action, events = advance(state, boot=boot, now=now, uptime=uptime,
                                 reachable=reachable, blocked=blocker)
        for event in events + ([action] if action != "none" else []):
            notify(outbox, event, state["incident"], now)
        # Persist authority and its notification before any disruptive action.
        atomic_write(state_path, json.dumps(state, sort_keys=True) + "\n")
        if action == "none":
            return
        # Recheck connectivity and maintenance at the actual mutation boundary.
        if network_reachable() or safety_blocker():
            notify(outbox, "action-cancelled-after-recheck", state["incident"], now)
            return
        commands = {
            "reconnect": ["nmcli", "--wait", "20", "connection", "up", "ifname", "wlan0"],
            "restart-network": ["systemctl", "restart", "NetworkManager.service"],
            "reboot": ["systemctl", "--check-inhibitors=yes", "--no-ask-password", "reboot"],
        }
        if action == "reboot":
            atomic_write(PENDING, boot + "\n")
        try:
            result = run(commands[action], timeout=30)
        except (OSError, subprocess.SubprocessError):
            # An unacknowledged reboot may already be scheduled. Keep its latch.
            notify(outbox, action + "-result-unknown", state["incident"], now)
            return
        if result.returncode:
            if action == "reboot":
                PENDING.unlink(missing_ok=True)
            notify(outbox, action + "-failed", state["incident"], now)


def main() -> int:
    global MAINTENANCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--maintenance-file", type=Path, default=MAINTENANCE)
    args = parser.parse_args()
    MAINTENANCE = args.maintenance_file
    try:
        cycle(args.state_dir, args.outbox)
    except (OSError, ValueError, RuntimeError, TypeError, subprocess.SubprocessError):
        # Fail closed: corrupted observations cannot authorize host mutations.
        print("[network-recovery] BLOCKED: probe or persistent state unavailable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
