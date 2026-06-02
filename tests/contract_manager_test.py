from aznovel.core.contract_manager import ContractManager
from aznovel.models.contract import ChapterBrief, MasterSetting
from aznovel.models.project import EntityRecord, ProjectState, ProtagonistState


def test_review_contract_includes_protagonist_and_dedupes_entities(tmp_path) -> None:
    state = ProjectState(
        protagonist=ProtagonistState(
            name="周也",
            cultivation="失业半年的前财务从业者",
            current_goal="保护12岁儿子周小禾",
        ),
        entities=[
            EntityRecord(name="周小禾"),
            EntityRecord(name="禾苗"),
            EntityRecord(name="周小禾"),
        ],
    )

    contract = ContractManager(tmp_path).generate_review_contract(
        4,
        state,
        MasterSetting(world_rules=["禾苗是高风险食物"]),
        ChapterBrief(summary="周也配送2.0，儿子周小禾症状加重。"),
    )

    assert contract.known_entities == ["周也", "周小禾", "禾苗"]
    assert "禾苗是高风险食物" in contract.established_rules
    assert any(
        "主角是周也" in item and "保护12岁儿子周小禾" in item
        for item in contract.established_rules
    )
