"""Pure lap eligibility, context alignment, and feature calculations."""

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

FEATURE_SCHEMA_VERSION = "lap-features-v1"
PIPELINE_VERSION = "1.2.0"

RAW_FEATURE_NAMES = (
    "lap_time_seconds",
    "sector1_seconds",
    "sector2_seconds",
    "sector3_seconds",
    "speed_mean_kph",
    "speed_max_kph",
    "throttle_mean_pct",
    "full_throttle_fraction",
    "brake_fraction",
    "gear_change_count",
    "rpm_mean",
    "tyre_life",
    "air_temp",
    "track_temp",
)
FEATURE_NAMES = tuple(f"{name}_robust_z" for name in RAW_FEATURE_NAMES)
TIMING_FEATURES = (
    "lap_time_seconds",
    "sector1_seconds",
    "sector2_seconds",
    "sector3_seconds",
)

SCALE_FLOORS = {
    "lap_time_seconds": 0.05,
    "sector1_seconds": 0.02,
    "sector2_seconds": 0.02,
    "sector3_seconds": 0.02,
    "speed_mean_kph": 1.0,
    "speed_max_kph": 1.0,
    "throttle_mean_pct": 1.0,
    "full_throttle_fraction": 0.01,
    "brake_fraction": 0.01,
    "gear_change_count": 1.0,
    "rpm_mean": 50.0,
    "tyre_life": 1.0,
    "air_temp": 0.1,
    "track_temp": 0.1,
}

LAP_INPUT_COLUMNS = {
    "lap_id",
    "driver_id",
    "lap_number",
    "lap_time_seconds",
    "sector1_seconds",
    "sector2_seconds",
    "sector3_seconds",
    "pit_out_seconds",
    "pit_in_seconds",
    "compound",
    "tyre_life",
    "track_status",
    "deleted",
    "fastf1_generated",
    "is_accurate",
    "lap_start_seconds",
}

TELEMETRY_SUMMARY_COLUMNS = (
    "driver_id",
    "lap_number",
    "telemetry_sample_count",
    "speed_mean_kph",
    "speed_max_kph",
    "throttle_mean_pct",
    "full_throttle_fraction",
    "brake_fraction",
    "gear_change_count",
    "rpm_mean",
)


