from vigil.backend.narrate import load_actions, template_text
from vigil.core.context import Ctx
from vigil.core.pipeline import Incident, IncidentMetric

ACTIONS = load_actions("docs/actions.yaml")


def incident(**kw) -> Incident:
    inc = Incident(
        ts_start=0, ts_update=360, level=3, peak_level=3, source="hard", ctx=Ctx.REST
    )
    inc.pattern = "hypoxia"
    inc.metrics["spo2"] = IncidentMetric(
        m="spo2", first_ts=0, value=88.2, usual=(95.5, 99.5), z=-9.3, since_min=6
    )
    inc.metrics["hr"] = IncidentMetric(
        m="hr", first_ts=0, value=71.4, usual=(56.0, 68.0), z=3.1, trend="rising"
    )
    for k, v in kw.items():
        setattr(inc, k, v)
    return inc


def test_actions_file_has_every_pattern():
    for pattern in ("hypoxia", "tachycardia_rest", "bradycardia", "fever_like",
                    "hypercapnia", "depressurization", "default"):  # fmt: skip
        assert ACTIONS[pattern]["critical"]
        assert all(1 <= len(steps) <= 3 for steps in ACTIONS[pattern].values())


def test_text_uses_only_the_incident_numbers():
    text = template_text(incident(), ACTIONS)
    assert text["what"] == "Blood oxygen below the safety limit for 6 minutes"
    assert text["why"] == (
        "88 %, usual 95.5–99.5. Heart rate is rising. "
        "This matches low blood oxygen while resting."
    )
    assert text["action"] == ACTIONS["hypoxia"]["critical"]


def test_unknown_pattern_falls_back_to_default_actions():
    text = template_text(incident(pattern=None, level=1, peak_level=1), ACTIONS)
    assert text["action"] == ACTIONS["default"]["watch"]


def test_no_text_without_actions_or_for_notices():
    assert template_text(incident(), {}) is None
    assert template_text(incident(key="baseline_learned"), ACTIONS) is None
