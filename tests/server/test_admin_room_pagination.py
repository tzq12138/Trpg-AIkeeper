import pytest

from tests.server.conftest import create_scenario, login, setup_auth_test_data


def _admin_headers(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, 'admin')}"}


def _insert_rooms(test_db, count: int) -> list[str]:
    create_scenario(test_db, "sc-page", "Pagination Scenario")
    room_ids = [f"page-room-{index:02d}" for index in range(count)]
    for room_id in room_ids:
        test_db.execute(
            "INSERT INTO rooms "
            "(room_id, owner_token, scenario_id, status, rule_source_status, rule_source_reason, created_at) "
            "VALUES (%s, %s, 'sc-page', 'active', 'blocked', 'legacy test rule source', %s)",
            (room_id, f"owner-token-{room_id}", "2026-08-13 00:00:00"),
        )
    test_db.commit()
    return room_ids


def test_admin_room_pagination_returns_stable_non_overlapping_pages_and_metadata(
    client, test_db
):
    setup_auth_test_data(test_db)
    _insert_rooms(test_db, 31)
    headers = _admin_headers(client)

    first_page = client.get(
        "/api/admin/rooms?page=1&page_size=10", headers=headers
    )
    second_page = client.get(
        "/api/admin/rooms?page=2&page_size=10", headers=headers
    )
    last_page = client.get(
        "/api/admin/rooms?page=4&page_size=10", headers=headers
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert last_page.status_code == 200
    first_payload = first_page.json()
    second_payload = second_page.json()
    last_payload = last_page.json()
    assert first_payload["page"] == 1
    assert first_payload["page_size"] == 10
    assert first_payload["total"] == 31
    assert first_payload["total_pages"] == 4
    assert [item["room_id"] for item in first_payload["items"]] == [
        f"page-room-{index:02d}" for index in range(30, 20, -1)
    ]
    assert set(item["room_id"] for item in first_payload["items"]).isdisjoint(
        item["room_id"] for item in second_payload["items"]
    )
    assert [item["room_id"] for item in last_payload["items"]] == ["page-room-00"]


@pytest.mark.parametrize(
    ("page_size", "expected_count", "expected_total_pages"),
    [(10, 10, 4), (30, 30, 2), (50, 31, 1)],
)
def test_admin_room_pagination_accepts_supported_page_sizes(
    client, test_db, page_size, expected_count, expected_total_pages
):
    setup_auth_test_data(test_db)
    _insert_rooms(test_db, 31)

    response = client.get(
        f"/api/admin/rooms?page=1&page_size={page_size}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == expected_count
    assert payload["total_pages"] == expected_total_pages


@pytest.mark.parametrize(
    "query",
    [
        "?page=1",
        "?page_size=10",
        "?page=zero&page_size=10",
        "?page=1.5&page_size=10",
        "?page=0&page_size=10",
        "?page=1&page_size=20",
    ],
)
def test_admin_room_pagination_rejects_incomplete_or_invalid_parameters(
    client, test_db, query
):
    setup_auth_test_data(test_db)

    response = client.get(f"/api/admin/rooms{query}", headers=_admin_headers(client))

    assert response.status_code == 422


def test_admin_room_list_keeps_legacy_array_and_never_leaks_owner_tokens(client, test_db):
    setup_auth_test_data(test_db)
    _insert_rooms(test_db, 1)
    headers = _admin_headers(client)

    legacy = client.get("/api/admin/rooms", headers=headers)
    paged = client.get("/api/admin/rooms?page=1&page_size=10", headers=headers)

    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    for payload in (legacy.json(), paged.json()["items"]):
        assert payload[0]["room_id"] == "page-room-00"
        assert payload[0]["status"] == "active"
        assert payload[0]["scenario_title"] == "Pagination Scenario"
        assert payload[0]["rule_source_status"] == "blocked"
        assert payload[0]["rule_source_reason"] == "legacy test rule source"
        assert "owner_token" not in payload[0]
        assert "player_token" not in payload[0]
