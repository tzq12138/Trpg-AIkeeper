import json

from .action_state import is_allowed_transition


def transition_action(
    conn,
    action_id: str,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    metadata: dict | None = None,
    result: dict | None = None,
    transaction=None,
) -> bool:
    if not from_statuses:
        raise ValueError("from_statuses must not be empty")
    if any(not is_allowed_transition(status, to_status) for status in from_statuses):
        raise ValueError(f"Illegal action transition: {from_statuses} -> {to_status}")
    def execute(tx):
        if result is None:
            cursor = tx.execute(
                "UPDATE actions SET status = %s WHERE action_id = %s AND status = ANY(%s)",
                (to_status, action_id, list(from_statuses)),
            )
        else:
            cursor = tx.execute(
                "UPDATE actions SET status = %s, result = %s "
                "WHERE action_id = %s AND status = ANY(%s)",
                (
                    to_status,
                    json.dumps(result, ensure_ascii=False),
                    action_id,
                    list(from_statuses),
                ),
            )
        if cursor.rowcount == 0:
            return False
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, %s, %s)",
            (action_id, to_status, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return True

    if transaction is not None:
        return execute(transaction)
    with conn.transaction() as tx:
        return execute(tx)


def complete_action(
    conn,
    action_id: str,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    result: dict,
    receipt: dict | None = None,
    metadata: dict | None = None,
    transaction=None,
) -> bool:
    if not from_statuses:
        raise ValueError("from_statuses must not be empty")
    if any(not is_allowed_transition(status, to_status) for status in from_statuses):
        raise ValueError(f"Illegal action transition: {from_statuses} -> {to_status}")
    def execute(tx):
        cursor = tx.execute(
            "UPDATE actions SET status = %s, result = %s, receipt = %s, completed_at = NOW() "
            "WHERE action_id = %s AND status = ANY(%s)",
            (
                to_status,
                json.dumps(result, ensure_ascii=False),
                json.dumps(receipt, ensure_ascii=False) if receipt is not None else None,
                action_id,
                list(from_statuses),
            ),
        )
        if cursor.rowcount == 0:
            return False
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, %s, %s)",
            (action_id, to_status, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return True

    if transaction is not None:
        return execute(transaction)
    with conn.transaction() as tx:
        return execute(tx)
