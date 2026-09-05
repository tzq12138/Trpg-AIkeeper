from src.server.scenario.identifiers import ensure_npc_ids


def test_ensure_npc_ids_uses_english_names_and_deduplicates_stably():
    npcs = ensure_npc_ids([
        {"name": "布莱斯·法伦", "english_name": "Blythe Farren"},
        {"name": "约翰·惠特克罗夫特", "english_name": "John Whitcroft"},
        {"name": "艾米莉亚·考特", "english_name": "Amelia Court"},
        {"name": "另一位布莱斯", "english_name": "Blythe Farren"},
    ])

    assert [npc["npc_id"] for npc in npcs] == [
        "blythe-farren",
        "john-whitcroft",
        "amelia-court",
        "blythe-farren-2",
    ]


def test_ensure_npc_ids_keeps_existing_manual_identifiers():
    npcs = ensure_npc_ids([
        {"name": "馆长", "npc_id": "keeper"},
    ])

    assert npcs[0]["npc_id"] == "keeper"
