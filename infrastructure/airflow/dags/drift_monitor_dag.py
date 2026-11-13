"""
Airflow DAG: drift monitor — tự động kích hoạt retraining khi phát hiện data drift (IncidentIQ).

Tính toán PSI/KS giữa phân phối đặc trưng tham chiếu (reference) và phân phối hiện tại
(current) từ logs inferencing. Nếu có feature drift vượt ngưỡng, kích hoạt
model_retrain_pipeline qua Airflow REST API.

Credentials qua Airflow Variables (không hardcode):
  - AIRFLOW_VAR_DRIFT_REFERENCE_JSON
  - AIRFLOW_VAR_DRIFT_CURRENT_JSON
  - AIRFLOW_VAR_DRIFT_PSI_THRESHOLD (mặc định 0.2)
  - AIRFLOW_VAR_DRIFT_KS_THRESHOLD   (mặc định 0.2)
  - AIRFLOW_VAR_AIRFLOW_BASE_URL
  - AIRFLOW_VAR_AIRFLOW_TOKEN
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.models.variable import Variable

default_args = {
    "owner": "mlops",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=30),
}

PSI_DEFAULT = 0.2
KS_DEFAULT = 0.2


def _variable(name: str, default=None):
    return Variable.get(name, default_var=default)


def _json_variable(name: str, default=None):
    raw = _variable(name, default)
    if raw is None or raw == "":
        return default if default is not None else {}
    return json.loads(raw)


@dag(
    dag_id="incidentiq_drift_monitor_dag",
    default_args=default_args,
    schedule="*/30 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "drift", "retrain-trigger"],
)
def incidentiq_drift_monitor_dag() -> None:
    @task
    def evaluate_drift() -> dict:
        reference = _json_variable("DRIFT_REFERENCE_JSON", {})
        current = _json_variable("DRIFT_CURRENT_JSON", {})
        psi_threshold = float(_variable("DRIFT_PSI_THRESHOLD", PSI_DEFAULT))
        ks_threshold = float(_variable("DRIFT_KS_THRESHOLD", KS_DEFAULT))

        sys_path = ["/opt/incidentiq/ai"]
        for p in sys_path:
            if p not in sys.path:
                sys.path.insert(0, p)
        from drift_detection import detect_drift  # type: ignore

        results = detect_drift(
            reference,
            current,
            psi_threshold=psi_threshold,
            ks_threshold=ks_threshold,
        )
        drifted = {name: r.to_dict() for name, r in results.items() if r.drift_detected}
        return {
            "drift_detected": bool(drifted),
            "drifted_features": drifted,
            "psi_threshold": psi_threshold,
            "ks_threshold": ks_threshold,
        }

    @task
    def trigger_retrain(drift_report: dict) -> str:
        if not drift_report.get("drift_detected"):
            return "skipped: no drift detected"
        base_url = _variable("AIRFLOW_BASE_URL", "").rstrip("/")
        token = _variable("AIRFLOW_TOKEN", "")
        if not base_url or not token:
            raise RuntimeError("AIRFLOW_BASE_URL / AIRFLOW_TOKEN chưa cấu hình")
        url = f"{base_url}/api/v1/dags/incidentiq_model_retrain_pipeline/dagRuns"
        body = {
            "dag_run_id": f"drift_trigger_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "conf": {"reason": "drift_detected", "drift_report": drift_report},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"trigger retrain failed: HTTP {resp.status}")
            return f"triggered incidentiq_model_retrain_pipeline (drifted={list(drift_report['drifted_features'].keys())})"

    report = evaluate_drift()
    trigger_retrain(report)


incidentiq_drift_monitor_dag()
