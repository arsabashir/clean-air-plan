"""Pure logic for Clear Air Plan: data fetching, AQI rules, prompt building, schema.

Nothing here imports Streamlit, so it can be unit tested without a UI.
"""
from typing import List, Literal, Optional

import requests
from pydantic import BaseModel, Field

CAR_KG_CO2_PER_KM = 0.17
TWO_WHEELER_KG_CO2_PER_KM = 0.08
SWAP_SHARE = 0.4  # assumed share of commute emissions saved by swapping 2 of 5 days
MAX_PLACE_LEN = 100
HTTP_TIMEOUT = 10

SYSTEM_PROMPT = """You are an air quality advisor for families and communities in cities with severe winter smog.

Rules:
- Use ONLY the supplied AQI, pollutant and weather numbers. Never invent readings.
- Tailor every action to the household (children, elderly, asthma, commute, home type, heating, cooking fuel, budget) and to the city's realistic options.
- Every action must carry a one-line impact explanation. Any number you give is an estimate and must say so (use "about" or "est.").
- Prefer free or low-cost actions first. Do not tell people to buy expensive gear unless AQI is Unhealthy or worse.
- Recommend N95/FFP2 masks only when AQI > 150, or > 100 for sensitive members. Note that cloth and surgical masks do little against PM2.5.
- Ventilation: open windows only when outdoor AQI is lower than indoor is likely to be; otherwise keep closed and filter.
- No medical diagnoses. For asthma, heart or lung conditions, tell them to follow their doctor's action plan.
- Plain words a 12 year old could follow. No scare language.
"""


# ------------------------------------------------------------------ schema


class Action(BaseModel):
    title: str = Field(description="Short action, max 8 words")
    how: str = Field(description="Plain-language steps, 1-2 sentences, family friendly")
    impact: str = Field(
        description="ONE line explaining the direct effect of this choice on air quality, "
        "health exposure, or emissions. Mark numbers as estimates."
    )
    effort: Literal["easy", "medium", "hard"]
    cost: Literal["free", "low", "medium", "high"]


class Plan(BaseModel):
    headline: str = Field(description="One sentence summary of today's situation for this household")
    risk_level: Literal["low", "moderate", "high", "severe"]
    best_outdoor_window: str
    daily_routine: List[Action] = Field(description="Low-emission daily routine, 4 items")
    indoor_air_hacks: List[Action] = Field(description="4 items")
    sustainable_alternatives: List[Action] = Field(description="3 items, location specific")
    mask_and_health_guidance: str = Field(
        description="Mask advice only if AQI warrants. Name who is most at risk in this household. "
        "No diagnoses. Say when to see a doctor."
    )
    weekly_goal: str = Field(description="One measurable goal the family can hit this week")


# ------------------------------------------------------------------ rules


def sanitize_place(raw: str) -> str:
    """Trim whitespace, collapse spaces and cap length for geocoding input."""
    cleaned = " ".join((raw or "").split())
    return cleaned[:MAX_PLACE_LEN]


def aqi_band(aqi: float) -> tuple[str, str, str]:
    """Return (label, background hex, text hex). Colours meet WCAG AA contrast (4.5:1)."""
    if aqi <= 50:
        return "Good", "#1b7f45", "#ffffff"
    if aqi <= 100:
        return "Moderate", "#f2c200", "#1a1a1a"
    if aqi <= 150:
        return "Unhealthy for sensitive groups", "#b45309", "#ffffff"
    if aqi <= 200:
        return "Unhealthy", "#c62828", "#ffffff"
    if aqi <= 300:
        return "Very unhealthy", "#7b1fa2", "#ffffff"
    return "Hazardous", "#7b1e3a", "#ffffff"


def mask_needed(aqi: float, has_sensitive_member: bool) -> bool:
    """Deterministic safety rule, independent of the model's output."""
    return aqi > 150 or (has_sensitive_member and aqi > 100)


def has_sensitive_member(kids: int, elders: int, conditions: List[str]) -> bool:
    return kids > 0 or elders > 0 or any(c != "None" for c in conditions)


def commute_co2_weekly(mode: str, km_one_way: float, days: int = 5) -> float:
    """Estimated weekly kg CO2 for a round-trip commute. Only car and two-wheeler emit."""
    factors = {"Car": CAR_KG_CO2_PER_KM, "Two-wheeler": TWO_WHEELER_KG_CO2_PER_KM}
    factor = factors.get(mode, 0.0)
    return max(km_one_way, 0) * 2 * days * factor


def swap_saving(weekly_kg: float) -> float:
    return weekly_kg * SWAP_SHARE


# ------------------------------------------------------------------ data


def geocode(place: str) -> Optional[dict]:
    place = sanitize_place(place)
    if not place:
        return None
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": place, "count": 1},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    hits = r.json().get("results") or []
    if not hits:
        return None
    h = hits[0]
    return {
        "name": f'{h["name"]}, {h.get("country", "")}'.rstrip(", "),
        "lat": h["latitude"],
        "lon": h["longitude"],
    }


def parse_conditions(air: dict, wx: dict) -> dict:
    """Turn raw Open-Meteo payloads into the compact dict sent to Gemini."""
    cur_air = air.get("current", {})
    cur_wx = wx.get("current", {})
    hourly = air.get("hourly", {})
    pairs = [
        (t, a)
        for t, a in zip(hourly.get("time", []), hourly.get("us_aqi", []))
        if a is not None
    ]
    best = min(pairs, key=lambda x: x[1]) if pairs else None
    return {
        "aqi": cur_air.get("us_aqi"),
        "pm25": cur_air.get("pm2_5"),
        "pm10": cur_air.get("pm10"),
        "no2": cur_air.get("nitrogen_dioxide"),
        "ozone": cur_air.get("ozone"),
        "temp_c": cur_wx.get("temperature_2m"),
        "humidity": cur_wx.get("relative_humidity_2m"),
        "wind_kmh": cur_wx.get("wind_speed_10m"),
        "cleanest_hour_today": best[0][-5:] if best else None,
        "cleanest_hour_aqi": best[1] if best else None,
    }


def fetch_conditions(lat: float, lon: float) -> dict:
    air = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm2_5,pm10,nitrogen_dioxide,ozone",
            "hourly": "us_aqi",
            "forecast_days": 1,
            "timezone": "auto",
        },
        timeout=HTTP_TIMEOUT,
    )
    air.raise_for_status()
    wx = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "timezone": "auto",
        },
        timeout=HTTP_TIMEOUT,
    )
    wx.raise_for_status()
    return parse_conditions(air.json(), wx.json())


def build_prompt(location_name: str, conditions: dict, profile: dict) -> str:
    return (
        f"Location: {location_name}\n"
        f"Live conditions: {conditions}\n"
        f"Household: {profile}\n"
        "Build today's plan."
    )
