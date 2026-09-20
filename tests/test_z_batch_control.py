import asyncio

import pytest

from core.batch import BatchController


@pytest.mark.asyncio
async def test_paused_batch_waits_then_resumes():
    controller = BatchController()
    assert await controller.start_batch(1, 2, 10, 100, "public", 200)
    assert await controller.pause_batch(1)

    waiter = asyncio.create_task(controller.wait_until_runnable(1))
    await asyncio.sleep(0)
    assert not waiter.done()

    assert await controller.resume_batch(1)
    assert await waiter is True


@pytest.mark.asyncio
async def test_cancelling_batch_cancels_processor_task():
    controller = BatchController()
    assert await controller.start_batch(1, 2, 10, 100, "public", 200)
    processor = asyncio.create_task(asyncio.sleep(60))
    assert await controller.attach_task(1, processor)

    assert await controller.cancel_batch(1)
    await asyncio.sleep(0)
    assert processor.cancelled()
    assert await controller.wait_until_runnable(1) is False

@pytest.mark.asyncio
async def test_parallel_manager_uses_bounded_worker_pool():
    from core.managers.download_manager import DownloadManager, DownloadTask

    manager = DownloadManager(max_concurrent=2)
    active = 0
    peak = 0

    async def fetch(*_args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return object()

    async def process(*_args):
        return "[OK] done"

    tasks = [DownloadTask(1, message_id, "public", 2, 3) for message_id in range(10)]
    results = await manager.download_batch_parallel(None, None, tasks, fetch, process)

    assert len(results) == len(tasks)
    assert peak == 2
    assert manager.active_tasks == []


def test_retry_classification_and_media_size_helpers():
    from core.bot import get_media_file_size, is_retryable_error, parse_link

    media = type("Message", (), {"document": None, "video": type("Video", (), {"file_size": 42})()})()
    assert get_media_file_size(media) == 42
    assert is_retryable_error(TimeoutError())
    assert not is_retryable_error(ValueError("invalid media type"))
    assert parse_link("https://t.me/example_channel/42") == ("example_channel", 42, "public")


def test_active_collection_directories_are_protected(tmp_path):
    import json
    from core.handlers.cleanup import _active_collection_directories

    active = tmp_path / "active"
    completed = tmp_path / "completed"
    active.mkdir()
    completed.mkdir()
    (active / ".tgdl_collection_1_2.json").write_text(json.dumps({"phase": "collecting"}))
    (completed / ".tgdl_collection_1_2.json").write_text(json.dumps({"phase": "completed"}))

    assert str(active) in _active_collection_directories(str(tmp_path))
    assert str(completed) not in _active_collection_directories(str(tmp_path))
