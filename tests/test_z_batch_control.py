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
