"""Process-wide fair scheduler for media downloads."""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable, Any


@dataclass
class _Job:
    group: str
    run: Callable[[], Awaitable[Any]]
    future: asyncio.Future[Any]


class DownloadScheduler:
    """Round-robin download queue with additive increase/multiplicative decrease."""

    def __init__(self, max_concurrency: int = 2, min_concurrency: int = 1, cooldown_seconds: float = 30):
        self.max_concurrency = max(1, int(max_concurrency))
        self.min_concurrency = max(1, min(int(min_concurrency), self.max_concurrency))
        # Honor the configured throughput immediately; only back off on
        # genuine transport/API pressure, then restore the cap after cooldown.
        self.target_concurrency = self.max_concurrency
        self.cooldown_seconds = max(0.01, float(cooldown_seconds))
        self._cooldown_until = 0.0
        self._recovery_task: asyncio.Task[None] | None = None
        self._active = 0
        self._queues: OrderedDict[str, deque[_Job]] = OrderedDict()
        self._active_tasks: dict[str, set[asyncio.Task[Any]]] = {}
        self._labels: dict[str, str] = {}
        self._last_served: str | None = None
        self._condition = asyncio.Condition()
        self._workers: list[asyncio.Task[None]] = []
        self.completed = 0
        self.failed = 0
        self.throttles = 0

    @property
    def active(self) -> int:
        return self._active

    @property
    def pending(self) -> int:
        return sum(map(len, self._queues.values()))

    def snapshot(self) -> list[dict[str, Any]]:
        groups = list(dict.fromkeys([*self._queues, *self._active_tasks]))
        return [
            {"group": key, "label": self._labels.get(key, key),
             "pending": len(queue), "active": len(self._active_tasks.get(key, ())) }
            for key in groups
            for queue in [self._queues.get(key, ())]
            if queue or self._active_tasks.get(key)
        ]

    async def report_throttle(self) -> None:
        self.throttles += 1
        await self.report_backpressure()

    async def report_backpressure(self) -> None:
        self.target_concurrency = max(self.min_concurrency, self.target_concurrency // 2)
        self._cooldown_until = asyncio.get_running_loop().time() + self.cooldown_seconds
        if self._recovery_task is None or self._recovery_task.done():
            self._recovery_task = asyncio.create_task(self._recover_after_cooldown())
        async with self._condition:
            self._condition.notify_all()

    async def _recover_after_cooldown(self) -> None:
        loop = asyncio.get_running_loop()
        while (remaining := self._cooldown_until - loop.time()) > 0:
            await asyncio.sleep(remaining)
        self.target_concurrency = self.max_concurrency
        async with self._condition:
            self._condition.notify_all()

    async def submit(self, group: str, jobs: list[Callable[[], Awaitable[Any]]], label: str | None = None) -> list[Any]:
        if not jobs:
            return []
        loop = asyncio.get_running_loop()
        futures = [loop.create_future() for _ in jobs]
        async with self._condition:
            if label:
                self._labels[group] = label
            self._workers = [worker for worker in self._workers if not worker.done()]
            queue = self._queues.get(group)
            if queue is None:
                queue = deque()
                if self._last_served in self._queues:
                    self._queues[group] = queue
                    self._queues.move_to_end(group, last=False)
                else:
                    self._queues[group] = queue
            for run, future in zip(jobs, futures):
                queue.append(_Job(group, run, future))
            while len(self._workers) < self.max_concurrency:
                self._workers.append(asyncio.create_task(self._worker()))
            self._condition.notify_all()
        return await asyncio.gather(*futures)

    async def cancel_group(self, group: str) -> int:
        async with self._condition:
            queue = self._queues.pop(group, deque())
            cancelled = 0
            for job in queue:
                if not job.future.done():
                    job.future.cancel()
                    cancelled += 1
            for task in tuple(self._active_tasks.get(group, ())):
                task.cancel()
                cancelled += 1
            self._condition.notify_all()
            return cancelled

    async def _next_job(self) -> _Job:
        async with self._condition:
            await self._condition.wait_for(lambda: self.pending > 0 and self._active < self.target_concurrency)
            group, queue = self._queues.popitem(last=False)
            self._last_served = group
            job = queue.popleft()
            if queue:
                self._queues[group] = queue
            self._active += 1
            return job

    async def _worker(self) -> None:
        while True:
            job = await self._next_job()
            run_task = asyncio.create_task(job.run())
            self._active_tasks.setdefault(job.group, set()).add(run_task)
            try:
                result = await run_task
                if not job.future.done():
                    job.future.set_result(result)
                self.completed += 1
                if isinstance(result, tuple) and result and result[0] == "failed":
                    self.failed += 1
                else:
                    if asyncio.get_running_loop().time() >= self._cooldown_until:
                        self.target_concurrency = min(self.max_concurrency, self.target_concurrency + 1)
            except asyncio.CancelledError:
                if not job.future.done():
                    job.future.cancel()
                if not run_task.cancelled():
                    run_task.cancel()
                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise
            except Exception as exc:
                self.failed += 1
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                active_for_group = self._active_tasks.get(job.group, set())
                active_for_group.discard(run_task)
                if not active_for_group:
                    self._active_tasks.pop(job.group, None)
                    if job.group not in self._queues:
                        self._labels.pop(job.group, None)
                self._active -= 1
                async with self._condition:
                    self._condition.notify_all()

    async def close(self) -> None:
        if self._recovery_task:
            self._recovery_task.cancel()
            await asyncio.gather(self._recovery_task, return_exceptions=True)
            self._recovery_task = None
        for queue in self._queues.values():
            for job in queue:
                if not job.future.done():
                    job.future.cancel()
        self._queues.clear()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
