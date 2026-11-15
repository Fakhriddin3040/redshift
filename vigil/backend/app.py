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
from vigil.backend.narrate import load_actions
from vigil.backend.writer import Writer
from vigil.core.pattern_model import PatternModel
from vigil.llm import create_provider, get_llm_settings
from vigil.llm.ask import create_asker

API_PREFIX = "/api/v1"
log = logging.getLogger("vigil.app")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    settings = get_settings()
    db = await Database.connect(settings.database_url)
    await db.init_schema()
    writer = Writer(db)
    model = PatternModel.load(settings.pattern_model)
    log.info("pattern model: %s", "loaded" if model else "not found, using the rule")
    llm_settings = get_llm_settings()
    llm = create_provider(llm_settings)
    app.state.asker = create_asker(llm, llm_settings)
    log.info("ask vigil: %s", "on" if app.state.asker else "off")
    hub = Hub(db, writer, load_actions(settings.actions_file), model, llm)
    await hub.load()
    await hub.load_radiation()
    writer.start()
    app.state.hub = hub
    app.state.vdev = httpx.AsyncClient(base_url=settings.vdev_url, timeout=5.0)
    try:
        yield
    finally:
        await writer.stop()
        await app.state.vdev.aclose()
        if llm is not None:
            await llm.aclose()
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
