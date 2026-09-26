import pytest

from ladder_dragon.strategy import bnb_capture_command as command
from tests.strategy.test_capture_credentials import credential


@pytest.mark.parametrize('options', [[], ['--signing-credential', '/not-read'],
    ['--trusted-key-sha256', '0'*64], ['--clock-ttl-ms', '0']])
def test_incomplete_signing_blocks_before_key_or_network(monkeypatch, capsys, options):
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', '/unused', '--slot', 'signed-test']+options)
    def forbidden(*args, **kwargs):
        pytest.fail('key or network accessed')
    monkeypatch.setattr(command, 'load_capture_key', forbidden)
    monkeypatch.setattr(command, 'collect', forbidden)
    assert command.main() == 2
    assert 'BLOCKED' in capsys.readouterr().out


def test_signed_command_loads_pinned_key_and_routes_slot(credential, monkeypatch, capsys):
    path, pin, expected = credential
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', '/unused', '--slot', 'signed-test',
        '--signing-credential', str(path), '--trusted-key-sha256', pin, '--collector-id', 'test',
        '--clock-max-uncertainty-ms', '10', '--clock-ttl-ms', '30000', '--clock-drift-ppm', '100'])
    def collect(root, **kwargs):
        assert root == '/unused' and kwargs['slot'] == 'signed-test'
        signer = kwargs['attestor']
        assert signer.private_key.sign(b'test') == expected.sign(b'test')
        assert signer.policy['max_uncertainty_ns'] == 10000000
        return {'status': 'DIAGNOSTIC_ONLY', 'replay_allowed': False}
    monkeypatch.setattr(command, 'collect', collect)
    assert command.main() == 0
    output = capsys.readouterr().out
    assert 'PRIVATE KEY' not in output and str(path) not in output


def test_bad_key_error_never_prints_parser_details(credential, monkeypatch, capsys):
    path, pin, _ = credential
    path.write_bytes(b'PRIVATE_TEST_MARKER')
    monkeypatch.setattr('sys.argv', ['record', '--external-mount', '/unused', '--slot', 'signed-test',
        '--signing-credential', str(path), '--trusted-key-sha256', pin, '--collector-id', 'test',
        '--clock-max-uncertainty-ms', '10', '--clock-ttl-ms', '30000', '--clock-drift-ppm', '100'])
    assert command.main() == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_TEST_MARKER' not in output and str(path) not in output
