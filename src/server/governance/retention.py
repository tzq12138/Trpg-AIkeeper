import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone


_RETENTION_DRY_RUN_TTL_SECONDS = 15 * 60
_RETENTION_CLOCK_SKEW_SECONDS = 5


class RetentionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _secret() -> bytes:
    return os.getenv("JWT_SECRET", "aikeeper-retention-dev-secret").encode()


def _token(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: str, expected: dict):
    try:
        body, signature = token.split(".", 1)
        actual = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
        padding = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + padding))
    except Exception as exc:
        raise RetentionError("retention_dry_run_invalid") from exc
    if not hmac.compare_digest(actual, signature):
        raise RetentionError("retention_dry_run_invalid")
    if any(payload.get(key) != value for key, value in expected.items()):
        raise RetentionError("retention_dry_run_mismatch")
    if int(payload.get("exp") or 0) <= int(
        datetime.now(timezone.utc).timestamp()
    ):
        raise RetentionError("retention_dry_run_expired")
    return payload


def _validate_cutoff(cutoff: str) -> None:
    try:
        parsed = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RetentionError("retention_cutoff_invalid") from exc
    if parsed.tzinfo is None:
        raise RetentionError("retention_cutoff_invalid")
    if parsed > datetime.now(timezone.utc) + timedelta(
        seconds=_RETENTION_CLOCK_SKEW_SECONDS
    ):
        raise RetentionError("retention_cutoff_in_future")


def issue_sensitive_access_grant(*, actor_id: str, incident_id: str, reason: str,
                                 scope: str, ttl_seconds: int) -> str:
    return _token({"actor_id": actor_id, "incident_id": incident_id, "reason": reason,
                   "scope": scope, "exp": int(datetime.now(timezone.utc).timestamp()) + ttl_seconds})


def verify_sensitive_access_grant(token: str, *, actor_id: str, incident_id: str,
                                  reason: str, scope: str):
    try:
        body, signature = token.split(".", 1)
        actual = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as exc:
        raise RetentionError("sensitive_grant_invalid") from exc
    if not hmac.compare_digest(actual, signature):
        raise RetentionError("sensitive_grant_invalid")
    expected = {"actor_id": actor_id, "incident_id": incident_id, "reason": reason, "scope": scope}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise RetentionError("sensitive_grant_scope_mismatch")
    if int(payload.get("exp") or 0) <= int(datetime.now(timezone.utc).timestamp()):
        raise RetentionError("sensitive_grant_expired")


