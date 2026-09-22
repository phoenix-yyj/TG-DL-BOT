import json

from core.auto_monitor import load_monitor_config


def test_public_username_can_be_used_as_monitor_peer(tmp_path):
    path = tmp_path / "auto.json"
    path.write_text(json.dumps({"chats": {"@example_public_group": {"passwords": []}}}), encoding="utf-8")

    config = load_monitor_config(path)

    assert "example_public_group" in config
