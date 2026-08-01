"""Positive fixtures for Ladder Dragon Semgrep rules. This file is not executed."""

import os
import pickle
import subprocess
import tempfile
from decimal import Decimal

import requests
import yaml


def unsafe(data, command, url):
    # ruleid: ladder-dragon.no-broad-exception-pass
    try:
        operation()
    except Exception:
        pass
    # ruleid: ladder-dragon.no-shell-true
    subprocess.run(command, shell=True)
    # ruleid: ladder-dragon.no-os-system
    os.system(command)
    # ruleid: ladder-dragon.no-eval
    eval(data)
    # ruleid: ladder-dragon.no-exec
    exec(data)
    # ruleid: ladder-dragon.no-unsafe-pickle
    pickle.loads(data)
    # ruleid: ladder-dragon.no-unsafe-yaml-loader
    yaml.load(data, Loader=yaml.Loader)
    # ruleid: ladder-dragon.no-disabled-tls-verification
    requests.get(url, timeout=5, verify=False)
    # ruleid: ladder-dragon.no-insecure-tempfile-mktemp
    tempfile.mktemp()
    # ruleid: ladder-dragon.requests-require-timeout
    requests.post(url, json={"ok": True})
    # ruleid: ladder-dragon.no-decimal-from-float
    Decimal(float(data))


def operation():
    raise RuntimeError("fixture")
