import json

from core.collection_store import CollectionStore


def test_collection_manifest_is_persisted_and_restored(tmp_path):
    store = CollectionStore(tmp_path)
    session = store.begin(100, 200, "旅行/视频")
    first = store.add_entry(session, 100, 1, "direct")
    second = store.add_entry(session, "example_channel", 2, "public")
    store.update_entry(session, first, "success", "0001_message_1.mp4")
    store.update_entry(session, second, "failed", error="temporary network error")

    assert session.directory.name == "旅行_视频"
    manifest = session.manifest_path
    assert manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["entries"][0]["status"] == "success"

    restored = CollectionStore(tmp_path).get(100, 200)
    assert restored is not None
    assert restored.name == "旅行/视频"
    assert [entry.status for entry in restored.entries] == ["success", "failed"]
    assert [entry.sequence for entry in CollectionStore.remaining_entries(restored)] == [2]


def test_active_collection_blocks_second_collection(tmp_path):
    store = CollectionStore(tmp_path)
    store.begin(100, 200, "第一集")

    try:
        store.begin(100, 200, "第二集")
    except RuntimeError as exc:
        assert "进行中" in str(exc)
    else:
        raise AssertionError("active collection must reject a second collection")


def test_reopening_completed_collection_appends_entry_sequence(tmp_path):
    store = CollectionStore(tmp_path)
    session = store.begin(100, 200, "旅行")
    first = store.add_entry(session, 100, 1, "direct")
    store.update_entry(session, first, "success", "0001_message_1.mp4")
    store.set_phase(session, "completed")

    reopened = store.begin(100, 200, "旅行")
    second = store.add_entry(reopened, 100, 2, "direct")

    assert reopened is session
    assert second.sequence == 2
