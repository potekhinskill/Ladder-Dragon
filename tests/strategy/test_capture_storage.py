import os
from pathlib import Path

import pytest

from ladder_dragon.strategy.capture_storage import prepare_slot, check_slots, SLOT_BYTES
from tests.strategy.test_bnb_capture import Response, row, run


def test_two_runs_preserve_first(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, [Response([row()])])
    first = tmp_path/'bnb-public-capture'/'observations.jsonl'
    before = first.read_bytes()
    run(tmp_path, monkeypatch, [Response([row()])], slot='signed-test')
    assert first.read_bytes() == before
    assert (tmp_path/'bnb-public-capture-signed-test'/'observations.jsonl').exists()
    with pytest.raises(FileExistsError):
        run(tmp_path, monkeypatch, [Response([row()])], slot='signed-test')
    assert first.read_bytes() == before


@pytest.mark.parametrize('slot', ['third', '../escape', '/tmp', '', None])
def test_only_two_names(tmp_path, slot):
    with pytest.raises(ValueError):
        prepare_slot(tmp_path, slot)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('kind', ['directory_link', 'file_link', 'directory', 'unknown', 'hardlink'])
def test_reject_unsafe_existing_slot(tmp_path, kind):
    old = tmp_path/'bnb-public-capture'
    outside = tmp_path/'outside'
    outside.mkdir()
    if kind == 'directory_link':
        old.symlink_to(outside, target_is_directory=True)
    else:
        old.mkdir()
        target = old/'observations.jsonl'
        if kind == 'file_link':
            target.symlink_to(outside/'missing')
        elif kind == 'directory':
            target.mkdir()
        elif kind == 'unknown':
            (old/'unexpected').touch()
        else:
            (outside/'file').touch()
            os.link(outside/'file', target)
    with pytest.raises(ValueError):
        prepare_slot(tmp_path, 'signed-test')
    assert not (tmp_path/'bnb-public-capture-signed-test').exists()


def test_full_old_slot_blocks_new_without_deleting(tmp_path):
    folder = prepare_slot(tmp_path, 'original')
    file = folder/'observations.jsonl'
    with file.open('wb') as output:
        output.truncate(SLOT_BYTES+1)
    with pytest.raises(ValueError, match='CAPACITY'):
        prepare_slot(tmp_path, 'signed-test')
    assert file.stat().st_size == SLOT_BYTES+1


def test_capacity_boundary_and_two_slot_total(tmp_path):
    for slot in ('original', 'signed-test'):
        folder = prepare_slot(tmp_path, slot)
        with (folder/'observations.jsonl').open('wb') as output:
            output.truncate(SLOT_BYTES)
    assert check_slots(tmp_path) == 2*SLOT_BYTES


def test_insufficient_space_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ladder_dragon.strategy import bnb_capture
    original_stat = Path.stat
    def fake_stat(path, **kwargs):
        result = original_stat(path, **kwargs)
        if path == tmp_path:
            values = list(result)
            values[2] = original_stat(Path('/')).st_dev+1
            return os.stat_result(values)
        return result
    monkeypatch.setattr(Path, 'stat', fake_stat)
    monkeypatch.setattr(bnb_capture.os.path, 'ismount', lambda _: True)
    monkeypatch.setattr(bnb_capture.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    with pytest.raises(ValueError, match='DISK_RESERVE'):
        bnb_capture.external_store(tmp_path)
    assert list(tmp_path.iterdir()) == []
