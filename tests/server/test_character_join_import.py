import openpyxl


def _make_cy20_like_xlsx(path: str, name: str = "阿尔伯特·格雷", occupation: str = "罪犯-独行罪犯"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人物卡"
    ws["B3"] = "姓名"
    ws["E3"] = name
    ws["B5"] = "职业"
    ws["E5"] = occupation
    ws["B6"] = "年龄"
    ws["E6"] = 26
    ws["J6"] = "性别"
    ws["M6"] = "男"
    ws["B7"] = "住地"
    ws["E7"] = "阿卡姆"
    ws["J7"] = "故乡"
    ws["M7"] = "波士顿"
    ws["B10"] = "体力 Hit  Points"
    ws["E10"] = 10
    ws["G10"] = 10
    ws["K10"] = "理智 Sanity"
    ws["N10"] = 55
    ws["P10"] = 99
    ws["F15"] = "技能名称"
    ws["R15"] = "成功率 普通/困难/极限"
    ws["F20"] = "技艺①"
    ws["H20"] = "表演"
    ws["R20"] = 80
    ws["F33"] = "话术"
    ws["R33"] = 25
    ws["F42"] = "急救"
    ws["R42"] = 55
    simple = wb.create_sheet("简化卡")
    simple["H7"] = "MP"
    simple["I7"] = 11
    simple["J7"] = 11
    simple["H9"] = "LUCK"
    simple["I9"] = 60
    wb.save(path)


def _room_id(client) -> str:
    resp = client.post("/api/rooms", json={})
    return resp.json()["room_id"]


def test_preview_xlsx_returns_summary_without_creating_character(client, test_db, tmp_path):
    path = tmp_path / "albert.xlsx"
    _make_cy20_like_xlsx(str(path))

    with path.open("rb") as file:
        resp = client.post(
            "/api/player/character/preview-xlsx",
            files={"file": ("albert.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "阿尔伯特·格雷"
    assert data["occupation"] == "罪犯-独行罪犯"
    assert data["hp"] == 10
    assert data["max_hp"] == 10
    assert data["skill_count"] == 3

    row = test_db.execute("SELECT COUNT(*) AS c FROM characters").fetchone()
    assert row["c"] == 0


def test_join_with_uploaded_character_creates_player_and_character_data(client, tmp_path):
    room_id = _room_id(client)
    path = tmp_path / "albert.xlsx"
    _make_cy20_like_xlsx(str(path))

    with path.open("rb") as file:
        resp = client.post(
            f"/api/player/rooms/{room_id}/join-with-character",
            data={"player_name": "田文"},
            files={"file": ("albert.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert resp.status_code == 200
    joined = resp.json()
    assert joined["player_name"] == "田文"
    assert joined["investigator_name"] == "阿尔伯特·格雷"
    assert joined["character"]["skills"]["急救"] == 55

    char_resp = client.get(
        "/api/player/character",
        headers={"X-Room-Token": joined["player_token"]},
    )
    assert char_resp.status_code == 200
    char = char_resp.json()
    assert char["player_name"] == "田文"
    assert char["investigator_name"] == "阿尔伯特·格雷"
    assert char["name"] == "阿尔伯特·格雷"


def test_presets_list_skips_bad_files_and_marks_room_occupancy(client, tmp_path):
    room_id = _room_id(client)
    client.app.state.character_preset_dir = str(tmp_path)
    _make_cy20_like_xlsx(str(tmp_path / "albert.xlsx"))
    (tmp_path / "broken.xlsx").write_text("not a workbook", encoding="utf-8")

    resp = client.get(f"/api/player/character/presets?room_id={room_id}")

    assert resp.status_code == 200
    presets = resp.json()["presets"]
    assert len(presets) == 1
    assert presets[0]["preset_id"] == "albert"
    assert presets[0]["name"] == "阿尔伯特·格雷"
    assert presets[0]["occupied"] is False


def test_join_with_preset_locks_that_preset_for_room(client, tmp_path):
    room_id = _room_id(client)
    client.app.state.character_preset_dir = str(tmp_path)
    _make_cy20_like_xlsx(str(tmp_path / "albert.xlsx"))

    resp = client.post(
        f"/api/player/rooms/{room_id}/join-with-character",
        data={"player_name": "田文", "preset_id": "albert"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["player_name"] == "田文"
    assert data["investigator_name"] == "阿尔伯特·格雷"

    presets_resp = client.get(f"/api/player/character/presets?room_id={room_id}")
    assert presets_resp.json()["presets"][0]["occupied"] is True

    duplicate = client.post(
        f"/api/player/rooms/{room_id}/join-with-character",
        data={"player_name": "另一个玩家", "preset_id": "albert"},
    )

    assert duplicate.status_code == 409


def test_failed_import_does_not_create_placeholder_player(client, test_db, tmp_path):
    room_id = _room_id(client)
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook", encoding="utf-8")

    with path.open("rb") as file:
        resp = client.post(
            f"/api/player/rooms/{room_id}/join-with-character",
            data={"player_name": "田文"},
            files={"file": ("broken.xlsx", file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert resp.status_code == 400
    row = test_db.execute("SELECT COUNT(*) AS c FROM characters").fetchone()
    assert row["c"] == 0
