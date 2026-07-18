import os
import sys

import pytest

from bin import tools_cancel_open


def parse(monkeypatch, *arguments):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tools_cancel_open.py", "--pairs", "SOLUSDT", *arguments],
    )
    return tools_cancel_open.parse_args()


def test_cancel_tool_defaults_to_testnet_dry(monkeypatch):
    args = parse(monkeypatch)
    assert args.testnet is True
    assert args.live is False
    assert args.base_url == tools_cancel_open.DEFAULT_TEST


def test_cancel_tool_live_requires_confirmation(monkeypatch):
    monkeypatch.delenv("BOT_LIVE_CONFIRMED", raising=False)
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--live")
    assert exc.value.code == 2


def test_cancel_tool_mainnet_requires_second_confirmation(monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.delenv("BOT_MAINNET_CANCEL_CONFIRMED", raising=False)
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--mainnet", "--live")
    assert exc.value.code == 2


def test_cancel_tool_rejects_custom_key_exfiltration_endpoint(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        parse(monkeypatch, "--base-url", "https://attacker.example")
    assert exc.value.code == 2


def test_cancel_tool_accepts_explicitly_confirmed_mainnet(monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    monkeypatch.setenv("BOT_MAINNET_CANCEL_CONFIRMED", "YES")
    args = parse(monkeypatch, "--mainnet", "--live")
    assert args.testnet is False
    assert args.base_url == tools_cancel_open.DEFAULT_MAIN
