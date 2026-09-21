import asyncio

from core.download_scheduler import DownloadScheduler


async def test_scheduler_shares_global_limit_and_round_robins_groups():
    scheduler = DownloadScheduler(max_concurrency=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    order = []

    async def first():
        order.append("a1")
        first_started.set()
        await release_first.wait()
        return "success", None, None

    async def item(name):
        async def run():
            order.append(name)
            return "success", None, None
        return run

    task_a = asyncio.create_task(scheduler.submit("a", [first, await item("a2"), await item("a3")]))
    await first_started.wait()
    task_b = asyncio.create_task(scheduler.submit("b", [await item("b1")]))
    await asyncio.sleep(0)
    release_first.set()
    await asyncio.gather(task_a, task_b)

    assert order == ["a1", "b1", "a2", "a3"]
    assert scheduler.active == 0
    assert scheduler.target_concurrency == 1
    await scheduler.close()


async def test_scheduler_adapts_concurrency_to_success_and_failure():
    scheduler = DownloadScheduler(max_concurrency=3, cooldown_seconds=0.02)
    assert scheduler.target_concurrency == 3

    async def result(value):
        async def run():
            return value, None, None
        return run

    await scheduler.submit("batch", [await result("success"), await result("success")])
    assert scheduler.target_concurrency == 3
    await scheduler.submit("batch", [await result("failed")])
    assert scheduler.target_concurrency == 3  # Permanent item errors do not throttle the queue.
    assert scheduler.failed == 1
    await scheduler.report_throttle()
    assert scheduler.target_concurrency == 1
    await asyncio.sleep(0.03)
    assert scheduler.target_concurrency == 3
    assert scheduler.throttles == 1
    await scheduler.close()


async def test_scheduler_uses_configured_parallelism_for_long_batches():
    scheduler = DownloadScheduler(max_concurrency=3)
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def work():
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.005)
        async with lock:
            active -= 1
        return "success", None, None

    await scheduler.submit("large", [work for _ in range(12)])
    assert peak == 3
    assert scheduler.target_concurrency == 3
    await scheduler.close()


async def test_scheduler_cancels_queued_and_active_group_work():
    scheduler = DownloadScheduler(max_concurrency=1)
    started = asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    submit_task = asyncio.create_task(scheduler.submit("cancel-me", [blocked, blocked]))
    await started.wait()
    count = await scheduler.cancel_group("cancel-me")
    assert count == 2
    try:
        await submit_task
    except asyncio.CancelledError:
        pass
    assert scheduler.active == 0
    await scheduler.close()
