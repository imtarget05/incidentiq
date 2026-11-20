"""
Model registry cho Option B — AI/MLOps (IncidentIQ).

Lưu metadata mô hình đã huấn luyện (incident triage): URI, SHA-256, version, chất lượng,
thời điểm, trạng thái (candidate/production/archived). Chỉ stdlib.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class ModelVersion:
    model_id: str
    version: str
    adapter_uri: str
    sha256: str
    created_at: str
    status: str = "candidate"
    metrics: dict[str, float] = field(default_factory=dict)
    promoted_by: Optional[str] = None
    promoted_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelRegistry:
    def __init__(self, registry_path: str = "/opt/incidentiq/finetune/registry.json",
                 registry_root: str = "/opt/incidentiq/finetune"):
        root = Path(registry_root).resolve()
        path = Path(registry_path).resolve()
        if not path.is_relative_to(root) or path.suffix != ".json":
            raise ValueError("registry path must be a JSON file inside the registry root")
        self.path = path
        root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        # Replace the directory entry atomically, so a symlink planted at the
        # target cannot redirect the write outside the checked registry root.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".registry-", suffix=".tmp", delete=False) as stream:
                temp_path = Path(stream.name)
                os.chmod(temp_path, 0o600)
                json.dump(data, stream, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def register(
        self,
        model_id: str,
        version: str,
        adapter_uri: str,
        sha256: str,
        metrics: dict[str, float],
        status: str = "candidate",
    ) -> ModelVersion:
        now = datetime.now(timezone.utc).isoformat()
        mv = ModelVersion(
            model_id=model_id,
            version=version,
            adapter_uri=adapter_uri,
            sha256=sha256,
            created_at=now,
            status=status,
            metrics=metrics,
        )
        data = self._load()
        data.setdefault(model_id, [])
        data[model_id].append(mv.to_dict())
        self._save(data)
        return mv

    def promote(self, model_id: str, version: str, promoted_by: str) -> Optional[ModelVersion]:
        data = self._load()
        versions = data.get(model_id, [])
        for mv in versions:
            mv["status"] = "archived" if mv["version"] == version else mv["status"]
            if mv["version"] == version:
                mv["status"] = "production"
                mv["promoted_by"] = promoted_by
                mv["promoted_at"] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        for mv in versions:
            if mv["version"] == version:
                return ModelVersion(**mv)
        return None

    def get_production(self, model_id: str) -> Optional[ModelVersion]:
        data = self._load()
        for mv in data.get(model_id, []):
            if mv.get("status") == "production":
                return ModelVersion(**mv)
        return None

    def list_versions(self, model_id: str) -> list[ModelVersion]:
        data = self._load()
        return [ModelVersion(**mv) for mv in data.get(model_id, [])]

    @staticmethod
    def sha256_file(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
