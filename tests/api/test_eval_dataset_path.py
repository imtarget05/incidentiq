from pathlib import Path

import pytest

from scripts.eval_harness import resolve_dataset_path


def test_eval_dataset_defaults_to_repo_data() -> None:
    path = resolve_dataset_path(None)
    assert path.name == "rag_eval_dataset.json"
    assert path.parent.name == "data"


def test_eval_dataset_rejects_path_outside_data() -> None:
    with pytest.raises(ValueError, match="inside the data directory"):
        resolve_dataset_path("../../private.json")


def test_eval_dataset_rejects_symlink_escape(tmp_path: Path) -> None:
    data_dir = resolve_dataset_path(None).parent
    link = data_dir / "eval-test-symlink.json"
    link.symlink_to(tmp_path / "private.json")
    try:
        with pytest.raises(ValueError, match="inside the data directory"):
            resolve_dataset_path(link.name)
    finally:
        link.unlink()
