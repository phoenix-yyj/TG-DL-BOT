import json

from core.collection_store import CollectionEntry, CollectionSession, CollectionStore


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
    assert json.loads(manifest.read_text(encoding="utf-8"))["entries"] == []
    assert manifest.with_suffix(".jsonl").exists()

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


def test_new_collection_can_start_while_previous_collection_downloads(tmp_path):
    store = CollectionStore(tmp_path)
    first = store.begin(100, 200, "第一份")
    store.add_entry(first, 100, 1, "direct")
    store.set_phase(first, "downloading")

    second = store.begin(100, 200, "第二份")

    assert second is not first
    assert store.get(100, 200) is second
    assert first.phase == "downloading"
    assert len(store.all(100, 200)) == 2


def test_ephemeral_single_item_session_targets_download_root_without_manifest(tmp_path):
    session = CollectionSession(
        name="单项下载", directory_name=".", owner_user_id=200, owner_chat_id=100,
        entries=[CollectionEntry(1, 100, 1, "direct")], root=tmp_path, persist=False,
    )

    assert session.directory == tmp_path
    assert session.manifest_path == tmp_path / ".tgdl_collection_100_200.json"


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


def test_interrupted_download_entries_are_restorable(tmp_path):
    store = CollectionStore(tmp_path)
    session = store.begin(100, 200, "旅行")
    entry = store.add_entry(session, 100, 1, "direct")
    store.update_entry(session, entry, "downloading")
    store.set_phase(session, "downloading")

    restored = CollectionStore(tmp_path).get(100, 200)
    assert restored is not None
    assert restored.phase == "downloading"
    assert [item.sequence for item in CollectionStore.remaining_entries(restored)] == [1]


def test_collection_journal_checkpoints_large_batches(tmp_path):
    store = CollectionStore(tmp_path)
    session = store.begin(100, 200, "大量文件")
    for message_id in range(1, store.CHECKPOINT_EVERY + 1):
        store.add_entry(session, 100, message_id, "direct")

    assert len(json.loads(session.manifest_path.read_text(encoding="utf-8"))["entries"]) == store.CHECKPOINT_EVERY
    assert not session.manifest_path.with_suffix(".jsonl").exists()
    restored = CollectionStore(tmp_path).get(100, 200)
    assert len(restored.entries) == store.CHECKPOINT_EVERY
