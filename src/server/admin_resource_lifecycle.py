"""Safe lifecycle operations shared by administrator resource endpoints."""

from __future__ import annotations

from dataclasses import dataclass
import uuid


class AdminResourceLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResourceSpec:
    table: str
    identifier: str


RESOURCE_SPECS = {
    "rooms": ResourceSpec("rooms", "room_id"),
    "scenarios": ResourceSpec("scenarios", "scenario_id"),
    "characters": ResourceSpec("characters", "character_id"),
    "accounts": ResourceSpec("accounts", "account_id"),
}


def _normalized_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        raise AdminResourceLifecycleError("invalid_ids", "请至少选择一项资源")
    result: list[str] = []
    for value in values:
        resource_id = str(value or "").strip()
        if resource_id and resource_id not in result:
            result.append(resource_id)
    if not result:
        raise AdminResourceLifecycleError("invalid_ids", "请至少选择一项资源")
    if len(result) > 100:
        raise AdminResourceLifecycleError("too_many_resources", "一次最多处理 100 项资源")
    return result


def soft_delete_resources(conn, resource_type: str, values: object, actor_id: str) -> list[str]:
    spec = RESOURCE_SPECS.get(resource_type)
    if not spec:
        raise AdminResourceLifecycleError("invalid_resource_type", "不支持的资源类型")
    resource_ids = _normalized_ids(values)
    placeholders = ", ".join(["%s"] * len(resource_ids))
    rows = conn.execute(
        f"SELECT * FROM {spec.table} WHERE {spec.identifier} IN ({placeholders})",
        tuple(resource_ids),
    ).fetchall()
    by_id = {str(row[spec.identifier]): dict(row) for row in rows}
    missing = [resource_id for resource_id in resource_ids if resource_id not in by_id]
    if missing:
        raise AdminResourceLifecycleError("resource_not_found", "所选资源不存在或已被清理")

    if resource_type == "accounts":
        _assert_account_deletion_allowed(conn, by_id, actor_id)

    for resource_id in resource_ids:
        if by_id[resource_id].get("deleted_at"):
            continue
        _soft_delete(conn, resource_type, spec, resource_id, actor_id)
        _write_audit(conn, resource_type, resource_id, "soft_delete", actor_id)
    return resource_ids


def restore_resource(conn, resource_type: str, resource_id: str, actor_id: str) -> None:
    spec = RESOURCE_SPECS.get(resource_type)
    if not spec:
        raise AdminResourceLifecycleError("invalid_resource_type", "不支持的资源类型")
    row = conn.execute(
        f"SELECT * FROM {spec.table} WHERE {spec.identifier} = %s", (resource_id,)
    ).fetchone()
    if not row:
        raise AdminResourceLifecycleError("resource_not_found", "资源不存在")
    if not dict(row).get("deleted_at"):
        raise AdminResourceLifecycleError("resource_not_deleted", "资源不在回收站中")

    if resource_type == "rooms":
        conn.execute(
            "UPDATE rooms SET deleted_at = NULL, deleted_by = NULL, status = 'paused' WHERE room_id = %s",
            (resource_id,),
        )
    elif resource_type == "characters":
        conn.execute(
            "UPDATE characters SET deleted_at = NULL, deleted_by = NULL, status = 'joined', is_ready = FALSE WHERE character_id = %s",
            (resource_id,),
        )
    else:
        conn.execute(
            f"UPDATE {spec.table} SET deleted_at = NULL, deleted_by = NULL WHERE {spec.identifier} = %s",
            (resource_id,),
        )
    _write_audit(conn, resource_type, resource_id, "restore", actor_id)


def _soft_delete(conn, resource_type: str, spec: ResourceSpec, resource_id: str, actor_id: str) -> None:
    if resource_type == "rooms":
        conn.execute(
            "UPDATE rooms SET deleted_at = NOW(), deleted_by = %s, status = 'archived' WHERE room_id = %s",
            (actor_id, resource_id),
        )
    elif resource_type == "characters":
        conn.execute(
            "UPDATE characters SET deleted_at = NOW(), deleted_by = %s, status = 'removed', is_ready = FALSE WHERE character_id = %s",
            (actor_id, resource_id),
        )
    else:
        conn.execute(
            f"UPDATE {spec.table} SET deleted_at = NOW(), deleted_by = %s WHERE {spec.identifier} = %s",
            (actor_id, resource_id),
        )


def _assert_account_deletion_allowed(conn, accounts: dict[str, dict], actor_id: str) -> None:
    if actor_id in accounts:
        raise AdminResourceLifecycleError("current_admin_protected", "不能删除当前登录的管理员账号")
    active_admins = conn.execute(
        "SELECT COUNT(*) AS count FROM accounts WHERE role = 'admin' AND deleted_at IS NULL"
    ).fetchone()["count"]
    deleting_active_admins = sum(
        1 for account in accounts.values()
        if account.get("role") == "admin" and not account.get("deleted_at")
    )
    if deleting_active_admins and int(active_admins) <= deleting_active_admins:
        raise AdminResourceLifecycleError("last_admin_protected", "必须至少保留一个可登录的管理员账号")


def _write_audit(conn, resource_type: str, resource_id: str, action: str, actor_id: str) -> None:
    conn.execute(
        "INSERT INTO admin_resource_audits (audit_id, resource_type, resource_id, action, actor_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (str(uuid.uuid4()), resource_type, resource_id, action, actor_id),
    )
