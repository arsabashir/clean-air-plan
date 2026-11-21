# Clear Air Plan

A GenAI assistant that helps families deal with severe winter smog and urban air pollution. Built for PromptWars, Challenge 6: Urban Air Quality Assistant.

**Live app:**https://clean-air-plan-ag947fpq9vgjk5begxxjhu.streamlit.app/

## The problem

In many cities, winter smog pushes AQI into unhealthy ranges for weeks. Families get generic advice ("stay indoors") that ignores their situation: a household with an asthmatic child and a long car commute needs a different plan than two adults who work from home.

## What it does

1. The user enters a city and a short household profile: children, elderly members, health conditions, commute, home type, heating or cooking fuel, and budget.
2. The app pulls live AQI, PM2.5, wind and humidity for that city, and finds the cleanest hour of the day.
3. Gemini turns that data into a personal plan:
   - Low-emission daily routine
   - Indoor air quality hacks
   - Sustainable alternatives for their location and budget
   - Mask and health guidance, shown only at the AQI levels where it matters
   - One measurable goal for the week
4. Every suggestion carries a one-line explanation of its direct impact, so people see why a choice matters.
5. A separate calculator (plain Python, not the LLM) estimates weekly commute CO2 and the saving from swapping two driving days.

## How the Gemini part works

- Model: Gemini 2.5 Flash through the Google GenAI SDK.
- Output is forced into a Pydantic JSON schema, so the UI always gets the same fields.
- The system prompt tells the model to:
  - use only the supplied readings and never invent numbers
  - label every figure as an estimate
  - recommend N95 or FFP2 masks only above AQI 150 (above 100 for sensitive members)
  - avoid medical diagnoses and defer to a doctor's action plan
  - write in plain language a family can follow

## Run it locally

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your key from aistudio.google.com"
streamlit run app.py
```

On Windows PowerShell, use `$env:GEMINI_API_KEY="your key"` instead of `export`.

## Deploy

Deployed on Streamlit Community Cloud. The API key is stored in the app's Secrets (`GEMINI_API_KEY`), never in the repo.

## Data sources

- Air quality and weather: [Open-Meteo](https://open-meteo.com) (Copernicus Atmosphere Monitoring Service model data)
- Geocoding: Open-Meteo Geocoding API

## Limits and disclaimer

This tool gives general guidance, not medical advice. Modelled AQI can differ from a nearby ground sensor. Anyone with asthma, heart or lung conditions should follow their doctor's plan. Impact figures are estimates.
