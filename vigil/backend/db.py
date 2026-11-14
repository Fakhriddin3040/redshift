import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import asyncpg

AGG_COLUMNS = (
    "crew_id", "ts", "hr", "spo2", "rr", "skin_t", "hrv",
    "co2_ppm", "press_hpa", "amb_t", "ppco2", "act_mg", "sqi", "worn_frac", "valid_s",
    "ctx", "z_hr", "z_spo2", "z_rr", "z_skin_t",
    "lo_hr", "hi_hr", "lo_spo2", "hi_spo2", "lo_rr", "hi_rr", "lo_skin_t", "hi_skin_t",
    "level", "learn_mask",
)  # fmt: skip

ALERT_COLUMNS = (
    "id", "crew_id", "key", "source", "ts_start", "ts_update", "ts_end",
    "level", "peak_level", "pattern", "p", "ctx", "metrics", "text", "text_src", "ack_ts",
)  # fmt: skip

METRIC_COLUMNS = {
    "hr": ("hr", "lo_hr", "hi_hr"),
    "spo2": ("spo2", "lo_spo2", "hi_spo2"),
    "rr": ("rr", "lo_rr", "hi_rr"),
    "skin_t": ("skin_t", "lo_skin_t", "hi_skin_t"),
    "ppco2": ("ppco2", None, None),
    "press": ("press_hpa", None, None),
    "amb_t": ("amb_t", None, None),
}


def _upsert_sql(table: str, columns: tuple[str, ...], key: str) -> str:
    cols = ", ".join(columns)
    params = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in key)
    return f"insert into {table} ({cols}) values ({params}) on conflict ({key}) do update set {updates}"


AGG_UPSERT = _upsert_sql("agg_1m", AGG_COLUMNS, "crew_id, ts")
ALERT_UPSERT = _upsert_sql("alert", ALERT_COLUMNS, "id")


def to_dt(ts: int | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(ts, UTC)


def to_ts(dt: datetime | None) -> int | None:
    return None if dt is None else int(dt.timestamp())


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, url: str) -> Database:
        pool = await asyncpg.create_pool(url, min_size=1, max_size=5, init=_init_conn)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def init_schema(self) -> None:
        sql = files("vigil.backend").joinpath("schema.sql").read_text()
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def crews(self) -> list[asyncpg.Record]:
        return await self.pool.fetch("select * from crew order by id")

    async def last_minute_ts(self, crew_id: int) -> int | None:
        return to_ts(
            await self.pool.fetchval(
                "select max(ts) from agg_1m where crew_id = $1", crew_id
            )
        )

    async def first_minute_ts(self, crew_id: int) -> int | None:
        return to_ts(
            await self.pool.fetchval(
                "select min(ts) from agg_1m where crew_id = $1", crew_id
            )
        )

    async def minutes_since(self, crew_id: int, since_ts: int) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "select * from agg_1m where crew_id = $1 and ts > $2 order by ts",
            crew_id,
            to_dt(since_ts),
        )

    async def open_alerts(self) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "select * from alert where ts_end is null order by id"
        )

    async def alert_keys(self, crew_id: int) -> set[str]:
        rows = await self.pool.fetch(
            "select distinct key from alert where crew_id = $1", crew_id
        )
        return {r["key"] for r in rows}

    async def max_alert_id(self) -> int:
        return await self.pool.fetchval("select coalesce(max(id), 0) from alert")

    async def alerts(self, crew_id: int) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "select * from alert where crew_id = $1 order by ts_start desc, id desc",
            crew_id,
        )

    async def alert(self, alert_id: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow("select * from alert where id = $1", alert_id)

    async def ack_alert(self, alert_id: int, ack_ts: int) -> asyncpg.Record | None:
        return await self.pool.fetchrow(
            "update alert set ack_ts = coalesce(ack_ts, $2) where id = $1 returning *",
            alert_id,
            to_dt(ack_ts),
        )

    async def incidents_between(
        self, crew_id: int, start_ts: int, end_ts: int
    ) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            """select * from alert
               where crew_id = $1 and key = 'incident' and ts_start <= $3
                 and (ts_end is null or ts_end >= $2)
               order by ts_start""",
            crew_id,
            to_dt(start_ts),
            to_dt(end_ts),
        )

    async def metric_points(
        self, crew_id: int, metric: str, start_ts: int, end_ts: int
    ) -> list[tuple[int, Any, Any, Any, int]]:
        value, lo, hi = METRIC_COLUMNS[metric]
        rows = await self.pool.fetch(
            f"""select ts, {value} as v, {lo or "null::real"} as lo,
                       {hi or "null::real"} as hi, ctx
                from agg_1m where crew_id = $1 and ts between $2 and $3 order by ts""",
            crew_id,
            to_dt(start_ts),
            to_dt(end_ts),
        )
        return [(to_ts(r["ts"]), r["v"], r["lo"], r["hi"], r["ctx"]) for r in rows]

    async def write_minutes(self, conn: asyncpg.Connection, rows: list[tuple]) -> None:
        if len(rows) == 1:
            await conn.execute(AGG_UPSERT, *rows[0])
            return
        try:
            async with conn.transaction():
                await conn.copy_records_to_table(
                    "agg_1m", records=rows, columns=AGG_COLUMNS
                )
        except asyncpg.UniqueViolationError:
            await conn.executemany(AGG_UPSERT, rows)

    async def write_alert(self, conn: asyncpg.Connection, row: tuple) -> None:
        await conn.execute(ALERT_UPSERT, *row)

    async def wipe(self) -> None:
        await self.pool.execute(
            "truncate agg_1m, alert, checkin, report restart identity"
        )
