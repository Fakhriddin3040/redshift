import pytest
from litestar import Litestar, Router
from litestar.datastructures import State
from litestar.di import Provide
from litestar.testing import AsyncTestClient

from tests.llm.test_ask import T0, FakeLLM
from tests.llm.test_explain import hub_with, minute_frame
from vigil.backend.api.routes import ROUTES
from vigil.llm import ask

# The routes use Litestar's older parameter style; its notices are not about this test.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


class FakeDB:
    async def incidents_between(self, crew_id, start_ts, end_ts):
        return []

    async def sleep_minutes(self, since_ts):
        return []


def client(llm, with_data: bool = True) -> AsyncTestClient:
    hub, _, writer = hub_with(None)
    hub.db, writer.pending = FakeDB(), 0
    if with_data:
        hub.handle_frame(minute_frame(T0 + 600, 97.0))
    app = Litestar(
        route_handlers=[Router(path="/api/v1", route_handlers=ROUTES)],
        dependencies={"hub": Provide(lambda: hub, sync_to_thread=False)},
        state=State({"asker": ask.Asker(llm, 5, 300) if llm else None}),
    )
    return AsyncTestClient(app)


async def test_question_is_answered_from_the_crew_members_record():
    llm = FakeLLM("Your blood oxygen is 97 % and its status is usual.")
    async with client(llm) as c:
        body = {"question": "  How is my\n oxygen? ", "history": [{"role": "x"}]}
        res = await c.post("/api/v1/crew/1/ask", json=body)
        assert res.status_code == 200
        assert res.json() == {"answer": "Your blood oxygen is 97 % and its status is usual.",
                              "src": "llm"}  # fmt: skip
        messages, _ = llm.calls[0]
        assert messages[-1]["content"] == "How is my oxygen?"
        assert '"value": "97 %"' in messages[0]["content"]
        assert (await c.get("/api/v1/health")).json()["ask"] is True


async def test_bad_questions_and_unknown_crew_are_refused_before_the_model():
    llm = FakeLLM("never used")
    async with client(llm) as c:
        for body in ({}, {"question": "   "}, {"question": 7}, {"question": "x" * 301}):
            assert (await c.post("/api/v1/crew/1/ask", json=body)).status_code == 400
        res = await c.post("/api/v1/crew/9/ask", json={"question": "Hi?"})
        assert res.status_code == 404
    async with client(llm, with_data=False) as c:
        res = await c.post("/api/v1/crew/1/ask", json={"question": "Hi?"})
        assert res.status_code == 400 and "no data" in res.json()["detail"]
    assert llm.calls == []


async def test_ask_answers_503_when_no_model_is_configured():
    async with client(None) as c:
        res = await c.post("/api/v1/crew/1/ask", json={"question": "Hi?"})
        assert res.status_code == 503
        assert (await c.get("/api/v1/health")).json()["ask"] is False
