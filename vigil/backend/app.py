import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from litestar import Litestar, Router
from litestar.config.cors import CORSConfig
from litestar.datastructures import State
from litestar.di import Provide
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin

from vigil.backend.api.routes import ROUTES
from vigil.backend.config import get_settings
from vigil.backend.db import Database
from vigil.backend.hub import Hub
from vigil.backend.writer import Writer

API_PREFIX = "/api/v1"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    settings = get_settings()
    db = await Database.connect(settings.database_url)
    await db.init_schema()
    writer = Writer(db)
    hub = Hub(db, writer)
    await hub.load()
    writer.start()
    app.state.hub = hub
    app.state.vdev = httpx.AsyncClient(base_url=settings.vdev_url, timeout=5.0)
    try:
        yield
    finally:
        await writer.stop()
        await app.state.vdev.aclose()
        await db.close()


def provide_hub(state: State) -> Hub:
    return state.hub


def create_app() -> Litestar:
    settings = get_settings()
    return Litestar(
        route_handlers=[Router(path=API_PREFIX, route_handlers=ROUTES)],
        lifespan=[lifespan],
        dependencies={"hub": Provide(provide_hub, sync_to_thread=False)},
        cors_config=CORSConfig(
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        openapi_config=OpenAPIConfig(
            title="Vigil",
            version="0.1.0",
            path=f"{API_PREFIX}/docs",
            render_plugins=[SwaggerRenderPlugin(path="/swagger")],
        ),
    )


app = create_app()
