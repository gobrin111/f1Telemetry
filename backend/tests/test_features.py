"""Known-value tests for the versioned lap feature pipeline."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

from f1_telemetry.features import (
    FEATURE_NAMES,
    FeatureConfig,
    calculate_lap_features,
    summarize_telemetry,
)
from f1_telemetry.features.pipeline import build_session_features
from f1_telemetry.storage import Base
from f1_telemetry.storage.database import (
    create_database_engine,
    create_session_factory,
)
from f1_telemetry.storage.models import (
    Driver,
    Event,
    FeatureRun,
    ImportRecord,
    Lap,
    LapFeature,
    RaceSession,
    TelemetryFile,
    WeatherSample,
)


def _lap_inputs() -> pd.DataFrame:
    lap_numbers = list(range(1, 10))
    return pd.DataFrame(
        {
            "lap_id": lap_numbers,
            "driver_id": [1] * 9,
            "driver": ["AAA"] * 9,
            "lap_number": lap_numbers,
            "stint_number": [1] * 9,
            "lap_time_seconds": [91, 92, 93, 94, 100, 95, 96, 97, 98],
            "sector1_seconds": [30, 30, 31, 31, 35, 31, 31, 32, 32],
            "sector2_seconds": [30, 31, 30, 31, 33, 31, 32, 32, 32],
            "sector3_seconds": [31, 31, 32, 32, 32, 33, 33, 33, 34],
            "pit_out_seconds": [1.0, None, None, None, None, None, None, None, None],
            "pit_in_seconds": [None, None, None, None, None, None, None, 1.0, None],
            "lap_start_seconds": [100 * number for number in lap_numbers],
            "compound": ["SOFT"] * 9,
            "tyre_life": lap_numbers,
            "track_status": ["1", "1", "1", "1", "1", "12", "1", "1", "1"],
            "deleted": [False, False, False, False, False, False, True, False, False],
            "fastf1_generated": [False] * 9,
            "is_accurate": [True] * 9,
            "position": [1] * 9,
        }
    )


def _telemetry_summaries(lap_count: int = 9) -> pd.DataFrame:
    lap_numbers = list(range(1, lap_count + 1))
    return pd.DataFrame(
        {
            "driver_id": [1] * lap_count,
            "lap_number": lap_numbers,
            "telemetry_sample_count": [120] * lap_count,
            "speed_mean_kph": [200 + lap for lap in lap_numbers],
            "speed_max_kph": [300 + lap for lap in lap_numbers],
            "throttle_mean_pct": [60 + lap / 10 for lap in lap_numbers],
            "full_throttle_fraction": [0.5 + lap / 100 for lap in lap_numbers],
            "brake_fraction": [0.2 + lap / 100 for lap in lap_numbers],
            "gear_change_count": [40 + lap for lap in lap_numbers],
            "rpm_mean": [10000 + 10 * lap for lap in lap_numbers],
        }
    )


def _weather() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_seconds": [0.0, 1000.0],
            "air_temp": [25.0, 26.0],
            "humidity": [50.0, 51.0],
            "pressure": [1010.0, 1010.0],
            "rainfall": [False, False],
            "track_temp": [30.0, 31.0],
            "wind_direction": [90, 90],
            "wind_speed": [2.0, 2.0],
        }
    )


def test_raw_telemetry_summary_has_known_values() -> None:
    telemetry = pd.DataFrame(
        {
            "LapNumber": [1.0] * 4,
            "Speed": [100.0, 200.0, 300.0, 400.0],
            "Throttle": [100.0, 99.0, 50.0, 0.0],
            "Brake": [False, True, True, False],
            "nGear": [1, 2, 2, 3],
            "RPM": [8000.0, 9000.0, 10000.0, 11000.0],
        }
    )

    summary = summarize_telemetry(telemetry, driver_id=7).iloc[0]

    assert summary["driver_id"] == 7
    assert summary["telemetry_sample_count"] == 4
    assert summary["speed_mean_kph"] == 250.0
    assert summary["speed_max_kph"] == 400.0
    assert summary["throttle_mean_pct"] == 62.25
    assert summary["full_throttle_fraction"] == 0.5
    assert summary["brake_fraction"] == 0.5
    assert summary["gear_change_count"] == 2
    assert summary["rpm_mean"] == 9500.0


def test_missing_optional_telemetry_channel_produces_missing_summary() -> None:
    telemetry = pd.DataFrame(
        {
            "LapNumber": [1.0, 1.0],
            "Speed": [200.0, 210.0],
            "Throttle": [80.0, 100.0],
            "Brake": [pd.NA, pd.NA],
            "nGear": [pd.NA, pd.NA],
            "RPM": [pd.NA, pd.NA],
        }
    )

    summary = summarize_telemetry(telemetry, driver_id=7).iloc[0]

    assert pd.isna(summary["brake_fraction"])
    assert pd.isna(summary["gear_change_count"])
    assert pd.isna(summary["rpm_mean"])


@pytest.mark.parametrize(
    ("track_status", "reason"),
    [
        ("2", "yellow_flag_lap"),
        ("4", "safety_car_lap"),
        ("5", "red_flag_lap"),
        ("6", "virtual_safety_car_lap"),
        ("7", "virtual_safety_car_lap"),
    ],
)
def test_non_green_track_conditions_have_specific_reasons(
    track_status: str,
    reason: str,
) -> None:
    laps = _lap_inputs()
    laps.loc[laps["lap_number"] == 6, "track_status"] = track_status

    features = calculate_lap_features(
        laps, _weather(), _telemetry_summaries()
    ).set_index("lap_number")

    assert features.at[6, "exclusion_reason"] == reason


def test_eligibility_deltas_and_historical_normalization_are_reproducible() -> None:
    config = FeatureConfig(min_history_laps=3, history_window_laps=5)
    features = calculate_lap_features(
        _lap_inputs(), _weather(), _telemetry_summaries(), config
    ).set_index("lap_number")

    assert features.at[1, "exclusion_reason"] == "pit_out_lap"
    assert features.at[2, "exclusion_reason"] == "insufficient_comparison_history"
    assert features.at[4, "exclusion_reason"] == "insufficient_comparison_history"
    assert bool(features.at[5, "eligible"]) is True
    assert features.at[5, "comparison_sample_count"] == 3
    assert features.at[5, "feature_values"]["deltas"]["lap_time_seconds_delta"] == 7
    assert features.at[5, "feature_values"]["baselines"]["lap_time_seconds"] == 93
    assert features.at[5, "feature_values"]["scales"]["lap_time_seconds"] > 0
    assert len(features.at[5, "feature_vector"]) == len(FEATURE_NAMES)
    assert features.at[6, "exclusion_reason"] == "yellow_flag_lap"
    assert features.at[7, "exclusion_reason"] == "deleted_lap"
    assert features.at[8, "exclusion_reason"] == "pit_in_lap"
    assert bool(features.at[9, "eligible"]) is True
    assert features.at[9, "feature_values"]["raw"]["track_temp"] == 30.0
    assert features.at[5, "feature_values"]["deltas"]["sector1_seconds_delta"] == 4
    assert "|stint:1|" in features.at[5, "comparison_group"]

    extended_laps = pd.concat(
        [
            _lap_inputs(),
            pd.DataFrame(
                [
                    {
                        **_lap_inputs().iloc[-1].to_dict(),
                        "lap_id": 10,
                        "lap_number": 10,
                        "lap_start_seconds": 1000,
                        "lap_time_seconds": 500,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    extended = calculate_lap_features(
        extended_laps,
        _weather(),
        _telemetry_summaries(10),
        config,
    ).set_index("lap_number")
    assert extended.at[9, "feature_values"] == features.at[9, "feature_values"]
    assert extended.at[9, "feature_vector"] == features.at[9, "feature_vector"]


def test_recent_rain_transition_is_not_compared_with_stable_dry_laps() -> None:
    weather = _weather()
    transition = weather.iloc[[0]].copy()
    transition["time_seconds"] = 850.0
    transition["rainfall"] = True
    weather = pd.concat([weather, transition], ignore_index=True).sort_values(
        "time_seconds"
    )

    features = calculate_lap_features(
        _lap_inputs(), weather, _telemetry_summaries()
    ).set_index("lap_number")

    assert features.at[9, "exclusion_reason"] == "changing_track_conditions"
    assert bool(features.at[9, "is_wet"]) is True
    assert features.at[9, "comparison_group"].endswith("condition:wet")


def test_rapid_track_temperature_change_is_excluded() -> None:
    weather = _weather()
    temperature_jump = weather.iloc[[0]].copy()
    temperature_jump["time_seconds"] = 800.0
    temperature_jump["track_temp"] = 40.0
    weather = pd.concat([weather, temperature_jump], ignore_index=True).sort_values(
        "time_seconds"
    )

    features = calculate_lap_features(
        _lap_inputs(), weather, _telemetry_summaries()
    ).set_index("lap_number")

    assert features.at[9, "exclusion_reason"] == "changing_track_conditions"
    assert features.at[9, "feature_values"]["context"]["track_temp_change"] == 10


def test_new_stint_starts_a_fresh_comparison_history() -> None:
    laps = _lap_inputs()
    laps.loc[laps["lap_number"] == 9, "stint_number"] = 2
    laps.loc[laps["lap_number"] == 9, "tyre_life"] = 1

    features = calculate_lap_features(
        laps, _weather(), _telemetry_summaries()
    ).set_index("lap_number")

    assert features.at[9, "comparison_sample_count"] == 0
    assert features.at[9, "exclusion_reason"] == "insufficient_comparison_history"
    assert "|stint:2|" in features.at[9, "comparison_group"]


def _seed_feature_session(
    database_url: str,
    import_dir: Path,
    *,
    missing_rpm: bool = False,
) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    artifact_dir = import_dir / "2024-round-01-race"
    telemetry_dir = artifact_dir / "telemetry"
    telemetry_dir.mkdir(parents=True)

    telemetry_records: list[dict[str, float | int | bool]] = []
    for lap_number in range(1, 10):
        for sample in range(120):
            telemetry_records.append(
                {
                    "LapNumber": float(lap_number),
                    "Speed": 180.0 + lap_number + sample / 10,
                    "Throttle": 100.0 if sample % 2 == 0 else 50.0,
                    "Brake": sample % 10 == 0,
                    "nGear": 1 + sample % 8,
                    "RPM": 9000.0 + sample,
                }
            )
    telemetry_path = telemetry_dir / "AAA.parquet"
    telemetry_frame = pd.DataFrame(telemetry_records)
    if missing_rpm:
        telemetry_frame = telemetry_frame.drop(columns="RPM")
    telemetry_frame.to_parquet(telemetry_path, index=False, compression="zstd")
    (artifact_dir / "manifest.json").write_text("{}", encoding="utf-8")

    with factory.begin() as db:
        event = Event(year=2024, round_number=1, name="Example Grand Prix")
        race_session = RaceSession(
            event=event,
            session_key="2024-round-01-race",
            session_code="R",
            name="Race",
        )
        driver = Driver(
            driver_key="fastf1:alpha", abbreviation="AAA", fastf1_driver_id="alpha"
        )
        db.add_all([race_session, driver])
        db.flush()
        imported_at = datetime(2024, 3, 2, tzinfo=UTC)
        db.add(
            ImportRecord(
                job_id="import-2024-round-01-race",
                session=race_session,
                session_key=race_session.session_key,
                status="completed",
                source="FastF1",
                fastf1_version="3.8.3",
                manifest_schema_version=1,
                artifact_path=race_session.session_key,
                manifest_path=f"{race_session.session_key}/manifest.json",
                row_counts={"laps": 9, "telemetry": len(telemetry_records)},
                source_imported_at=imported_at,
                completed_at=imported_at,
            )
        )
        for row in _lap_inputs().to_dict(orient="records"):
            db.add(
                Lap(
                    session=race_session,
                    driver=driver,
                    lap_number=int(row["lap_number"]),
                    stint_number=int(row["stint_number"]),
                    lap_time_seconds=float(row["lap_time_seconds"]),
                    sector1_seconds=float(row["sector1_seconds"]),
                    sector2_seconds=float(row["sector2_seconds"]),
                    sector3_seconds=float(row["sector3_seconds"]),
                    pit_out_seconds=row["pit_out_seconds"],
                    pit_in_seconds=row["pit_in_seconds"],
                    lap_start_seconds=float(row["lap_start_seconds"]),
                    compound=str(row["compound"]),
                    tyre_life=float(row["tyre_life"]),
                    track_status=str(row["track_status"]),
                    deleted=bool(row["deleted"]),
                    fastf1_generated=bool(row["fastf1_generated"]),
                    is_accurate=bool(row["is_accurate"]),
                    position=1,
                )
            )
        for row in _weather().to_dict(orient="records"):
            db.add(WeatherSample(session=race_session, **row))
        db.add(
            TelemetryFile(
                session=race_session,
                driver=driver,
                relative_path="telemetry/AAA.parquet",
                file_format="parquet",
                compression="zstd",
                row_count=len(telemetry_records),
                byte_size=telemetry_path.stat().st_size,
                sha256="0" * 64,
            )
        )
    engine.dispose()


def test_pipeline_persists_one_idempotent_feature_row_per_lap(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'features.db'}"
    import_dir = tmp_path / "imports"
    _seed_feature_session(database_url, import_dir)
    config = FeatureConfig(min_history_laps=3, history_window_laps=5)

    first = build_session_features(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
        config=config,
    )
    repeated = build_session_features(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
        config=config,
    )
    rebuilt = build_session_features(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
        config=config,
        force=True,
    )

    assert first == repeated == rebuilt
    assert first.row_count == 9
    assert first.eligible_count == 2
    assert first.exclusion_counts["insufficient_comparison_history"] == 3

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as db:
            run = db.scalar(select(FeatureRun))
            assert run is not None
            assert run.status == "completed"
            assert run.feature_names == list(FEATURE_NAMES)
            assert db.scalar(select(func.count()).select_from(FeatureRun)) == 1
            assert db.scalar(select(func.count()).select_from(LapFeature)) == 9
            eligible = db.scalars(
                select(LapFeature).where(LapFeature.eligible.is_(True))
            ).all()
            assert len(eligible) == 2
            assert all(
                len(row.feature_vector or []) == len(FEATURE_NAMES) for row in eligible
            )
    finally:
        engine.dispose()


def test_pipeline_excludes_missing_telemetry_channel_without_failing(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'missing-channel.db'}"
    import_dir = tmp_path / "imports"
    _seed_feature_session(database_url, import_dir, missing_rpm=True)

    summary = build_session_features(
        database_url=database_url,
        import_dir=import_dir,
        session_key="2024-round-01-race",
    )

    assert summary.row_count == 9
    assert summary.eligible_count == 0
    assert summary.exclusion_counts["missing_telemetry"] == 5
