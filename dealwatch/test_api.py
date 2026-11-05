import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test-dealwatch.sqlite3"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["DEALWATCH_SETUP_SECRET"] = "test-setup-secret-value"
os.environ["TEAM_TIMEZONE"] = "Asia/Manila"

import api
from database import Base, ScanRecord, ScanRun, SessionLocal, engine


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    monkeypatch.setattr(api, "get_sf", lambda: object())
    with TestClient(api.app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    database_file = Path("test-dealwatch.sqlite3")
    if database_file.exists():
        database_file.unlink()


def test_signup_verification_roles_and_record_visibility(client, monkeypatch):
    verification_links = []
    monkeypatch.setattr(
        api,
        "send_verification_email",
        lambda sf, recipient, url: verification_links.append((recipient, url)) or True,
    )

    manager_response = client.post(
        "/api/auth/bootstrap-manager",
        json={
            "name": "Sales Manager",
            "email": "manager@example.com",
            "password": "a-very-long-manager-password",
            "setup_secret": "test-setup-secret-value",
        },
    )
    assert manager_response.status_code == 201
    assert manager_response.json()["role"] == "manager"

    registration = client.post(
        "/api/auth/register",
        json={
            "name": "Sales Rep",
            "email": "rep@example.com",
            "password": "a-very-long-rep-password",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["status"] == "verification_required"
    assert verification_links[0][0] == "rep@example.com"

    verification_token = parse_qs(urlparse(verification_links[0][1]).query)["verify"][0]
    pending_login = client.post(
        "/api/auth/login",
        json={"email": "rep@example.com", "password": "a-very-long-rep-password"},
    )
    assert pending_login.status_code == 403

    verified = client.post("/api/auth/verify-email", json={"token": verification_token})
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert client.post(
        "/api/auth/verify-email",
        json={"token": verification_token},
    ).status_code == 200

    pending_users = client.get("/api/admin/registrations")
    assert [user["email"] for user in pending_users.json()] == ["rep@example.com"]
    rep_id = pending_users.json()[0]["id"]
    approval = client.patch(
        f"/api/admin/users/{rep_id}",
        json={"status": "approved", "role": "rep"},
    )
    assert approval.status_code == 200

    scan_id = "scan-for-permission-test"
    own_record_id = "own-record-for-test"
    other_record_id = "other-record-for-test"
    with SessionLocal() as db:
        db.add(
            ScanRun(
                id=scan_id,
                status="completed",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )
        for item_id, email, rank in (
            (own_record_id, "rep@example.com", 1),
            (other_record_id, "other@example.com", 2),
        ):
            db.add(
                ScanRecord(
                    id=item_id,
                    scan_id=scan_id,
                    salesforce_id=f"sf-{item_id}",
                    record_type="Lead",
                    name=item_id,
                    owner_id="005000000000001",
                    owner_name="A Sales Rep",
                    owner_email=email,
                    payload={
                        "id": f"sf-{item_id}",
                        "type": "Lead",
                        "reasons": [],
                        "owner_id": "005000000000001",
                        "owner_name": "A Sales Rep",
                        "owner_email": email,
                    },
                    analysis={
                        "id": f"sf-{item_id}",
                        "name": item_id,
                        "risk_level": "High",
                        "root_cause": "No recent contact",
                        "recommended_action": "Follow up",
                    },
                    priority={
                        "id": f"sf-{item_id}",
                        "name": item_id,
                        "rank": rank,
                        "score": 85,
                        "reason": "Needs attention",
                    },
                    draft={
                        "id": f"sf-{item_id}",
                        "name": item_id,
                        "task_subject": "Follow up",
                        "task_description": "Contact the customer.",
                        "alert_message": "Follow up soon.",
                    },
                )
            )
        db.commit()

    with TestClient(api.app) as rep_client:
        rep_login = rep_client.post(
            "/api/auth/login",
            json={"email": "rep@example.com", "password": "a-very-long-rep-password"},
        )
        assert rep_login.status_code == 200

        rep_queue = rep_client.get("/api/scans/latest")
        assert rep_queue.status_code == 200
        assert [item["item_id"] for item in rep_queue.json()["records"]] == [own_record_id]
        assert rep_queue.json()["schedule"]["frequency"] == "weekdays"
        assert rep_queue.json()["schedule"]["timezone"] == "Asia/Manila"

        forbidden_action = rep_client.post(f"/api/records/{other_record_id}/skip")
        assert forbidden_action.status_code == 403
        allowed_action = rep_client.post(f"/api/records/{own_record_id}/skip")
        assert allowed_action.status_code == 200
        assert allowed_action.json()["action_status"] == "skipped"

    manager_queue = client.get("/api/scans/latest")
    assert len(manager_queue.json()["records"]) == 2

    created = {}
    monkeypatch.setattr(
        api,
        "create_task",
        lambda sf, record, draft, priority: created.update(
            record=record,
            subject=draft.task_subject,
            priority=priority.score,
        ) or "00T000000000001",
    )
    monkeypatch.setattr(api, "send_email_alert", lambda *args, **kwargs: True)
    approved = client.post(
        f"/api/records/{other_record_id}/approve",
        json={
            "task_subject": "Edited follow-up",
            "task_description": "Call the customer tomorrow.",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["action_status"] == "approved"
    assert approved.json()["email_status"] == "sent"
    assert created["record"]["owner_id"] == "005000000000001"
    assert created["subject"] == "Edited follow-up"


def test_scheduled_scan_saves_empty_result(client, monkeypatch):
    monkeypatch.setattr(api, "run_detection", lambda: [])
    scan_id = api._run_scan()
    with SessionLocal() as db:
        scan = db.get(ScanRun, scan_id)
        assert scan.status == "completed"
        assert scan.error_message is None


def test_manager_can_run_scan_from_api(client, monkeypatch):
    manager = client.post(
        "/api/auth/bootstrap-manager",
        json={
            "name": "Sales Manager",
            "email": "manager@example.com",
            "password": "a-very-long-manager-password",
            "setup_secret": "test-setup-secret-value",
        },
    )
    assert manager.status_code == 201
    monkeypatch.setattr(api, "run_detection", lambda: [])

    response = client.post("/api/scans/run", json={})

    assert response.status_code == 200
    assert response.json()["scan"]["status"] == "completed"
    assert response.json()["scan"]["record_count"] == 0
    assert response.json()["schedule"]["timezone"] == "Asia/Manila"


def test_manual_scan_returns_error_and_saves_failed_run(client, monkeypatch):
    client.post(
        "/api/auth/bootstrap-manager",
        json={
            "name": "Sales Manager",
            "email": "manager@example.com",
            "password": "a-very-long-manager-password",
            "setup_secret": "test-setup-secret-value",
        },
    )

    def fail_detection():
        raise RuntimeError("Salesforce credentials are unavailable")

    monkeypatch.setattr(api, "run_detection", fail_detection)

    response = client.post("/api/scans/run", json={})

    assert response.status_code == 502
    assert "scan failed" in response.json()["detail"].lower()
    latest = client.get("/api/scans/latest")
    assert latest.json()["scan"]["status"] == "failed"
