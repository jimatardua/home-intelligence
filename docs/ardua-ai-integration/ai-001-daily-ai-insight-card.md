# AI-001 — Daily AI Insight Card (MVP)

**Status:** Draft

---

# Purpose

Introduce the first integration between Home Assistant and Ardua AI by generating a concise, natural-language summary of the previous day's household activity.

The goal is not to replace Home Assistant's dashboards or analytics, but to provide a quick explanation of what happened across multiple home systems without requiring the user to inspect several graphs.

This feature establishes Ardua AI as the reasoning layer above Home Assistant while keeping Home Assistant responsible for data collection and visualization.

---

# Motivation

Home Assistant already provides excellent dashboards for individual systems, including:

- Electricity usage
- HVAC operation
- Indoor and outdoor temperatures
- Vehicle charging

However, these systems are presented independently.

Understanding relationships between them currently requires manual interpretation.

Examples include:

- Did high electricity usage come from air conditioning or vehicle charging?
- Was yesterday's energy usage unusual?
- Was the weather responsible for increased HVAC runtime?
- Did anything noteworthy happen that deserves attention?

This feature provides a concise explanation rather than additional telemetry.

---

# Goals

The system shall:

- Generate one AI summary per day.
- Correlate information across multiple Home Assistant integrations.
- Highlight noteworthy events.
- Explain likely causes when they are reasonably supported by the available data.
- Present the results in a form that can be read in less than one minute.

---

# Non-Goals

This MVP shall **not**:

- Perform long-term forecasting.
- Recommend automations.
- Control devices.
- Continuously monitor the home.
- Perform conversational queries.
- Replace Home Assistant dashboards.
- Perform complex statistical analysis.

Those capabilities belong to future enhancements.

---

# Data Sources

The initial implementation shall use the following integrations.

## Rocky Mountain Power

- Total daily energy usage
- Hourly usage
- Peak demand
- Peak demand time

## Nest

- Indoor temperature
- Outdoor temperature
- HVAC runtime
- Heating/cooling mode

## Tesla

For each configured vehicle:

- Charging sessions
- Charging duration
- Energy added
- Charging start and end times

The implementation shall support multiple vehicles without assuming a fixed number.

---

# Processing Pipeline

The summary generation shall occur once per day after Rocky Mountain Power data becomes available.

The pipeline consists of four stages.

## 1. Collect Metrics

Gather the previous day's data from Home Assistant.

The implementation should extract only the information needed for summarization rather than sending raw sensor history.

---

## 2. Build Structured Summary

Construct a compact structured object representing the day's activity.

Example:

```json
{
  "date": "2026-07-13",
  "energy": {
    "total_kwh": 46.8,
    "peak_time": "18:00"
  },
  "weather": {
    "high": 99,
    "low": 72
  },
  "hvac": {
    "runtime_hours": 6.2
  },
  "vehicles": [
    {
      "name": "Jim",
      "energy_added_kwh": 27.8,
      "charge_start": "17:45",
      "charge_end": "20:32"
    }
  ]
}
```

This object becomes the interface between Home Assistant and Ardua AI.

---

## 3. Generate AI Summary

Submit the structured summary to Ardua AI.

The AI should:

- Explain what happened.
- Highlight unusual events.
- Correlate information across systems.
- Avoid unsupported speculation.
- Avoid simply repeating raw numbers.
- Keep the response concise.

The AI should be treated as an explanation engine rather than a calculation engine.

---

## 4. Cache the Result

Store the generated summary so that it is available without requiring another AI request.

The summary should be regenerated only once per day.

Dashboard rendering should never invoke the AI directly.

---

# Presentation

Display the summary as a Markdown card at the top of the existing **Energy & Comfort** dashboard.

No new dashboards or charts are required for this feature.

---

# Example Output

> **Yesterday**
>
> - Total electricity usage was slightly above average.
> - Jim's Tesla charged for approximately three hours during the early evening.
> - Air conditioning ran longer than usual because the outdoor high reached 99°F.
> - Household demand peaked when vehicle charging and cooling overlapped.
> - Overnight electricity usage remained typical.

The implementation is not expected to reproduce this wording exactly.

---

# Architectural Principles

Home Assistant remains responsible for:

- Collecting telemetry
- Computing deterministic metrics
- Storing historical data
- Displaying dashboards

Ardua AI is responsible only for:

- Explaining relationships
- Identifying noteworthy events
- Producing concise natural-language summaries

Business logic and numerical calculations should remain outside the LLM wherever practical.

---

# Success Criteria

The feature is considered complete when:

- A summary is generated automatically once per day.
- The summary combines information from Rocky Mountain Power, Nest, and Tesla.
- The summary is cached after generation.
- The summary is displayed on the Energy & Comfort dashboard.
- Viewing the dashboard does not trigger additional AI requests.

---

# Future Enhancements

Possible future capabilities include:

- Weekly summaries
- Monthly summaries
- Comparative reports ("compared with last week")
- Forecasting
- Cost optimization
- Notifications
- Natural-language home queries
- Domain-specific advisors (Energy, Climate, Vehicles)

These enhancements are intentionally outside the scope of this MVP.