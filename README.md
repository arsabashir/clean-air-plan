# Clear Air Plan

Built for PromptWars, Challenge 6: Urban Air Quality Assistant.

**Live app:** https://clean-air-plan-ag947fpq9vgjk5begxxjhu.streamlit.app/

## The problem

In winter, many cities sit under heavy smog. Families know the air is bad but not what to change: when to go out, how to protect the people at home who are most at risk, and which habits actually cut pollution.

## What it does

Enter your city and a few details about your household (children, older adults, health conditions, commute, home type, heating and cooking, budget). The app pulls live air quality and weather for your location, then Gemini builds a plan:

- A low-emission daily routine
- Indoor air quality hacks
- Sustainable alternatives suited to your area
- The best time of day to go outside
- Mask and health guidance that only appears when the AQI calls for it
- One measurable goal for the week

Every suggestion includes a one-line explanation of its direct impact. A calculated (non-AI) commute CO2 estimate shows the math behind switching trips.

## How Gemini is used

- Model: Gemini 2.5 Flash through the Google GenAI SDK (Gemini API).
- Input: live AQI, PM2.5, PM10, NO2, ozone, temperature, humidity and wind, plus the household profile.
- Output: structured JSON enforced by a Pydantic response schema, so the UI always renders cleanly.
- System prompt rules: use only the supplied readings, label every number as an estimate, recommend N95 masks only at high AQI, give no medical diagnoses, and keep the language simple enough for families.

## Data

Air quality and weather come from [Open-Meteo](https://open-meteo.com/) (no API key needed).

## Run it locally

```
python -m pip install -r requirements.txt
set GEMINI_API_KEY=your_key      # Windows CMD
python -m streamlit run app.py
```

On Mac or Linux, use `export GEMINI_API_KEY=your_key`. You can also paste the key into the sidebar box when the app opens.

The "Override AQI" field lets you simulate a smog day to test the plan.

## Tests

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

39 unit tests cover AQI banding and WCAG colour contrast, the deterministic mask rule, commute CO2 maths, input sanitising, Open-Meteo parsing (with mocked network calls), prompt building, and the Gemini response schema. Tests run automatically on every push through GitHub Actions.

## Structure

- `app.py`: Streamlit interface and Gemini call
- `core.py`: pure logic (data fetching, AQI rules, schema, prompt), no UI dependency
- `test_core.py`: unit tests

## Accessibility

AQI colours meet WCAG AA contrast, the AQI card is a live region with a text summary, status is never shown by colour alone, all inputs have labels and help text, and decorative emoji are hidden from screen readers.

## Note

This app gives general guidance, not medical advice. People with asthma, heart or lung conditions should follow their doctor's plan.
