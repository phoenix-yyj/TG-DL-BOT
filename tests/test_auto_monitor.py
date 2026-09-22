import json
from types import SimpleNamespace

from core.auto_monitor import archive_name, load_monitor_config, volume_group
from core.monitor_store import MonitorStore


def test_monitor_config_is_keyed_by_chat_id(tmp_path):
    path = tmp_path / "auto.json"
    path.write_text(json.dumps({"chats": {"-1001": {"name": "群", "passwords": ["pw"]}}}), encoding="utf-8")

    config = load_monitor_config(path)

    assert config["-1001"]["name"] == "群"
    assert config["-1001"]["passwords"] == ["pw"]
    assert config["-1001"]["output_dir"] == "downloads/-1001"


def test_archive_filter_and_volume_group():
    document = SimpleNamespace(file_name="package.7z.001")
    message = SimpleNamespace(document=document)

    assert archive_name(message) == "package.7z.001"
    assert volume_group("package.7z.001") == "package"
    assert volume_group("package.7z.002") == "package"
    assert archive_name(SimpleNamespace(document=SimpleNamespace(file_name="photo.jpg"))) is None


def test_monitor_store_restores_journal_and_checkpoint(tmp_path):
    store = MonitorStore(tmp_path)
    store.upsert(-1001, 42, status="downloaded", local_path="x.zip")

    restored = MonitorStore(tmp_path)
    assert restored.get(-1001, 42)["status"] == "downloaded"
    restored.checkpoint()
    assert restored.path.exists()
    assert not restored.journal.exists()
