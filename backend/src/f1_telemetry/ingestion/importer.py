"""FastF1 race-session importer and Parquet artifact writer."""

import json
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd
from fastf1 import Cache
from fastf1.exceptions import DataNotLoadedError, NoLapDataError

ProgressCallback = Callable[[int, str, str], None]

LAP_COLUMNS = (
    "Driver",
    "DriverNumber",
    "LapTime",
    "LapNumber",
    "Stint",
    "PitOutTime",
    "PitInTime",
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
    "Sector1SessionTime",
    "Sector2SessionTime",
    "Sector3SessionTime",
    "SpeedI1",
    "SpeedI2",
    "SpeedFL",
    "SpeedST",
    "IsPersonalBest",
    "Compound",
    "TyreLife",
    "FreshTyre",
    "Team",
    "LapStartTime",
    "LapStartDate",
    "TrackStatus",
    "Position",
    "Deleted",
    "DeletedReason",
    "FastF1Generated",
    "IsAccurate",
)

RESULT_COLUMNS = (
    "DriverNumber",
    "BroadcastName",
    "Abbreviation",
    "DriverId",
    "TeamName",
    "TeamColor",
    "FirstName",
    "LastName",
    "FullName",
    "HeadshotUrl",
    "CountryCode",
    "Position",
    "ClassifiedPosition",
    "GridPosition",
    "Q1",
    "Q2",
    "Q3",
    "Time",
    "Status",
    "Points",
)

WEATHER_COLUMNS = (
    "Time",
    "AirTemp",
    "Humidity",
    "Pressure",
    "Rainfall",
    "TrackTemp",
    "WindDirection",
    "WindSpeed",
)

TELEMETRY_COLUMNS = (
    "Date",
    "Time",
    "SessionTime",
    "RPM",
    "Speed",
    "nGear",
    "Throttle",
    "Brake",
    "DRS",
    "Source",
    "Distance",
    "RelativeDistance",
    "DriverAhead",
    "DistanceToDriverAhead",
    "X",
    "Y",
    "Z",
    "Status",
)


def session_key(year: int, round_number: int) -> str:
    """Return the canonical artifact key for a race import."""
    return f"{year}-round-{round_number:02d}-race"


def manifest_path(import_dir: Path, year: int, round_number: int) -> Path:
    """Return the final manifest path for a canonical race import."""
    return import_dir / session_key(year, round_number) / "manifest.json"


