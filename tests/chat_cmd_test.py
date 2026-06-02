from aznovel.cli.chat_cmd import _deterministic_action_from_input


def test_continue_maps_to_write_next() -> None:
    assert _deterministic_action_from_input("继续") == {
        "action": "write_next",
        "params": {},
    }


def test_write_chapter_maps_to_specific_chapter() -> None:
    assert _deterministic_action_from_input("写第3章") == {
        "action": "write_chapter",
        "params": {"chapter": 3},
    }
    assert _deterministic_action_from_input("续写第二章") == {
        "action": "write_chapter",
        "params": {"chapter": 2},
    }


def test_batch_write_maps_to_write_batch() -> None:
    assert _deterministic_action_from_input("连续写3章") == {
        "action": "write_batch",
        "params": {"count": 3},
    }
    assert _deterministic_action_from_input("写三章") == {
        "action": "write_batch",
        "params": {"count": 3},
    }


def test_repair_chapter_maps_to_repair_action() -> None:
    assert _deterministic_action_from_input("修复第4章审查报告里的阻断问题") == {
        "action": "repair_chapter",
        "params": {"chapter": 4},
    }
    assert _deterministic_action_from_input("继续修复第四章") == {
        "action": "repair_chapter",
        "params": {"chapter": 4},
    }


def test_final_safe_repair_maps_to_safe_action() -> None:
    assert _deterministic_action_from_input("请执行最终安全修复，修复全书硬逻辑问题") == {
        "action": "final_safe_repair",
        "params": {"all": True},
    }
    assert _deterministic_action_from_input("全面终检并修复全书硬逻辑") == {
        "action": "final_safe_repair",
        "params": {"all": True},
    }


def test_final_polish_and_finalize_map_to_actions() -> None:
    assert _deterministic_action_from_input("请执行终稿精修，最后打磨一下全书") == {
        "action": "final_polish",
        "params": {"all": True},
    }
    assert _deterministic_action_from_input("执行完稿流程") == {
        "action": "finalize_book",
        "params": {"all": True},
    }


def test_auto_run_book_maps_to_unattended_action() -> None:
    assert _deterministic_action_from_input("请无人值守一口气跑出最终精修稿") == {
        "action": "auto_run_book",
        "params": {},
    }
    assert _deterministic_action_from_input("全流程自动写到10章并产出精修稿") == {
        "action": "auto_run_book",
        "params": {"target": 10},
    }


def test_rename_character_maps_to_rename_action() -> None:
    assert _deterministic_action_from_input("把周小禾改名为周小森") == {
        "action": "rename_character",
        "params": {"old_name": "周小禾", "new_name": "周小森"},
    }
    assert _deterministic_action_from_input("请将角色汪禾重命名为汪野") == {
        "action": "rename_character",
        "params": {"old_name": "汪禾", "new_name": "汪野"},
    }


def test_export_book_maps_to_export_action() -> None:
    assert _deterministic_action_from_input("导出全书为单个文件的epub，pdf，mobi，docx") == {
        "action": "export_book",
        "params": {"formats": ["epub", "pdf", "mobi", "docx"]},
    }
    assert _deterministic_action_from_input("帮我输出全书 word") == {
        "action": "export_book",
        "params": {"formats": ["docx"]},
    }


def test_non_command_still_uses_llm() -> None:
    assert _deterministic_action_from_input("帮我想一个更阴冷的标题") is None
    assert _deterministic_action_from_input("帮我想写第3章的标题") is None
