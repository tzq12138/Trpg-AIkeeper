import openpyxl


def parse_xlsx_character(file_path: str) -> dict:
    wb = openpyxl.load_workbook(file_path, data_only=True)
    try:
        ws = _first_sheet(wb, ["人物卡", "Sheet1"]) or wb.active
        simple_ws = _first_sheet(wb, ["简化卡"])
        if _looks_like_cy20(ws):
            return _parse_cy20_sheet(ws, simple_ws)
        return _parse_key_value_sheet(ws)
    finally:
        wb.close()


def _first_sheet(wb, names: list[str]):
    for name in names:
        if name in wb.sheetnames:
            return wb[name]
    return None


def _looks_like_cy20(ws) -> bool:
    label = str(_cell(ws, "B3") or "")
    return bool(_cell(ws, "E3")) and ("姓名" in label or "Name" in label)


def _parse_key_value_sheet(ws) -> dict:
    data = {}
    for row in ws.iter_rows(min_row=1, max_row=50, values_only=False):
        if len(row) >= 2 and row[0].value is not None and row[1].value is not None:
            key = str(row[0].value).strip()
            val = row[1].value
            data[key] = val

    name = data.get("姓名", data.get("Name", "未知"))
    hp = _to_int(data.get("HP", data.get("生命", 10)))
    san = _to_int(data.get("SAN", data.get("理智", 50)))
    mp = _to_int(data.get("MP", data.get("魔法", 10)))
    luck = _to_int(data.get("LUCK", data.get("幸运", 50)))

    skills = {}
    skip_keys = {"HP", "SAN", "MP", "LUCK", "生命", "理智", "魔法", "幸运", "姓名", "Name"}
    for k, v in data.items():
        if k not in skip_keys and isinstance(v, (int, float)):
            skills[k] = int(v)

    return {
        "name": str(name),
        "hp": hp,
        "max_hp": hp,
        "san": san,
        "max_san": san,
        "mp": mp,
        "max_mp": mp,
        "luck": luck,
        "skills": skills,
        "raw": data,
    }


def _parse_cy20_sheet(ws, simple_ws=None) -> dict:
    hp = _to_int(_cell(ws, "E10"), default=10)
    max_hp = _to_int(_cell(ws, "G10"), default=hp)
    san = _to_int(_cell(ws, "N10"), default=50)
    max_san = _to_int(_cell(ws, "P10"), default=san)
    mp = _to_int(_cell(simple_ws, "I7"), default=10) if simple_ws else 10
    max_mp = _to_int(_cell(simple_ws, "J7"), default=mp) if simple_ws else mp
    luck = _to_int(_cell(simple_ws, "I9"), default=50) if simple_ws else 50

    raw = {
        "name": _text(_cell(ws, "E3")),
        "occupation": _text(_cell(ws, "E5")),
        "age": _cell(ws, "E6"),
        "sex": _text(_cell(ws, "M6")),
        "residence": _text(_cell(ws, "E7")),
        "hometown": _text(_cell(ws, "M7")),
    }
    return {
        "name": raw["name"] or "未知",
        "occupation": raw["occupation"],
        "age": _to_int(raw["age"], default=0),
        "sex": raw["sex"],
        "residence": raw["residence"],
        "hometown": raw["hometown"],
        "hp": hp,
        "max_hp": max_hp,
        "san": san,
        "max_san": max_san,
        "mp": mp,
        "max_mp": max_mp,
        "luck": luck,
        "skills": _parse_cy20_skills(ws),
        "raw": raw,
    }


def _parse_cy20_skills(ws) -> dict[str, int]:
    skills: dict[str, int] = {}
    for row in range(16, min(ws.max_row, 90) + 1):
        value = _to_int(ws.cell(row=row, column=18).value, default=-1)
        if value < 0:
            continue
        primary = _text(ws.cell(row=row, column=6).value)
        secondary = _text(ws.cell(row=row, column=8).value)
        name = _skill_name(primary, secondary)
        if name:
            skills[name] = value
    return skills


def _skill_name(primary: str, secondary: str) -> str:
    if primary and secondary:
        base = primary.rstrip("①②③④⑤⑥⑦⑧⑨⑩1234567890").rstrip(":：")
        if base != primary or primary.endswith((":", "：")):
            return f"{base}：{secondary}"
        return secondary
    return primary or secondary


def _cell(ws, address: str):
    if ws is None:
        return None
    return ws[address].value


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _to_int(val, default: int = 0) -> int:
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default
