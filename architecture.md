# Architecture

## Objectives

Separate responsibilities cleanly.

- Home Assistant collects data and performs automation.

- Ardua AI performs reasoning.

- Device manufacturers remain authoritative sources for their own data.

## Components

```
                     Weather

                        │

      Tesla ------------┤

                        │

        Nest -----------┤

                        │

 Rocky Mountain Power --┤

                        │

     Emporia Vue -------┤

                        │

                Home Assistant

                        │

              MQTT / REST Events

                        │

                   Ardua AI

                        │

          Analysis / Reporting / Advice
```

## Design Principles

- Home Assistant owns integrations.

- Ardua AI owns analysis.

- Historical data should never be discarded unnecessarily.

- Every automation should have a measurable purpose.

- Prefer notifications before automation.

- Automate only after sufficient data has been collected.
