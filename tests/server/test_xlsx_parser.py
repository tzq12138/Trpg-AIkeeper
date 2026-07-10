import openpyxl
from pathlib import Path


def _make_xlsx(path: str, data: dict[str, str | int]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人物卡"
    for i, (k, v) in enumerate(data.items(), start=1):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    wb.save(path)


def _make_cy20_like_xlsx(path: str):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "人物卡"
    ws["B3"] = "姓名"
    ws["E3"] = "阿尔伯特·格雷"
    ws["B5"] = "职业"
    ws["E5"] = "罪犯-独行罪犯"
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
    ws["B15"] = "成功标"
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


def test_parse_xlsx_returns_character_fields(tmp_path):
    from src.server.scenario.xlsx_parser import parse_xlsx_character

    path = str(tmp_path / "test.xlsx")
    _make_xlsx(path, {"姓名": "张三", "HP": 12, "SAN": 65, "MP": 10, "LUCK": 50})

    result = parse_xlsx_character(path)
    assert result["name"] == "张三"
    assert result["hp"] == 12
    assert result["san"] == 65
    assert result["mp"] == 10
    assert result["luck"] == 50


def test_parse_xlsx_with_skills(tmp_path):
    from src.server.scenario.xlsx_parser import parse_xlsx_character

    path = str(tmp_path / "test.xlsx")
    _make_xlsx(path, {"姓名": "李四", "HP": 10, "SAN": 50, "图书馆使用": 40, "聆听": 35})

    result = parse_xlsx_character(path)
    assert result["name"] == "李四"
    assert result["skills"]["图书馆使用"] == 40
    assert result["skills"]["聆听"] == 35


def test_parse_xlsx_missing_fields(tmp_path):
    from src.server.scenario.xlsx_parser import parse_xlsx_character

    path = str(tmp_path / "test.xlsx")
    _make_xlsx(path, {"姓名": "王五"})

    result = parse_xlsx_character(path)
    assert result["name"] == "王五"
    assert result["hp"] == 10  # default
    assert result["san"] == 50  # default


def test_parse_cy20_like_xlsx_returns_character_profile_and_skills(tmp_path):
    from src.server.scenario.xlsx_parser import parse_xlsx_character

    path = str(tmp_path / "tzq12138-like.xlsx")
    _make_cy20_like_xlsx(path)

    result = parse_xlsx_character(path)

    assert result["name"] == "阿尔伯特·格雷"
    assert result["occupation"] == "罪犯-独行罪犯"
    assert result["age"] == 26
    assert result["sex"] == "男"
    assert result["residence"] == "阿卡姆"
    assert result["hometown"] == "波士顿"
    assert result["hp"] == 10
    assert result["max_hp"] == 10
    assert result["san"] == 55
    assert result["max_san"] == 99
    assert result["mp"] == 11
    assert result["max_mp"] == 11
    assert result["luck"] == 60
    assert result["skills"]["技艺：表演"] == 80
    assert result["skills"]["话术"] == 25
    assert result["skills"]["急救"] == 55


def test_parse_real_cy20_card_recalculates_skills_without_formula_cache():
    from src.server.scenario.xlsx_parser import parse_xlsx_character

    data_dir = Path(__file__).resolve().parents[2] / "data"
    card_path = next(data_dir.rglob("tzq12138_01_*.xlsx"))

    result = parse_xlsx_character(str(card_path))

    assert result["skills"]["侦查"] == 65
    assert result["skills"]["图书馆使用"] == 70
    assert result["skills"]["聆听"] == 47
    assert result["skills"]["技艺：摄影"] == 38
