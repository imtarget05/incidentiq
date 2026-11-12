import pytest
from pydantic import ValidationError

from schemas import IncidentCreate, IncidentStatusUpdate, QuestionRequest, WorkspaceCreate


def test_incident_fields_are_normalized() -> None:
    incident = IncidentCreate(title="  Outage  ", severity=" high ", service=" api ", environment=" prod ")
    assert (incident.title, incident.severity, incident.service, incident.environment) == (
        "Outage", "HIGH", "api", "prod"
    )


@pytest.mark.parametrize("field,value", [
    ("title", "   "), ("service", "   "), ("environment", "   "), ("severity", "urgent"),
])
def test_incident_rejects_invalid_fields(field: str, value: str) -> None:
    payload = {"title": "Outage", "severity": "HIGH", "service": "api", "environment": "prod"}
    payload[field] = value
    with pytest.raises(ValidationError):
        IncidentCreate(**payload)


def test_status_and_question_validate_user_input() -> None:
    assert IncidentStatusUpdate(status=" resolved ").status == "RESOLVED"
    with pytest.raises(ValidationError):
        IncidentStatusUpdate(status="deleted")
    assert QuestionRequest(question="  What happened?  ").question == "What happened?"
    with pytest.raises(ValidationError):
        QuestionRequest(question="  ")
    assert WorkspaceCreate(name="  Ops  ").name == "Ops"
    with pytest.raises(ValidationError):
        WorkspaceCreate(name="  ")
