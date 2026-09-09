"""Parser observations preserve uncertainty and never evaluate configuration."""

import ast
import json

import pytest

from ladder_dragon.verification.architecture.cli_sites import parser_sites


@pytest.mark.parametrize("declaration,call", [
    ("import argparse", "argparse.ArgumentParser()"),
    ("import argparse as ap", "ap.ArgumentParser()"),
    ("from argparse import ArgumentParser", "ArgumentParser()"),
    ("from argparse import ArgumentParser as Factory", "Factory()"),
])
def test_constructor_aliases_are_observed(declaration, call):
    sites = parser_sites(ast.parse(declaration + "\np = " + call))
    assert [row["method"] for row in sites] == ["ArgumentParser"]
    assert all(len(row["ast_sha256"]) == 64 for row in sites)


def test_nested_conditional_and_class_sites_are_not_claimed_as_live():
    sites = parser_sites(ast.parse("""
if False:
    parser.add_argument('--unused')
def unused():
    parser.add_parser('unused')
class Factory:
    def build(self):
        parser.parse_args()
"""))
    assert [row["method"] for row in sites] == ["add_argument", "add_parser", "parse_args"]


def test_sensitive_defaults_and_unresolved_arguments_are_not_evaluated():
    sites = parser_sites(ast.parse("""
parser.add_argument('--option', default=read_private_state(), help='PRIVATE_MARKER')
parser.add_argument(*dynamic_arguments, **dynamic_defaults)
parser.set_defaults(value='FUTURE_MARKER')
"""))
    assert len(sites) == 3
    assert sites[0]["literal_string_count"] == 1
    assert sites[1]["expanded_arguments"] is True
    report = json.dumps(sites)
    for value in ("PRIVATE_MARKER", "FUTURE_MARKER", "read_private_state", "--option"):
        assert value not in report


def test_argument_changes_update_syntax_hash_without_approving_parity():
    first = parser_sites(ast.parse("p.add_argument('--size', default=1)"))[0]
    second = parser_sites(ast.parse("p.add_argument('--size', default=2)"))[0]
    assert first["ast_sha256"] != second["ast_sha256"]
    assert {key: value for key, value in first.items() if key != "ast_sha256"} == {
        key: value for key, value in second.items() if key != "ast_sha256"}


def test_name_matches_are_observations_not_provenance_checks():
    sites = parser_sites(ast.parse("""
from argparse import ArgumentParser
ArgumentParser = lambda: None
p = ArgumentParser()
unrelated.add_argument('value')
"""))
    assert len(sites) == 2


def test_dynamic_indirection_is_not_misrepresented_as_resolved():
    sites = parser_sites(ast.parse("""
getattr(parser, method)('value')
factory = parser.add_argument
factory('value')
"""))
    assert sites == []
