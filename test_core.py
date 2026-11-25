import pytest
from pydantic import ValidationError

import core


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    chans = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(f, chans)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted([_lum(a), _lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- AQI bands


@pytest.mark.parametrize(
    "aqi,label",
    [
        (0, "Good"),
        (50, "Good"),
        (51, "Moderate"),
        (100, "Moderate"),
        (101, "Unhealthy for sensitive groups"),
        (150, "Unhealthy for sensitive groups"),
        (151, "Unhealthy"),
        (200, "Unhealthy"),
        (201, "Very unhealthy"),
        (300, "Very unhealthy"),
        (301, "Hazardous"),
        (500, "Hazardous"),
    ],
)
def test_aqi_band_boundaries(aqi, label):
    assert core.aqi_band(aqi)[0] == label


@pytest.mark.parametrize("aqi", [25, 75, 125, 175, 250, 400])
def test_aqi_band_colours_meet_wcag_aa(aqi):
    _, bg, fg = core.aqi_band(aqi)
    assert contrast(bg, fg) >= 4.5


# ---------------------------------------------------------------- safety rules


def test_mask_needed_thresholds():
    assert core.mask_needed(151, False)
    assert not core.mask_needed(150, False)
    assert core.mask_needed(101, True)
    assert not core.mask_needed(100, True)
    assert not core.mask_needed(60, True)


def test_has_sensitive_member():
    assert core.has_sensitive_member(1, 0, ["None"])
    assert core.has_sensitive_member(0, 1, ["None"])
    assert core.has_sensitive_member(0, 0, ["Asthma"])
    assert not core.has_sensitive_member(0, 0, ["None"])
    assert not core.has_sensitive_member(0, 0, [])


# ---------------------------------------------------------------- impact maths


def test_commute_co2_car():
    # 10 km each way, 5 days: 10 * 2 * 5 * 0.17 = 17 kg
    assert core.commute_co2_weekly("Car", 10) == pytest.approx(17.0)


def test_commute_co2_non_emitting_modes_are_zero():
    for mode in ("Bus / metro", "Walk / cycle", "Work from home"):
        assert core.commute_co2_weekly(mode, 20) == 0


def test_commute_co2_never_negative():
    assert core.commute_co2_weekly("Car", -5) == 0


def test_swap_saving_is_share_of_weekly():
    assert core.swap_saving(10) == pytest.approx(4.0)


# ---------------------------------------------------------------- input handling


def test_sanitize_place_trims_and_collapses():
    assert core.sanitize_place("  New   Delhi \n") == "New Delhi"


def test_sanitize_place_caps_length():
    assert len(core.sanitize_place("a" * 500)) == core.MAX_PLACE_LEN


def test_sanitize_place_handles_none():
    assert core.sanitize_place(None) == ""


# ---------------------------------------------------------------- data parsing


AIR = {
    "current": {"us_aqi": 143, "pm2_5": 74.0, "pm10": 90.1, "nitrogen_dioxide": 20, "ozone": 30},
    "hourly": {
        "time": ["2026-11-21T00:00", "2026-11-21T14:00", "2026-11-21T15:00"],
        "us_aqi": [160, 98, None],
    },
}
WX = {"current": {"temperature_2m": 4.1, "relative_humidity_2m": 45, "wind_speed_10m": 0.4}}


def test_parse_conditions_maps_fields():
    c = core.parse_conditions(AIR, WX)
    assert c["aqi"] == 143
    assert c["pm25"] == 74.0
    assert c["humidity"] == 45
    assert c["wind_kmh"] == 0.4


def test_parse_conditions_picks_cleanest_hour_and_skips_none():
    c = core.parse_conditions(AIR, WX)
    assert c["cleanest_hour_today"] == "14:00"
    assert c["cleanest_hour_aqi"] == 98


def test_parse_conditions_survives_empty_payloads():
    c = core.parse_conditions({}, {})
    assert c["aqi"] is None
    assert c["cleanest_hour_today"] is None


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_geocode_returns_none_when_no_hits(monkeypatch):
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: _Resp({}))
    assert core.geocode("Nowhereville") is None


def test_geocode_returns_location(monkeypatch):
    payload = {"results": [{"name": "Srinagar", "country": "India", "latitude": 34.08, "longitude": 74.8}]}
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: _Resp(payload))
    loc = core.geocode("Srinagar")
    assert loc == {"name": "Srinagar, India", "lat": 34.08, "lon": 74.8}


def test_geocode_blank_input_skips_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network should not be called")

    monkeypatch.setattr(core.requests, "get", boom)
    assert core.geocode("   ") is None


def test_fetch_conditions_combines_both_apis(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp(AIR if "air-quality" in url else WX)

    monkeypatch.setattr(core.requests, "get", fake_get)
    c = core.fetch_conditions(34.08, 74.8)
    assert c["aqi"] == 143 and c["temp_c"] == 4.1


# ---------------------------------------------------------------- prompt + schema


def test_build_prompt_includes_real_numbers_and_profile():
    p = core.build_prompt("Srinagar, India", {"aqi": 143}, {"children_under_12": 1})
    assert "Srinagar, India" in p
    assert "143" in p
    assert "children_under_12" in p


def test_system_prompt_contains_safety_rules():
    s = core.SYSTEM_PROMPT
    assert "Never invent readings" in s
    assert "No medical diagnoses" in s
    assert "N95" in s


def _action():
    return {"title": "t", "how": "h", "impact": "i", "effort": "easy", "cost": "free"}


def _plan(**over):
    base = {
        "headline": "h",
        "risk_level": "high",
        "best_outdoor_window": "2-4 pm",
        "daily_routine": [_action()],
        "indoor_air_hacks": [_action()],
        "sustainable_alternatives": [_action()],
        "mask_and_health_guidance": "g",
        "weekly_goal": "w",
    }
    base.update(over)
    return base


def test_plan_schema_accepts_valid_payload():
    assert core.Plan(**_plan()).risk_level == "high"


def test_plan_schema_rejects_bad_risk_level():
    with pytest.raises(ValidationError):
        core.Plan(**_plan(risk_level="apocalyptic"))


def test_plan_schema_rejects_bad_effort():
    bad = _action()
    bad["effort"] = "impossible"
    with pytest.raises(ValidationError):
        core.Plan(**_plan(daily_routine=[bad]))
