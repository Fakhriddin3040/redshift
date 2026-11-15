import asyncio

from tests.backend.test_ingest import FakeWriter
from tests.backend.test_narrate import ACTIONS, incident
from vigil.backend.hub import CrewRuntime, Hub
from vigil.core.frame import Flag, Frame, pack
from vigil.llm import explain
from vigil.llm.provider import LLMError


def test_summary_has_no_identity_and_only_formatted_values():
    s = explain.summary(incident())
    assert s["level"] == "critical" and s["pattern"] == "low blood oxygen"
    first = s["readings"][0]
    assert first == {"reading": "blood oxygen", "value": "88 %", "trend": "stable",
                     "usual_range": "95.5–99.5 %", "direction": "below", "minutes": 6}  # fmt: skip
    assert "crew" not in str(s) and "id" not in s
    assert explain.summary(incident(key="baseline_learned")) is None


def test_answer_with_only_known_numbers_is_accepted():
    s = explain.summary(incident())
    good = "Blood oxygen is 88 %, below the usual 95.5–99.5 %, for 6 minutes while heart rate is 71 bpm and rising."
    assert explain.problems(good, s) == []
    assert explain.clean('WHY: "Blood oxygen is 88 %."') == "Blood oxygen is 88 %."


def test_answers_that_invent_numbers_or_patterns_are_rejected():
    s = explain.summary(incident())
    assert explain.problems("Blood oxygen fell to 85 %, far below the usual range.", s)
    assert explain.problems("Blood oxygen is 88 %; this looks like high cabin CO₂.", s)
    assert explain.problems("Too short.", s)
    assert explain.problems("x" * 600, s)
    assert explain.problems("- Blood oxygen is 88 % which is low for this person.", s)


class FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply, self.calls = reply, []

    async def chat(self, messages):
        self.calls.append(messages)
        await asyncio.sleep(0)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def usage(self) -> dict[str, int]:
        return {"requests": len(self.calls)}

    async def aclose(self) -> None:
        return None


def hub_with(llm) -> tuple[Hub, CrewRuntime, FakeWriter]:
    writer = FakeWriter()
    hub = Hub(db=None, writer=writer, actions=ACTIONS, llm=llm)
    rt = CrewRuntime(id=1, name="A", role="FE", dev_id=11, share={})
    hub.crews, hub.by_dev = {1: rt}, {11: rt}
    return hub, rt, writer


def minute_frame(ts: int, spo2: float, history: bool = False) -> bytes:
    flags = Flag.WORN | (Flag.HISTORY if history else 0)
    return pack(Frame(type=2, dev_id=11, ts=ts, hr=60.0, spo2=spo2, rr=14.0,
                      skin_t=33.5, act_mg=20, sqi=90, flags=flags))  # fmt: skip


async def settle(hub: Hub) -> None:
    while hub._llm_tasks:
        await asyncio.gather(*hub._llm_tasks)


async def test_llm_explanation_replaces_the_template_why_and_survives_updates():
    llm = FakeLLM("Blood oxygen is 88 %, at the fixed safety limit, while resting.")
    hub, rt, _ = hub_with(llm)
    hub.handle_frame(minute_frame(600, 88.0))
    inc = rt.state.incident
    assert inc.level == 3 and inc.text_src == "template"
    await settle(hub)
    assert inc.text_src == "llm"
    assert (
        inc.text["why"]
        == "Blood oxygen is 88 %, at the fixed safety limit, while resting."
    )
    assert (
        inc.text["action"] == ACTIONS["hypoxia"]["critical"]
    )  # steps never come from the model
    template_what = inc.text["what"]

    for ts in (660, 720):  # same level, later minutes
        hub.handle_frame(minute_frame(ts, 88.0))
    await settle(hub)
    assert len(llm.calls) == 1  # asked once per level, not every minute
    assert inc.text_src == "llm" and "88 %" in inc.text["why"]
    assert inc.text["what"] != template_what  # the title keeps counting minutes


async def test_rejected_or_failed_answers_keep_the_template():
    for reply in (
        "Blood oxygen dropped to 70 %, which is dangerous.",
        LLMError("down"),
    ):
        llm = FakeLLM(reply)
        hub, rt, _ = hub_with(llm)
        hub.handle_frame(minute_frame(600, 88.0))
        await settle(hub)
        inc = rt.state.incident
        assert len(llm.calls) == 1
        assert inc.text_src == "template" and inc.text["why"].startswith("88 %")


async def test_history_and_missing_llm_never_call_the_model():
    llm = FakeLLM("Blood oxygen is 88 %, at the fixed safety limit, while resting.")
    hub, rt, _ = hub_with(llm)
    hub.handle_frame(minute_frame(600, 88.0, history=True))
    await settle(hub)
    assert llm.calls == [] and rt.state.incident.text_src == "template"

    hub, rt, _ = hub_with(None)
    hub.handle_frame(minute_frame(600, 88.0))
    assert rt.state.incident.text_src == "template"
