import asyncio
import logging
from collections import deque

import asyncpg

from vigil.backend.db import Database

log = logging.getLogger("vigil.writer")

BATCH = 1000
RETRY_S = 1.0


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, asyncio.TimeoutError, asyncpg.InterfaceError)):
        return True
    sqlstate = getattr(exc, "sqlstate", "") or ""
    return sqlstate.startswith("08") or sqlstate.startswith("57P")


class Writer:
    """Ordered write-behind queue. Intake never waits for Postgres."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.lock = asyncio.Lock()
        self._ops: deque[tuple[str, tuple]] = deque()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def minute(self, row: tuple) -> None:
        self._put(("agg", row))

    def alert(self, row: tuple) -> None:
        self._put(("alert", row))

    def _put(self, op: tuple[str, tuple]) -> None:
        self._ops.append(op)
        self._wake.set()

    @property
    def pending(self) -> int:
        return len(self._ops)

    def clear(self) -> None:
        self._ops.clear()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="vigil-writer")

    async def stop(self, timeout: float = 10.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self._ops and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        while True:
            if not self._ops:
                self._wake.clear()
                await self._wake.wait()
                continue
            async with self.lock:
                if not self._ops:
                    continue
                kind, batch = self._take()
                try:
                    async with self.db.pool.acquire() as conn:
                        if kind == "agg":
                            await self.db.write_minutes(conn, batch)
                        else:
                            await self.db.write_alert(conn, batch[0])
                except Exception as exc:
                    if _is_connection_error(exc):
                        log.warning(
                            "postgres unavailable, retrying in %ss: %s", RETRY_S, exc
                        )
                        self._ops.extendleft((kind, row) for row in reversed(batch))
                    else:
                        log.exception("dropping %d %s row(s)", len(batch), kind)
                    retry = True
                else:
                    retry = False
            if retry:
                await asyncio.sleep(RETRY_S)

    def _take(self) -> tuple[str, list[tuple]]:
        kind, row = self._ops.popleft()
        batch = [row]
        if kind == "agg":
            while self._ops and self._ops[0][0] == "agg" and len(batch) < BATCH:
                batch.append(self._ops.popleft()[1])
        return kind, batch
