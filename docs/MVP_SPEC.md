# MVP Product Specification

## Status

**Approved on July 21, 2026.** This document defines the agreed MVP scope.

## Product definition

F1 Telemetry is a web application that imports completed Formula 1 race
sessions through FastF1, identifies unusual lap-level performance patterns,
and helps users investigate why a lap was flagged through driver comparisons
and explainable telemetry visualizations.

The application runs as local Docker services and is accessed through a normal
web browser at a localhost address. It is not a native desktop GUI. Keeping the
MVP local simplifies setup and deployment without changing its browser-based
user experience.

The application detects deviations in the available data. It does not claim to
diagnose mechanical failures, prove driver error, or determine wrongdoing.

## Intended user

The initial user is an F1 fan or amateur data analyst who wants to explore race
performance without writing Python or working directly with FastF1 datasets.

The user should understand common Formula 1 concepts such as laps, sectors,
stints, tire compounds, pit stops, and safety cars. They should not need machine
learning or software-development knowledge.

## Primary user goal

> Select a completed race session, find laps whose performance differs from a
> fair baseline, and inspect understandable evidence for why each lap was
> considered unusual.

## Definition of an anomaly

For the MVP, an anomaly is an **eligible completed lap whose combination of
performance features differs materially from comparable laps in the same
session**.

Comparable laps should account for context where the available data permits,
including:

- Driver and car performance.
- Tire compound, tire age, and stint.
- Track and weather conditions.
- Race phase and nearby laps.
- Valid green-flag running conditions.

An anomaly may be caused by traffic, a lockup, an off-track moment, tire
degradation, changing weather, damage, a data-quality issue, or another event.
The application reports the observed deviation and relevant context rather than
asserting an unverified cause.

## Eligibility and exclusion rules

The MVP scores normal racing laps when enough data is available for a fair
comparison. It should exclude or separately label:

- Pit-entry and pit-exit laps.
- Deleted or invalid laps.
- Formation laps and laps without a usable lap time.
- Safety-car, virtual-safety-car, and red-flag affected laps when identifiable.
- Laps with insufficient telemetry or feature data.
- Clearly wet or rapidly changing conditions when a suitable comparison group
  cannot be formed.

Every unscored lap must have a visible, machine-readable exclusion reason.

## Supported data and sessions

The MVP supports:

- Completed Formula 1 race sessions available through FastF1.
- One imported session analyzed at a time.
- Lap timing, sector timing, stint, tire, weather, and available car telemetry.
- One-driver inspection and multi-driver comparison within the selected race.

The MVP does not support qualifying, practice, sprint sessions, testing, or
live timing. These can be considered after the race-session workflow is stable.

## Primary user workflow

1. The user opens the application and browses available seasons and events.
2. The user selects a completed race session.
3. If the session has not been imported, the user starts an import and sees its
   progress and result.
4. The user starts or opens the latest anomaly analysis for the session.
5. The application displays scored laps and highlights unusual laps by
   severity.
6. The user filters the results by driver and selects an anomalous lap.
7. The application explains which features contributed to the score.
8. The user compares the lap with suitable baseline laps using timing and
   telemetry charts.

## MVP dashboard

The first dashboard should provide:

- Season, event, session, and driver selection.
- Import and analysis status.
- A lap-time chart with anomalous laps highlighted.
- A sortable anomaly table with score and severity.
- An explanation panel showing the largest contributing deviations.
- Comparison traces for speed, throttle, braking, and gear when available.
- Context for tire, stint, weather, and lap eligibility.
- Clear loading, empty, excluded-data, and error states.

## User stories and acceptance criteria

### Story 1: Select a race

As an F1 fan, I want to select a completed race so that I can analyze its laps.

Acceptance criteria:

- The user can browse supported seasons and events.
- The interface distinguishes imported and not-yet-imported sessions.
- Selecting a race opens its current import or analysis state.

### Story 2: Import session data

As an F1 fan, I want to import a selected session without running code so that
the data becomes available for analysis.

Acceptance criteria:

- The user can start an import from the application.
- The import runs outside the web request and reports queued, running,
  completed, or failed status.
- Repeating the request does not create duplicate session data.
- A failure provides a useful error without corrupting an existing import.

### Story 3: Find unusual laps

As an F1 fan, I want to see which eligible laps are unusual so that I know where
to begin investigating.

Acceptance criteria:

- Every eligible lap receives an anomaly score from a versioned analysis run.
- Results can be filtered by driver and sorted by score.
- Results display a human-readable severity level.
- Unscored laps display an exclusion reason.
- Re-running the same model version and configuration on the same features
  produces reproducible results.

### Story 4: Understand an anomaly

As an F1 fan, I want to know why a lap was flagged so that the score is not a
black box.

Acceptance criteria:

- A selected anomaly displays its most important contributing features.
- Each contribution includes the observed value and its comparison baseline.
- Explanations use cautious language and do not present inferred causes as
  facts.
- Tire, stint, weather, and race-condition context is visible when available.

### Story 5: Compare telemetry

As an F1 fan, I want to compare an unusual lap with relevant laps so that I can
inspect where its performance differed.

Acceptance criteria:

- The user can compare the selected lap with at least one suitable reference
  lap.
- Timing and available speed, throttle, brake, and gear traces share a common
  distance axis.
- The application identifies the driver and lap number for every trace.
- Missing telemetry is handled without breaking the rest of the analysis.

## MVP success criteria

The MVP is successful when all of the following are true:

- A supported completed race can be imported through the UI from a clean local
  environment.
- Imported data and completed analyses survive container restarts.
- At least 95% of laps deemed eligible by the documented rules receive a score.
- Every unscored lap has a recorded exclusion or data-quality reason.
- Each scored anomaly exposes its strongest contributing feature deviations.
- A user can complete the primary workflow without calling FastF1 directly or
  using developer tools.
- The statistical baseline and Isolation Forest are evaluated on the same
  versioned feature set using documented review cases and injected anomalies.
- Critical ingestion, feature, scoring, and API workflows have automated tests.

The 95% scoring target measures pipeline completeness among already eligible
laps; it is not a target for the percentage of all race laps that must be
eligible.

## Non-functional requirements

- The development environment starts through Docker Compose.
- The user interface is a browser-based web application served on localhost;
  no native desktop GUI is required.
- API schemas and errors are documented through FastAPI's OpenAPI output.
- Long-running imports and analyses do not block HTTP requests.
- Model, feature, and analysis versions are stored with results.
- Secrets and machine-specific settings are supplied through environment
  configuration and are not committed.
- Cached FastF1 data and database data persist locally between restarts.
- The UI remains usable when optional telemetry channels are unavailable.

## Deferred capabilities

- Live timing and streaming anomaly detection.
- Practice, qualifying, sprint, and testing sessions.
- Corner-level and raw sample-level time-series anomaly models.
- Automated mechanical-failure or incident diagnosis.
- Strategy recommendations and race-result prediction.
- User accounts, saved personal dashboards, sharing, and billing.
- Cloud deployment and horizontal scaling beyond what is needed for the MVP.

## Confirmed product decisions

1. The initial user is an F1 fan or amateur analyst.
2. The MVP supports completed race sessions only.
3. The MVP is a locally hosted, single-user web application accessed through a
   browser, not a native desktop GUI.
4. The MVP supports individual-driver analysis and driver comparisons.
5. Anomaly explanations use cautious language and do not claim an unverified
   underlying cause.

## Phase 1 completion gate

**Complete.** The product owner approved the five product decisions, including
the clarification that the locally hosted application must be browser based.