def read_manifest(path: Path) -> dict[str, Any]:
    """Read an existing import manifest."""
    with path.open(encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def _select_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    existing_columns = [column for column in columns if column in frame.columns]
    return pd.DataFrame(frame).loc[:, existing_columns].copy()


def _write_parquet(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")
    return {"path": path.name, "rows": len(frame)}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp | datetime | date):
        return value.isoformat()
    if isinstance(value, pd.Timedelta | timedelta):
        return value.total_seconds()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _event_metadata(session: Any) -> dict[str, Any]:
    fields = (
        "RoundNumber",
        "Country",
        "Location",
        "OfficialEventName",
        "EventName",
        "EventDate",
        "EventFormat",
        "F1ApiSupport",
    )
    return {
        field: _json_value(session.event.get(field))
        for field in fields
        if field in session.event
    }


def _build_stints(laps: pd.DataFrame) -> pd.DataFrame:
    required = {"Driver", "Stint", "LapNumber"}
    if not required.issubset(laps.columns):
        return pd.DataFrame(
            columns=["Driver", "Stint", "StartLap", "EndLap", "LapCount"]
        )

    valid_laps = laps.dropna(subset=["Driver", "Stint", "LapNumber"]).copy()
    records: list[dict[str, Any]] = []
    for (driver, stint), group in valid_laps.groupby(["Driver", "Stint"]):
        record: dict[str, Any] = {
            "Driver": driver,
            "Stint": stint,
            "StartLap": group["LapNumber"].min(),
            "EndLap": group["LapNumber"].max(),
            "LapCount": len(group),
        }
        if "Compound" in group:
            compounds = group["Compound"].dropna()
            record["Compound"] = compounds.iloc[0] if not compounds.empty else None
        if "TyreLife" in group:
            tyre_life = group["TyreLife"].dropna()
            record["StartTyreLife"] = tyre_life.min() if not tyre_life.empty else None
            record["EndTyreLife"] = tyre_life.max() if not tyre_life.empty else None
        records.append(record)
    return pd.DataFrame.from_records(records)


def _write_telemetry(
    session: Any,
    output_dir: Path,
    progress: ProgressCallback,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    telemetry_files: list[dict[str, Any]] = []
    skipped_laps: list[dict[str, Any]] = []
    drivers = list(session.drivers)

    for driver_index, driver_number in enumerate(drivers, start=1):
        driver_frames: list[pd.DataFrame] = []
        driver_code = str(driver_number)
        driver_laps = session.laps.pick_drivers(driver_number)

        # FastF1 3.8.3 converts ``require`` to a set internally, while current
        # pandas rejects sets as indexers. Validate the required values here so
        # ingestion remains compatible without patching the dependency.
        for _, lap in driver_laps.iterlaps():
            if pd.isna(lap["Driver"]) or pd.isna(lap["LapNumber"]):
                continue
            driver_code = str(lap["Driver"])
            try:
                telemetry = lap.get_telemetry(frequency="original")
            except (DataNotLoadedError, NoLapDataError, KeyError, ValueError) as error:
                skipped_laps.append(
                    {
                        "driver": driver_code,
                        "lap_number": _json_value(lap["LapNumber"]),
                        "reason": type(error).__name__,
                    }
                )
                continue

            telemetry_frame = _select_columns(telemetry, TELEMETRY_COLUMNS)
            if telemetry_frame.empty:
                skipped_laps.append(
                    {
                        "driver": driver_code,
                        "lap_number": _json_value(lap["LapNumber"]),
                        "reason": "empty_telemetry",
                    }
                )
                continue
            telemetry_frame.insert(0, "LapNumber", lap["LapNumber"])
            telemetry_frame.insert(0, "DriverNumber", str(driver_number))
            telemetry_frame.insert(0, "Driver", driver_code)
            driver_frames.append(telemetry_frame)

        if driver_frames:
            driver_telemetry = pd.concat(driver_frames, ignore_index=True)
            relative_path = Path("telemetry") / f"{driver_code}.parquet"
            telemetry_file = _write_parquet(
                driver_telemetry,
                output_dir / relative_path,
            )
            telemetry_file["path"] = relative_path.as_posix()
            telemetry_file["driver"] = driver_code
            telemetry_files.append(telemetry_file)

        telemetry_progress = 55 + round(35 * driver_index / max(len(drivers), 1))
        progress(
            telemetry_progress,
            "telemetry",
            f"Extracted telemetry for {driver_index} of {len(drivers)} drivers",
        )

    return telemetry_files, skipped_laps


def import_race_session(
    *,
    year: int,
    round_number: int,
    cache_dir: Path,
    import_dir: Path,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Download a race and atomically persist its raw analysis artifacts."""
    report_progress = progress or (lambda _value, _stage, _message: None)
    key = session_key(year, round_number)
    final_dir = import_dir / key
    final_manifest = final_dir / "manifest.json"

    if final_manifest.is_file():
        report_progress(100, "complete", "Session artifacts already exist")
        return read_manifest(final_manifest)
    if final_dir.exists():
        raise RuntimeError(f"incomplete import directory already exists for {key}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    import_dir.mkdir(parents=True, exist_ok=True)
    Cache.enable_cache(str(cache_dir))

    report_progress(5, "resolving", "Resolving race session")
    session = fastf1.get_session(year, round_number, "R")
    report_progress(10, "downloading", "Loading FastF1 session data")
    session.load(laps=True, telemetry=True, weather=True, messages=False)
    report_progress(50, "extracting", "Writing session tables")

    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=import_dir))
    try:
        laps = _select_columns(session.laps, LAP_COLUMNS)
        results = _select_columns(session.results, RESULT_COLUMNS)
        weather = _select_columns(session.weather_data, WEATHER_COLUMNS)
        stints = _build_stints(laps)

        files = {
            "laps": _write_parquet(laps, temporary_dir / "laps.parquet"),
            "results": _write_parquet(results, temporary_dir / "results.parquet"),
            "weather": _write_parquet(weather, temporary_dir / "weather.parquet"),
            "stints": _write_parquet(stints, temporary_dir / "stints.parquet"),
        }
        telemetry_files, skipped_telemetry_laps = _write_telemetry(
            session,
            temporary_dir,
            report_progress,
        )

        report_progress(95, "manifest", "Finalizing import manifest")
        manifest = {
            "schema_version": 1,
            "session_key": key,
            "year": year,
            "round_number": round_number,
            "session": "R",
            "session_name": str(session.name),
            "imported_at": datetime.now(UTC).isoformat(),
            "fastf1_version": fastf1.__version__,
            "event": _event_metadata(session),
            "files": files,
            "telemetry_files": telemetry_files,
            "telemetry_rows": sum(item["rows"] for item in telemetry_files),
            "skipped_telemetry_laps": skipped_telemetry_laps,
        }
        with (temporary_dir / "manifest.json").open("w", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2, sort_keys=True)
            file.write("\n")

        temporary_dir.replace(final_dir)
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)

    report_progress(100, "complete", "Session import completed")
    return manifest
