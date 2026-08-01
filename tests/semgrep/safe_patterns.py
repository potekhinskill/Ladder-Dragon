"""Negative fixtures for Ladder Dragon Semgrep rules. This file is not executed."""

import subprocess
import tempfile
from decimal import Decimal

import requests
import yaml


def safe(data, command, url):
    try:
        operation()
    except RuntimeError:
        report_safe_failure()
    subprocess.run(command, check=False)
    yaml.safe_load(data)
    requests.get(url, timeout=5)
    tempfile.NamedTemporaryFile()
    return Decimal(str(data))


def operation():
    raise RuntimeError("fixture")


def report_safe_failure():
    return None
