"""Synthetic CLI dispatch only; never start the real diagnostic worker."""
import json

import pytest

from ladder_dragon.strategy import diagnostic_cli as cli


def args():
    return ['--confirmed', '--expected-code-sha', 'a'*40, '--expected-device', '123',
            '--manifest-sha256', 'b'*64]


@pytest.mark.parametrize('arguments,stage', [([], 'authorization'),
    (['--confirmed'], 'input'), (['--unknown', 'SENTINEL'], 'input'),
    (['--conf'], 'input'), (args()+['--api-secret', 'SENTINEL'], 'input')])
def test_invalid_arguments_never_dispatch(arguments, stage, monkeypatch, capsys):
    monkeypatch.setattr(cli.launch, 'run', lambda value: pytest.fail('dispatch'))
    assert cli.main(arguments) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)['stage'] == stage
    assert 'SENTINEL' not in captured.out + captured.err


def test_no_terminal_never_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'terminal_available', lambda: False)
    monkeypatch.setattr(cli.launch, 'run', lambda value: pytest.fail('dispatch'))
    assert cli.main(args()) == 2
    assert json.loads(capsys.readouterr().out)['stage'] == 'host'


@pytest.mark.parametrize('stage', ['deadline', 'complete'])
def test_dispatch_once_to_bounded_parent(stage, monkeypatch, capsys):
    calls = []
    def run(value):
        calls.append(value)
        return cli.launch.report(stage, **(dict(bytes=123, ciphertext_sha256='c'*64) if stage == 'complete' else {}))
    monkeypatch.setattr(cli, 'terminal_available', lambda: True)
    monkeypatch.setattr(cli.launch, 'run', run)
    assert cli.main(args()) == (0 if stage == 'complete' else 2)
    result = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and calls[0] == dict(confirmed=True, expected_code_sha='a'*40,
        expected_device=123, manifest_sha256='b'*64)
    assert result['collection_allowed'] is False and result['replay_allowed'] is False


def test_terminal_failure(monkeypatch):
    def unavailable(*args):
        raise OSError
    monkeypatch.setattr(cli.os, 'open', unavailable)
    assert cli.terminal_available() is False


def test_terminal_descriptor_closed(monkeypatch):
    closed = []
    monkeypatch.setattr(cli.os, 'open', lambda *args: 999)
    monkeypatch.setattr(cli.os, 'isatty', lambda fd: fd == 999)
    monkeypatch.setattr(cli.os, 'close', closed.append)
    assert cli.terminal_available() is True and closed == [999]
