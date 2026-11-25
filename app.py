"""
Clear Air Plan (PromptWars Challenge 6: Urban Air Quality Assistant)
Live AQI + weather -> Gemini -> a personal plan with the impact of every choice explained.

Run:
  python -m pip install -r requirements.txt
  set GEMINI_API_KEY=your_key        (Mac/Linux: export GEMINI_API_KEY=your_key)
  python -m streamlit run app.py

Tests:
  python -m pip install -r requirements-dev.txt
  python -m pytest
"""
import html
import os
from typing import List

import streamlit as st
from google import genai
from google.genai import types

import core

MODEL = "gemini-2.5-flash"


@st.cache_data(ttl=600, show_spinner=False)
def cached_geocode(place: str):
    return core.geocode(place)


@st.cache_data(ttl=600, show_spinner=False)
def cached_conditions(lat: float, lon: float):
    return core.fetch_conditions(lat, lon)


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if key:
        return key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return ""


def generate_plan(api_key: str, prompt: str) -> core.Plan:
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(api_version="v1beta", timeout=60000),
    )
    last_error = None
    for _ in range(2):  # one retry for transient failures
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=core.SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=core.Plan,
                    temperature=0.4,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            if resp.parsed is None:
                raise ValueError("Model returned no structured plan.")
            return resp.parsed
        except Exception as e:  # noqa: BLE001
            last_error = e
    raise last_error


def render_actions(title: str, items: List[core.Action]):
    st.markdown(f"### {title}")
    for a in items:
        with st.expander(f"{a.title} (effort: {a.effort}, cost: {a.cost})"):
            st.write(a.how)
            st.markdown(f"**Why it matters:** {a.impact}")


# ---------------------------------------------------------------- page

st.set_page_config(page_title="Clear Air Plan", page_icon="🌫️", layout="centered")
st.markdown(
    '<h1><span aria-hidden="true">🌫️</span> Clear Air Plan</h1>', unsafe_allow_html=True
)
st.caption(
    "Live air data and Gemini build a daily plan for your family, "
    "with the impact of each choice explained."
)

api_key = get_api_key()
if not api_key:
    api_key = st.sidebar.text_input(
        "Gemini API key", type="password", help="Get a free key at aistudio.google.com"
    )

with st.form("profile"):
    st.markdown("#### About your household")
    place = st.text_input(
        "City or area",
        placeholder="Delhi, Lahore, Kathmandu, Srinagar...",
        max_chars=core.MAX_PLACE_LEN,
        help="Type the nearest city. Air data is looked up for this place.",
    )
    c1, c2 = st.columns(2)
    kids = c1.number_input("Children under 12", 0, 10, 0, help="How many kids live with you")
    elders = c2.number_input("Adults over 65", 0, 10, 0, help="How many older adults live with you")
    conditions = st.multiselect(
        "Health conditions in the household",
        ["Asthma", "COPD / lung disease", "Heart condition", "Pregnancy", "None"],
        default=["None"],
        help="Used only to tailor advice. Nothing is stored.",
    )
    commute = st.selectbox(
        "Main commute", ["Car", "Two-wheeler", "Bus / metro", "Walk / cycle", "Work from home"]
    )
    km = st.slider("Daily commute distance in km (one way)", 0, 60, 8)
    home = st.selectbox("Home type", ["Apartment", "House", "Shared / informal housing"])
    heating = st.selectbox(
        "Heating and cooking",
        ["Electric", "Gas", "Wood / charcoal / biomass", "Kerosene", "None"],
    )
    budget = st.select_slider(
        "Budget for changes", ["none", "low", "medium", "flexible"], value="low"
    )
    demo_aqi = st.number_input(
        "Override AQI for demos (0 uses live data)",
        0,
        500,
        0,
        help="Enter a value like 250 to simulate a heavy smog day.",
    )
    go = st.form_submit_button("Build my plan", type="primary")

if go:
    if not api_key:
        st.error("Add a Gemini API key in the sidebar first.")
        st.stop()
    place = core.sanitize_place(place)
    if not place:
        st.error("Enter a city or area.")
        st.stop()

    try:
        loc = cached_geocode(place)
    except Exception:
        st.error("The location service did not respond. Please try again in a minute.")
        st.stop()
    if not loc:
        st.error("Could not find that place. Try the nearest large city.")
        st.stop()

    try:
        cond = dict(cached_conditions(loc["lat"], loc["lon"]))
    except Exception:
        st.error("The air quality service did not respond. Please try again in a minute.")
        st.stop()

    if demo_aqi:
        cond["aqi"] = demo_aqi
    if cond["aqi"] is None:
        st.error("No air quality data for this spot. Use the override field to continue.")
        st.stop()

    aqi = float(cond["aqi"])
    band, bg, fg = core.aqi_band(aqi)
    summary = f"Air quality in {loc['name']}: AQI {int(aqi)}, {band}."
    st.markdown(
        f"""<div role="status" aria-live="polite" aria-label="{html.escape(summary)}"
        style="background:{bg};color:{fg};padding:16px;border-radius:12px;">
        <div style="font-size:16px">{html.escape(loc['name'])}</div>
        <div style="font-size:42px;font-weight:700;line-height:1.1">AQI {int(aqi)}</div>
        <div style="font-size:18px;font-weight:600">{band}</div></div>""",
        unsafe_allow_html=True,
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("PM2.5 (µg/m³)", cond["pm25"])
    m2.metric("Wind (km/h)", cond["wind_kmh"])
    m3.metric("Humidity (%)", cond["humidity"])

    sensitive = core.has_sensitive_member(kids, elders, conditions)
    if core.mask_needed(aqi, sensitive):
        st.warning(
            "Mask advice: at this AQI, a well-fitted N95 or FFP2 mask is recommended outdoors "
            "for sensitive household members. Cloth and surgical masks do little against PM2.5."
        )

    profile = {
        "children_under_12": kids,
        "adults_over_65": elders,
        "conditions": [c for c in conditions if c != "None"],
        "commute": commute,
        "commute_km_one_way": km,
        "home_type": home,
        "heating_cooking": heating,
        "budget": budget,
    }
    prompt = core.build_prompt(loc["name"], cond, profile)

    with st.spinner("Gemini is building your plan..."):
        try:
            plan = generate_plan(api_key, prompt)
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not build the plan: {e}")
            st.stop()

    st.subheader(plan.headline)
    st.info(f"Best time outside: {plan.best_outdoor_window}")

    render_actions("Low-emission daily routine", plan.daily_routine)
    render_actions("Indoor air quality hacks", plan.indoor_air_hacks)
    render_actions("Sustainable alternatives", plan.sustainable_alternatives)

    st.markdown("### Health and masks")
    st.warning(plan.mask_and_health_guidance)

    st.markdown("### This week's goal")
    st.success(plan.weekly_goal)

    weekly = core.commute_co2_weekly(commute, km)
    if weekly > 0:
        st.markdown("### Your commute impact (calculated estimate)")
        st.write(
            f"Commuting {km} km each way, 5 days a week, emits about **{weekly:.0f} kg CO₂** "
            f"per week. Swapping two of those days to metro, bus or carpool saves roughly "
            f"**{core.swap_saving(weekly):.0f} kg** and removes that exhaust from your own street."
        )

    st.caption(
        "Air data: Open-Meteo (CAMS). Plan: Gemini. Numbers marked as estimates are approximations. "
        "This is guidance, not medical advice."
    )