class RetentionService:
    def __init__(self, conn):
        self.conn = conn

    def _snapshot(self, cutoff: str, conn=None) -> dict:
        db = conn or self.conn
        redacted_resolution_traces = [
            str(row["candidate_id"])
            for row in db.execute(
                "SELECT resolution_trace_id AS candidate_id FROM resolution_traces "
                "WHERE created_at <= %s::timestamptz - INTERVAL '180 days' "
                "ORDER BY resolution_trace_id",
                (cutoff,),
            ).fetchall()
        ]
        full_resolution_traces = [
            str(row["candidate_id"])
            for row in db.execute(
                "SELECT resolution_trace_id AS candidate_id "
                "FROM resolution_trace_secure_payloads "
                "WHERE expires_at <= %s::timestamptz "
                "OR resolution_trace_id = ANY(%s) "
                "ORDER BY resolution_trace_id",
                (cutoff, redacted_resolution_traces),
            ).fetchall()
        ]
        diagnostics = [
            int(row["candidate_id"])
            for row in db.execute(
                "SELECT id AS candidate_id FROM ai_call_logs "
                "WHERE record_kind = 'diagnostic' "
                "AND created_at < %s::timestamptz - INTERVAL '24 hours' "
                "ORDER BY id",
                (cutoff,),
            ).fetchall()
        ]
        decisions = [
            int(row["candidate_id"])
            for row in db.execute(
                "SELECT id AS candidate_id FROM ai_call_logs "
                "WHERE record_kind = 'decision' "
                "AND COALESCE(expires_at, created_at + INTERVAL '90 days') "
                "<= %s::timestamptz ORDER BY id",
                (cutoff,),
            ).fetchall()
        ]
        governance_columns = {
            "admin_data_purge_audits": "audit_id",
            "ai_provider_config_audits": "audit_id",
            "private_data_access_audits": "private_data_access_audit_id",
            "retention_runs": "retention_run_id",
        }
        governance: dict[str, list[str]] = {}
        for table, column in governance_columns.items():
            governance[table] = [
                str(row["candidate_id"])
                for row in db.execute(
                    f"SELECT {column} AS candidate_id FROM {table} "
                    "WHERE created_at < %s::timestamptz - INTERVAL '365 days' "
                    f"ORDER BY {column}",
                    (cutoff,),
                ).fetchall()
            ]
        references = [
            *(f"resolution_trace_secure_payloads:{candidate_id}" for candidate_id in full_resolution_traces),
            *(f"resolution_traces:{candidate_id}" for candidate_id in redacted_resolution_traces),
            *(f"ai_call_logs:{candidate_id}" for candidate_id in diagnostics),
            *(f"ai_call_logs:{candidate_id}" for candidate_id in decisions),
            *(
                f"{table}:{candidate_id}"
                for table in sorted(governance)
                for candidate_id in governance[table]
            ),
        ]
        counts = {
            "full_resolution_traces": len(full_resolution_traces),
            "redacted_resolution_traces": len(redacted_resolution_traces),
            "diagnostics": len(diagnostics),
            "ai_decisions": len(decisions),
            "governance_audits": sum(len(ids) for ids in governance.values()),
        }
        digest = hashlib.sha256(
            json.dumps(
                references,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "counts": counts,
            "candidate_digest": digest,
            "full_resolution_traces": full_resolution_traces,
            "redacted_resolution_traces": redacted_resolution_traces,
            "diagnostics": diagnostics,
            "ai_decisions": decisions,
            "governance": governance,
        }

    def dry_run(self, *, cutoff: str, idempotency_key: str) -> dict:
        _validate_cutoff(cutoff)
        claims = {"cutoff": cutoff, "idempotency_key": idempotency_key}
        expires_at = (
            int(datetime.now(timezone.utc).timestamp())
            + _RETENTION_DRY_RUN_TTL_SECONDS
        )
        with self.conn.transaction() as tx:
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("aikeeper-retention-global",),
            )
            snapshot = self._snapshot(cutoff, conn=tx)
        token_claims = {
            **claims,
            "candidate_digest": snapshot["candidate_digest"],
            "counts": snapshot["counts"],
        }
        return {
            "counts": snapshot["counts"],
            "candidate_digest": snapshot["candidate_digest"],
            "dry_run_token": _token({**token_claims, "exp": expires_at}),
            "dry_run_expires_at": expires_at,
            **claims,
        }

    def apply(self, *, cutoff: str, idempotency_key: str, dry_run_token: str,
              actor_id: str) -> dict:
        _validate_cutoff(cutoff)
        claims = {"cutoff": cutoff, "idempotency_key": idempotency_key}
        with self.conn.transaction() as tx:
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("aikeeper-retention-global",),
            )
            existing = tx.execute(
                "SELECT counts, cutoff FROM retention_runs "
                "WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
            if existing:
                same_cutoff = tx.execute(
                    "SELECT %s::timestamptz = %s::timestamptz AS same",
                    (cutoff, existing["cutoff"]),
                ).fetchone()["same"]
                if not same_cutoff:
                    raise RetentionError("retention_idempotency_conflict")
                return {"counts": existing["counts"], "cutoff": cutoff,
                        "idempotency_key": idempotency_key, "idempotent": True}
            token_payload = _verify(dry_run_token, claims)
            snapshot = self._snapshot(cutoff, conn=tx)
            if (
                token_payload.get("candidate_digest")
                != snapshot["candidate_digest"]
                or token_payload.get("counts") != snapshot["counts"]
            ):
                raise RetentionError("retention_dry_run_stale")

            def delete_candidates(table: str, column: str, ids: list) -> int:
                if not ids:
                    return 0
                return len(tx.execute(
                    f"DELETE FROM {table} WHERE {column} = ANY(%s) RETURNING 1",
                    (ids,),
                ).fetchall())

            diagnostics_count = delete_candidates(
                "ai_call_logs",
                "id",
                snapshot["diagnostics"],
            )
            decisions_count = delete_candidates(
                "ai_call_logs",
                "id",
                snapshot["ai_decisions"],
            )
            full_resolution_traces_count = delete_candidates(
                "resolution_trace_secure_payloads",
                "resolution_trace_id",
                snapshot["full_resolution_traces"],
            )
            redacted_resolution_traces_count = delete_candidates(
                "resolution_traces",
                "resolution_trace_id",
                snapshot["redacted_resolution_traces"],
            )
            governance_count = 0
            governance_columns = {
                "admin_data_purge_audits": "audit_id",
                "ai_provider_config_audits": "audit_id",
                "private_data_access_audits": "private_data_access_audit_id",
                "retention_runs": "retention_run_id",
            }
            for table, column in governance_columns.items():
                governance_count += delete_candidates(
                    table,
                    column,
                    snapshot["governance"][table],
                )
            counts = {
                "full_resolution_traces": full_resolution_traces_count,
                "redacted_resolution_traces": redacted_resolution_traces_count,
                "diagnostics": diagnostics_count,
                "ai_decisions": decisions_count,
                "governance_audits": governance_count,
            }
            tx.execute("INSERT INTO retention_runs "
                       "(retention_run_id, idempotency_key, cutoff, actor_id, counts) "
                       "VALUES (%s, %s, %s, %s, %s)",
                       (f"retention-{uuid.uuid4().hex}", idempotency_key, cutoff, actor_id,
                        json.dumps(counts)))
            tx.execute("INSERT INTO admin_data_purge_audits "
                       "(audit_id, action, actor_id, target_count, details) "
                       "VALUES (%s, 'retention_apply', %s, %s, %s)",
                       (f"retention-audit-{uuid.uuid4().hex}", actor_id, sum(counts.values()),
                        json.dumps({
                            **claims,
                            "counts": counts,
                            "candidate_digest": snapshot["candidate_digest"],
                        })))
        return {"counts": counts, **claims, "idempotent": False}
