import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.server.conftest import login, setup_auth_test_data


def _seed_retention_rows(test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('retention-room', 'owner', 'completed')"
    )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs, created_at) "
        "VALUES ('retention-archive', 'retention-room', 'mixed', 'keep', '[]', '[]', "
        "NOW() - INTERVAL '500 days')"
    )
    for task_type, record_kind, age in (
        ("diagnostic", "diagnostic", "25 hours"),
        ("director", "decision", "91 days"),
        ("director", "decision", "1 day"),
    ):
        test_db.execute(
            "INSERT INTO ai_call_logs "
            "(room_id, task_type, provider, status, record_kind, created_at, expires_at) "
            "VALUES ('retention-room', %s, 'local', 'ok', %s, NOW() - %s::interval, "
            "NULL)",
            (task_type, record_kind, age),
        )
    test_db.execute(
        "INSERT INTO admin_data_purge_audits "
        "(audit_id, action, actor_id, target_count, details, created_at) "
        "VALUES ('old-admin-audit', 'account_delete', 'actor', 1, '{}', "
        "NOW() - INTERVAL '366 days')"
    )
    test_db.execute(
        "INSERT INTO ai_provider_config_audits "
        "(audit_id, action, actor_id, details, created_at) "
        "VALUES ('old-provider-audit', 'updated', 'actor', '{}', "
        "NOW() - INTERVAL '366 days')"
    )
    test_db.execute(
        "INSERT INTO private_data_access_audits "
        "(private_data_access_audit_id, room_id, host_account_id, reason, created_at) "
        "VALUES ('old-sensitive-access-audit', 'retention-room', 'acc-admin', "
        "'expired incident access', NOW() - INTERVAL '366 days')"
    )
    test_db.execute(
        "INSERT INTO retention_runs "
        "(retention_run_id, idempotency_key, cutoff, actor_id, counts, created_at) "
        "VALUES ('old-retention-run', 'old-retention-key', NOW() - INTERVAL '366 days', "
        "'actor', '{}', NOW() - INTERVAL '366 days')"
    )
    test_db.commit()


def test_retention_dry_run_apply_and_retry_are_safe_and_idempotent(test_db):
    from src.server.governance.retention import RetentionService

    _seed_retention_rows(test_db)
    service = RetentionService(test_db)
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    dry_run = service.dry_run(cutoff=cutoff, idempotency_key="retention-2026-08")

    assert dry_run["counts"] == {
        "diagnostics": 1,
        "ai_decisions": 1,
        "governance_audits": 4,
    }
    assert test_db.execute("SELECT COUNT(*) AS c FROM retention_runs").fetchone()["c"] == 1
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM admin_data_purge_audits"
    ).fetchone()["c"] == 1

    applied = service.apply(
        cutoff=cutoff,
        idempotency_key="retention-2026-08",
        dry_run_token=dry_run["dry_run_token"],
        actor_id="acc-admin",
    )
    retried = service.apply(
        cutoff=cutoff,
        idempotency_key="retention-2026-08",
        dry_run_token=dry_run["dry_run_token"],
        actor_id="acc-admin",
    )

    assert applied["counts"] == dry_run["counts"]
    assert retried == {**applied, "idempotent": True}
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM campaign_archives WHERE archive_id = 'retention-archive'"
    ).fetchone()["c"] == 1
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs"
    ).fetchone()["c"] == 1
    assert test_db.execute("SELECT COUNT(*) AS c FROM retention_runs").fetchone()["c"] == 1
    audits = test_db.execute(
        "SELECT details FROM admin_data_purge_audits WHERE action = 'retention_apply'"
    ).fetchall()
    assert len(audits) == 1
    assert audits[0]["details"]["idempotency_key"] == "retention-2026-08"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_provider_config_audits"
    ).fetchone()["c"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM private_data_access_audits"
    ).fetchone()["c"] == 0


def test_retention_apply_rejects_changed_cutoff_or_key(test_db):
    from src.server.governance.retention import RetentionError, RetentionService

    _seed_retention_rows(test_db)
    service = RetentionService(test_db)
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    dry_run = service.dry_run(cutoff=cutoff, idempotency_key="retention-original")

    try:
        service.apply(
            cutoff=cutoff,
            idempotency_key="retention-changed",
            dry_run_token=dry_run["dry_run_token"],
            actor_id="acc-admin",
        )
    except RetentionError as exc:
        assert exc.code == "retention_dry_run_mismatch"
    else:
        raise AssertionError("changed retention request must be rejected")


def test_retention_apply_rejects_candidates_added_after_dry_run(test_db):
    from src.server.governance.retention import RetentionError, RetentionService

    _seed_retention_rows(test_db)
    service = RetentionService(test_db)
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    key = "retention-stale-preview"
    dry_run = service.dry_run(cutoff=cutoff, idempotency_key=key)
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, task_type, provider, status, record_kind, created_at) "
        "VALUES ('retention-room', 'late-diagnostic', 'local', 'ok', "
        "'diagnostic', NOW() - INTERVAL '25 hours')"
    )
    test_db.commit()

    with pytest.raises(RetentionError) as error:
        service.apply(
            cutoff=cutoff,
            idempotency_key=key,
            dry_run_token=dry_run["dry_run_token"],
            actor_id="acc-admin",
        )

    assert error.value.code == "retention_dry_run_stale"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs "
        "WHERE record_kind = 'diagnostic'"
    ).fetchone()["c"] == 2
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM retention_runs WHERE idempotency_key = %s",
        (key,),
    ).fetchone()["c"] == 0