@dataclass(frozen=True)
class FeatureConfig:
    """Parameters that fully determine one feature-set calculation."""

    min_history_laps: int = 3
    history_window_laps: int = 12
    min_telemetry_samples: int = 100
    full_throttle_threshold: float = 98.0
    weather_stability_seconds: int = 300
    temperature_lookback_seconds: int = 300
    rapid_track_temp_change_celsius: float = 5.0

    def __post_init__(self) -> None:
        if self.min_history_laps < 1:
            raise ValueError("min_history_laps must be positive")
        if self.history_window_laps < self.min_history_laps:
            raise ValueError("history_window_laps must cover minimum history")
        if self.min_telemetry_samples < 1:
            raise ValueError("min_telemetry_samples must be positive")
        if not 0 <= self.full_throttle_threshold <= 100:
            raise ValueError("full_throttle_threshold must be between 0 and 100")
        if self.weather_stability_seconds < 0:
            raise ValueError("weather_stability_seconds cannot be negative")
        if self.temperature_lookback_seconds < 1:
            raise ValueError("temperature_lookback_seconds must be positive")
        if self.rapid_track_temp_change_celsius <= 0:
            raise ValueError("rapid track temperature threshold must be positive")

    def as_dict(self) -> dict[str, int | float]:
        """Return stable JSON-serializable configuration values."""
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _boolean(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return bool(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip()
    return text or None


def _float_or_nan(value: Any) -> float:
    number = _number(value)
    return number if number is not None else float("nan")


def summarize_telemetry(
    telemetry: pd.DataFrame,
    *,
    driver_id: int,
    full_throttle_threshold: float = 98.0,
) -> pd.DataFrame:
    """Summarize one driver's raw telemetry samples at lap grain."""
    required = {"LapNumber", "Speed", "Throttle", "Brake", "nGear", "RPM"}
    _require_columns(telemetry, required, "telemetry")
    records: list[dict[str, int | float]] = []
    valid = telemetry.dropna(subset=["LapNumber"]).copy()
    for lap_number, group in valid.groupby("LapNumber", sort=True):
        speed = pd.to_numeric(group["Speed"], errors="coerce")
        throttle = pd.to_numeric(group["Throttle"], errors="coerce")
        valid_throttle = throttle.dropna()
        brake = group["Brake"].astype("boolean").astype("Float64")
        gear = pd.to_numeric(group["nGear"], errors="coerce").dropna()
        rpm = pd.to_numeric(group["RPM"], errors="coerce")
        records.append(
            {
                "driver_id": driver_id,
                "lap_number": int(lap_number),
                "telemetry_sample_count": int(len(group)),
                "speed_mean_kph": _float_or_nan(speed.mean()),
                "speed_max_kph": _float_or_nan(speed.max()),
                "throttle_mean_pct": _float_or_nan(throttle.mean()),
                "full_throttle_fraction": _float_or_nan(
                    valid_throttle.ge(full_throttle_threshold).mean()
                ),
                "brake_fraction": _float_or_nan(brake.mean()),
                "gear_change_count": (
                    int(gear.diff().fillna(0).ne(0).sum())
                    if not gear.empty
                    else float("nan")
                ),
                "rpm_mean": _float_or_nan(rpm.mean()),
            }
        )
    return pd.DataFrame.from_records(records, columns=TELEMETRY_SUMMARY_COLUMNS)


def _align_weather(
    laps: pd.DataFrame,
    weather: pd.DataFrame,
    config: FeatureConfig,
) -> pd.DataFrame:
    context_columns = (
        "air_temp",
        "humidity",
        "pressure",
        "rainfall",
        "track_temp",
        "wind_direction",
        "wind_speed",
        "track_temp_change",
        "weather_changed_recently",
    )
    output = laps.copy()
    for column in context_columns:
        if column == "weather_changed_recently":
            output[column] = False
        elif column == "rainfall":
            output[column] = pd.Series(pd.NA, index=output.index, dtype="boolean")
        else:
            output[column] = np.nan
    if weather.empty:
        return output

    required = {"time_seconds", "air_temp", "rainfall", "track_temp"}
    _require_columns(weather, required, "weather")
    weather_ordered = weather.sort_values("time_seconds").copy()
    weather_ordered["time_seconds"] = pd.to_numeric(
        weather_ordered["time_seconds"], errors="coerce"
    ).astype(float)
    previous_rainfall = weather_ordered["rainfall"].shift()
    rain_changed = (
        weather_ordered["rainfall"].notna()
        & previous_rainfall.notna()
        & weather_ordered["rainfall"].ne(previous_rainfall)
    )
    weather_ordered["last_rain_change_seconds"] = weather_ordered["time_seconds"].where(
        rain_changed
    )
    weather_ordered["last_rain_change_seconds"] = weather_ordered[
        "last_rain_change_seconds"
    ].ffill()

    valid_laps = laps[laps["lap_start_seconds"].notna()].copy()
    if valid_laps.empty:
        return output
    valid_laps["_row_id"] = valid_laps.index
    valid_laps["lap_start_seconds"] = pd.to_numeric(
        valid_laps["lap_start_seconds"], errors="coerce"
    ).astype(float)
    valid_laps = valid_laps.sort_values("lap_start_seconds")

    current_columns = [
        column
        for column in (
            "time_seconds",
            "air_temp",
            "humidity",
            "pressure",
            "rainfall",
            "track_temp",
            "wind_direction",
            "wind_speed",
            "last_rain_change_seconds",
        )
        if column in weather_ordered.columns
    ]
    aligned = pd.merge_asof(
        valid_laps,
        weather_ordered[current_columns].sort_values("time_seconds"),
        left_on="lap_start_seconds",
        right_on="time_seconds",
        direction="backward",
        suffixes=("", "_weather"),
    )

    lookback = valid_laps[["_row_id", "lap_start_seconds"]].copy()
    lookback["weather_lookup_seconds"] = (
        lookback["lap_start_seconds"] - config.temperature_lookback_seconds
    )
    reference = pd.merge_asof(
        lookback.sort_values("weather_lookup_seconds"),
        weather_ordered[["time_seconds", "track_temp"]].sort_values("time_seconds"),
        left_on="weather_lookup_seconds",
        right_on="time_seconds",
        direction="backward",
    ).rename(columns={"track_temp": "reference_track_temp"})
    aligned = aligned.merge(
        reference[["_row_id", "reference_track_temp"]], on="_row_id", how="left"
    )
    aligned["track_temp_change"] = (
        aligned["track_temp"] - aligned["reference_track_temp"]
    )
    seconds_since_rain_change = (
        aligned["lap_start_seconds"] - aligned["last_rain_change_seconds"]
    )
    recent_rain_change = seconds_since_rain_change.between(
        0, config.weather_stability_seconds, inclusive="both"
    )
    rapid_temperature_change = (
        aligned["track_temp_change"].abs().ge(config.rapid_track_temp_change_celsius)
    )
    aligned["weather_changed_recently"] = (
        recent_rain_change | rapid_temperature_change
    ).fillna(False)

    by_row = aligned.set_index("_row_id")
    for column in context_columns:
        if column in by_row:
            output.loc[by_row.index, column] = by_row[column]
    return output


def _base_exclusion(row: pd.Series, config: FeatureConfig) -> str | None:
    if _number(row.get("pit_out_seconds")) is not None:
        return "pit_out_lap"
    if _number(row.get("pit_in_seconds")) is not None:
        return "pit_in_lap"
    if _boolean(row.get("deleted")) is True:
        return "deleted_lap"
    if _boolean(row.get("fastf1_generated")) is True:
        return "fastf1_generated_lap"
    if _number(row.get("lap_time_seconds")) is None:
        return "missing_lap_time"
    if any(_number(row.get(name)) is None for name in TIMING_FEATURES[1:]):
        return "missing_sector_time"
    if _text(row.get("compound")) is None:
        return "missing_tire_compound"
    if _number(row.get("tyre_life")) is None:
        return "missing_tire_age"
    if _number(row.get("stint_number")) is None:
        return "missing_stint"
    if _boolean(row.get("is_accurate")) is not True:
        return "inaccurate_lap"
    track_status = row.get("track_status")
    if track_status is None or pd.isna(track_status) or not str(track_status):
        return "missing_track_status"
    track_status = str(track_status)
    if track_status != "1":
        if "5" in track_status:
            return "red_flag_lap"
        if "4" in track_status:
            return "safety_car_lap"
        if "6" in track_status or "7" in track_status:
            return "virtual_safety_car_lap"
        if "2" in track_status:
            return "yellow_flag_lap"
        return "non_green_track_status"
    if _boolean(row.get("rainfall")) is None:
        return "missing_weather"
    if any(_number(row.get(name)) is None for name in ("air_temp", "track_temp")):
        return "missing_weather"
    if _boolean(row.get("weather_changed_recently")) is True:
        return "changing_track_conditions"
    if _number(row.get("telemetry_sample_count")) is None:
        return "missing_telemetry"
    if int(row["telemetry_sample_count"]) < config.min_telemetry_samples:
        return "insufficient_telemetry"
    telemetry_features = (
        "speed_mean_kph",
        "speed_max_kph",
        "throttle_mean_pct",
        "full_throttle_fraction",
        "brake_fraction",
        "gear_change_count",
        "rpm_mean",
    )
    if any(_number(row.get(name)) is None for name in telemetry_features):
        return "missing_telemetry"
    return None


def _robust_scale(values: np.ndarray, feature_name: str) -> float:
    median = float(np.median(values))
    mad_scale = float(np.median(np.abs(values - median)) * 1.4826)
    q1, q3 = np.quantile(values, [0.25, 0.75])
    iqr_scale = float((q3 - q1) / 1.349)
    std_scale = float(np.std(values))
    floor = SCALE_FLOORS[feature_name]
    for candidate in (mad_scale, iqr_scale, std_scale):
        if np.isfinite(candidate) and candidate >= floor:
            return candidate
    return floor


def _comparison_group(row: pd.Series) -> str:
    compound = (_text(row.get("compound")) or "UNKNOWN").upper()
    stint_value = _number(row.get("stint_number"))
    stint = str(int(stint_value)) if stint_value is not None else "UNKNOWN"
    condition = "wet" if row["is_wet"] else "dry"
    return (
        f"driver:{int(row['driver_id'])}"
        f"|compound:{compound}"
        f"|stint:{stint}"
        f"|condition:{condition}"
    )


def _feature_payload(
    row: pd.Series,
    history: list[dict[str, float]],
) -> tuple[dict[str, Any], list[float] | None]:
    raw = {name: _number(row.get(name)) for name in RAW_FEATURE_NAMES}
    deltas: dict[str, float | None] = {}
    normalized: dict[str, float | None] = {}
    baselines: dict[str, float | None] = {}
    scales: dict[str, float | None] = {}
    for feature_name in RAW_FEATURE_NAMES:
        current = raw[feature_name]
        historical = np.array([item[feature_name] for item in history], dtype="float64")
        if current is None or historical.size == 0:
            normalized[f"{feature_name}_robust_z"] = None
            baselines[feature_name] = None
            scales[feature_name] = None
            if feature_name in TIMING_FEATURES:
                deltas[f"{feature_name}_delta"] = None
            continue
        median = float(np.median(historical))
        scale = _robust_scale(historical, feature_name)
        baselines[feature_name] = median
        scales[feature_name] = scale
        normalized[f"{feature_name}_robust_z"] = (current - median) / scale
        if feature_name in TIMING_FEATURES:
            deltas[f"{feature_name}_delta"] = current - median

    context = {
        "driver_id": int(row["driver_id"]),
        "lap_number": int(row["lap_number"]),
        "stint_number": (
            int(row["stint_number"])
            if _number(row.get("stint_number")) is not None
            else None
        ),
        "compound": _text(row.get("compound")) or "",
        "rainfall": _boolean(row.get("rainfall")),
        "air_temp": _number(row.get("air_temp")),
        "track_temp": _number(row.get("track_temp")),
        "humidity": _number(row.get("humidity")),
        "pressure": _number(row.get("pressure")),
        "wind_direction": _number(row.get("wind_direction")),
        "wind_speed": _number(row.get("wind_speed")),
        "track_status": _text(row.get("track_status")),
        "track_temp_change": _number(row.get("track_temp_change")),
        "position": (
            int(row["position"]) if _number(row.get("position")) is not None else None
        ),
        "telemetry_sample_count": int(_number(row.get("telemetry_sample_count")) or 0),
    }
    payload = {
        "raw": raw,
        "baselines": baselines,
        "scales": scales,
        "deltas": deltas,
        "normalized": normalized,
        "context": context,
    }
    vector_values = [normalized[name] for name in FEATURE_NAMES]
    vector = (
        [float(value) for value in vector_values]
        if all(value is not None for value in vector_values)
        else None
    )
    return payload, vector


def calculate_lap_features(
    laps: pd.DataFrame,
    weather: pd.DataFrame,
    telemetry_summaries: pd.DataFrame,
    config: FeatureConfig | None = None,
) -> pd.DataFrame:
    """Return one eligibility decision and historical feature vector per lap."""
    active_config = config or FeatureConfig()
    _require_columns(laps, LAP_INPUT_COLUMNS, "laps")
    _require_columns(
        telemetry_summaries,
        set(TELEMETRY_SUMMARY_COLUMNS),
        "telemetry summaries",
    )
    enriched = _align_weather(laps, weather, active_config)
    enriched = enriched.merge(
        telemetry_summaries,
        on=["driver_id", "lap_number"],
        how="left",
        validate="one_to_one",
    )
    enriched["is_wet"] = (
        enriched["rainfall"].astype("boolean").fillna(False).astype(bool)
    )
    enriched["comparison_group"] = enriched.apply(_comparison_group, axis=1)
    enriched["_base_exclusion"] = enriched.apply(
        _base_exclusion, axis=1, config=active_config
    )
    enriched["eligible"] = False
    enriched["exclusion_reason"] = enriched["_base_exclusion"]
    enriched["comparison_sample_count"] = 0
    enriched["feature_values"] = None
    enriched["feature_vector"] = None

    history_by_group: dict[str, list[dict[str, float]]] = {}
    ordered = enriched.sort_values(
        ["lap_start_seconds", "driver_id", "lap_number"], na_position="last"
    )
    for index, row in ordered.iterrows():
        group = str(row["comparison_group"])
        complete_history = history_by_group.setdefault(group, [])
        history = complete_history[-active_config.history_window_laps :]
        enriched.at[index, "comparison_sample_count"] = len(history)
        payload, vector = _feature_payload(row, history)
        enriched.at[index, "feature_values"] = payload

        exclusion = row["_base_exclusion"]
        if exclusion is None and len(history) < active_config.min_history_laps:
            exclusion = "insufficient_comparison_history"
        if exclusion is None and vector is None:
            exclusion = "incomplete_feature_vector"
        enriched.at[index, "exclusion_reason"] = exclusion
        if exclusion is None:
            enriched.at[index, "eligible"] = True
            enriched.at[index, "feature_vector"] = vector

        if row["_base_exclusion"] is None:
            raw = payload["raw"]
            if all(raw[name] is not None for name in RAW_FEATURE_NAMES):
                complete_history.append(
                    {name: float(raw[name]) for name in RAW_FEATURE_NAMES}
                )

    return enriched.drop(columns=["_base_exclusion"])
