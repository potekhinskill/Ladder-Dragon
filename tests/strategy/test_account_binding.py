import json

import pytest

from ladder_dragon.strategy import account_binding as binding


def inputs():
    permissions = {key: False for key in binding.BOOLEAN_FIELDS}
    permissions.update(enableReading=True, createTime=12345)
    return dict(expected_uid=123456789, expected_scope="a" * 64,
                account_scope="a" * 64, permission_scope="a" * 64,
                account_body=json.dumps({"uid": 123456789, "canTrade": True,
                    "canWithdraw": True, "balances": [{"private": "SENTINEL"}]}).encode(),
                permission_body=json.dumps(permissions).encode())


def test_matches_are_not_authentication_or_admission():
    supplied = inputs()
    before = dict(supplied)
    result = binding.validate_account_claims(**supplied)
    assert result == dict(status="CLAIMS_MATCH_ONLY", reason="MATCH",
                         account_authenticated=False, private_fills_authenticated=False,
                         replay_allowed=False)
    assert supplied == before
    assert "SENTINEL" not in repr(result)
    assert str(supplied["expected_uid"]) not in repr(result)
    assert supplied["expected_scope"] not in repr(result)


@pytest.mark.parametrize("uid", [None, True, 0, -1, 2**63, "123456789", 1.5])
def test_invalid_expected_identity(uid):
    data = inputs(); data["expected_uid"] = uid
    assert binding.validate_account_claims(**data)["reason"] == "BINDING_INVALID"


@pytest.mark.parametrize("key", ["expected_scope", "account_scope", "permission_scope"])
@pytest.mark.parametrize("value", [None, "A"*64, "a"*63, "../SENTINEL", "b"*64])
def test_scope_validation_and_mixed_credentials(key, value):
    data = inputs(); data[key] = value
    assert binding.validate_account_claims(**data)["status"] == "BLOCKED"


@pytest.mark.parametrize("body", [b'{}', b'{"uid":true}', b'{"uid":"123456789"}',
    b'{"uid":0}', b'{"uid":987654321}', b'{"uid":123456789,"code":0}'])
def test_foreign_or_invalid_response_identity(body):
    data = inputs(); data["account_body"] = body
    assert binding.validate_account_claims(**data)["status"] == "BLOCKED"


@pytest.mark.parametrize("field", sorted(binding.MUTATION_FIELDS))
def test_each_mutating_permission_blocks(field):
    data = inputs(); permission = json.loads(data["permission_body"])
    permission[field] = True; data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "MUTATION_PERMISSION_ENABLED"


@pytest.mark.parametrize("field", sorted(binding.BOOLEAN_FIELDS | {"createTime"}))
def test_each_required_field_is_required(field):
    data = inputs(); permission = json.loads(data["permission_body"])
    del permission[field]; data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "PERMISSION_SCHEMA_INVALID"


@pytest.mark.parametrize("field", sorted(binding.BOOLEAN_FIELDS))
@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_boolean_truthiness_is_not_accepted(field, value):
    data = inputs(); permission = json.loads(data["permission_body"])
    permission[field] = value; data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "PERMISSION_SCHEMA_INVALID"


@pytest.mark.parametrize("extra", ["enableNewTrading", "replay_allowed", "code"])
def test_unknown_permission_schema_blocks(extra):
    data = inputs(); permission = json.loads(data["permission_body"])
    permission[extra] = False; data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "PERMISSION_SCHEMA_INVALID"


def test_reading_is_required():
    data = inputs(); permission = json.loads(data["permission_body"])
    permission["enableReading"] = False
    data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "READ_PERMISSION_REQUIRED"


@pytest.mark.parametrize("value", [None, True, 0, -1, 2**63, "12345", 1.5])
def test_permission_creation_time_is_strict(value):
    data = inputs(); permission = json.loads(data["permission_body"])
    permission["createTime"] = value
    data["permission_body"] = json.dumps(permission).encode()
    assert binding.validate_account_claims(**data)["reason"] == "PERMISSION_SCHEMA_INVALID"


def test_no_network_or_file_access(monkeypatch):
    import builtins
    import socket
    data = inputs()
    def forbidden(*args, **kwargs):
        pytest.fail("pure validator attempted external access")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert binding.validate_account_claims(**data)["reason"] == "MATCH"


@pytest.mark.parametrize("key", ["account_body", "permission_body"])
@pytest.mark.parametrize("body", [None, "SENTINEL", b'', b'[]', b'null', b'\xff',
    b'{"uid":123456789,"uid":123456789}', b'{"uid":123456789,"nested":{"x":0,"x":0}}',
    b'{"uid":123456789,"value":NaN}', b'{"uid":123456789,"value":Infinity}',
    b'{"uid":123456789,"value":1e999999999999999999999999}',
    b'{"secret":"SENTINEL"', b'[' * 2000 + b']' * 2000])
def test_malformed_input_is_bounded_and_secret_safe(key, body):
    data = inputs(); data[key] = body
    result = binding.validate_account_claims(**data)
    assert result["status"] == "BLOCKED"
    assert "SENTINEL" not in repr(result)
    assert not result["account_authenticated"] and not result["replay_allowed"]


@pytest.mark.parametrize("key,limit", [("account_body", binding.MAX_ACCOUNT_BYTES),
                                     ("permission_body", binding.MAX_PERMISSION_BYTES)])
def test_byte_ceiling_boundary(key, limit):
    data = inputs(); raw = data[key]
    data[key] = raw + b' ' * (limit-len(raw))
    assert binding.validate_account_claims(**data)["reason"] == "MATCH"
    data[key] += b' '
    assert binding.validate_account_claims(**data)["status"] == "BLOCKED"