def test_retention_retry_preserves_non_utc_cutoff_instant(test_db):
    from src.server.governance.retention import RetentionService

    setup_auth_test_data(test_db)
    service = RetentionService(test_db)
    cutoff = "2026-08-02T17:30:00+08:00"
    dry_run = service.dry_run(
        cutoff=cutoff,
        idempotency_key="retention-offset-cutoff",
    )

    applied = service.apply(
        cutoff=cutoff,
        idempotency_key="retention-offset-cutoff",
        dry_run_token=dry_run["dry_run_token"],
        actor_id="acc-admin",
    )
    retried = service.apply(
        cutoff=cutoff,
        idempotency_key="retention-offset-cutoff",
        dry_run_token=dry_run["dry_run_token"],
        actor_id="acc-admin",
    )

    stored = test_db.execute(
        "SELECT cutoff FROM retention_runs "
        "WHERE idempotency_key = 'retention-offset-cutoff'"
    ).fetchone()["cutoff"]
    assert retried == {**applied, "idempotent": True}
    assert stored == datetime.fromisoformat(cutoff)


def test_retention_dry_run_token_expires_and_cannot_be_replayed(test_db):
    from src.server.governance.retention import (
        RetentionError,
        RetentionService,
        _token,
    )

    setup_auth_test_data(test_db)
    service = RetentionService(test_db)
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    key = "retention-expiring-token"
    dry_run = service.dry_run(cutoff=cutoff, idempotency_key=key)

    assert dry_run["dry_run_expires_at"] > int(
        datetime.now(timezone.utc).timestamp()
    )
    expired_token = _token({
        "cutoff": cutoff,
        "idempotency_key": key,
        "exp": int(datetime.now(timezone.utc).timestamp()) - 1,
    })

    with pytest.raises(RetentionError) as error:
        service.apply(
            cutoff=cutoff,
            idempotency_key=key,
            dry_run_token=expired_token,
            actor_id="acc-admin",
        )

    assert error.value.code == "retention_dry_run_expired"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM retention_runs "
        "WHERE idempotency_key = %s",
        (key,),
    ).fetchone()["c"] == 0


def test_retention_rejects_future_cutoff_in_dry_run_and_apply(test_db):
    from src.server.governance.retention import (
        RetentionError,
        RetentionService,
        _token,
    )

    _seed_retention_rows(test_db)
    service = RetentionService(test_db)
    cutoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    key = "retention-future-cutoff"

    with pytest.raises(RetentionError) as dry_run_error:
        service.dry_run(cutoff=cutoff, idempotency_key=key)
    assert dry_run_error.value.code == "retention_cutoff_in_future"

    token = _token({
        "cutoff": cutoff,
        "idempotency_key": key,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 60,
    })
    with pytest.raises(RetentionError) as apply_error:
        service.apply(
            cutoff=cutoff,
            idempotency_key=key,
            dry_run_token=token,
            actor_id="acc-admin",
        )
    assert apply_error.value.code == "retention_cutoff_in_future"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs"
    ).fetchone()["c"] == 3


def test_retention_admin_api_requires_dry_run_and_explicit_apply_confirmation(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {"cutoff": cutoff, "idempotency_key": "retention-admin-api"}
    unauthorized = client.post("/api/admin/retention/dry-run", json=payload)
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}
    dry_run = client.post(
        "/api/admin/retention/dry-run",
        headers=headers,
        json=payload,
    )

    assert unauthorized.status_code == 401
    assert dry_run.status_code == 200
    apply_payload = {
        **payload,
        "dry_run_token": dry_run.json()["dry_run_token"],
    }
    unconfirmed = client.post(
        "/api/admin/retention/apply",
        headers=headers,
        json=apply_payload,
    )
    applied = client.post(
        "/api/admin/retention/apply",
        headers=headers,
        json={**apply_payload, "confirm": True},
    )

    assert unconfirmed.status_code == 400
    assert applied.status_code == 200
    assert applied.json()["idempotency_key"] == "retention-admin-api"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM retention_runs "
        "WHERE idempotency_key = 'retention-admin-api'"
    ).fetchone()["c"] == 1


def test_retention_admin_api_rejects_future_cutoff(client, test_db):
    setup_auth_test_data(test_db)
    headers = {"Authorization": f"Bearer {login(client, 'admin')}"}
    response = client.post(
        "/api/admin/retention/dry-run",
        headers=headers,
        json={
            "cutoff": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "idempotency_key": "future-cutoff-api",
        },
    )

    assert response.status_code == 400
