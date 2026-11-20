import pytest

from api.src.model_registry import ModelRegistry


def test_registry_rejects_parent_traversal_and_symlink(tmp_path):
    root = tmp_path / "registry"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        ModelRegistry(str(root / ".." / "outside.json"), str(root))

    (root / "linked.json").symlink_to(outside)
    with pytest.raises(ValueError):
        ModelRegistry(str(root / "linked.json"), str(root))


def test_registry_write_does_not_follow_replaced_target_symlink(tmp_path):
    root = tmp_path / "registry"
    registry = ModelRegistry(str(root / "registry.json"), str(root))
    outside = tmp_path / "outside.json"
    outside.write_text("private", encoding="utf-8")
    registry.path.unlink()
    registry.path.symlink_to(outside)

    registry._save({})
    version = registry.register("triage", "1", "local://adapter", "a" * 64,
                                {"f1": 0.8})

    assert version.version == "1"
    assert outside.read_text(encoding="utf-8") == "private"
    assert registry.path.is_file() and not registry.path.is_symlink()
    assert registry.get_production("triage") is None
    assert registry.promote("triage", "1", "reviewer").status == "production"
    assert len(registry.list_versions("triage")) == 1
