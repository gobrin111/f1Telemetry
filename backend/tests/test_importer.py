"""FastF1 artifact-writer tests using a small deterministic session."""

from pathlib import Path
from typing import Any

import pandas as pd

from f1_telemetry.ingestion import importer


class FakeTelemetry(pd.DataFrame):
    @property
    def _constructor(self):
        return FakeTelemetry


class FakeLap:
    def __init__(
        self,
        driver: str,
        driver_number: str,
        lap_number: int,
    ) -> None:
        self.values = {
            "Driver": driver,
            "DriverNumber": driver_number,
            "LapNumber": lap_number,
        }

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get_telemetry(self, *, frequency: str) -> FakeTelemetry:
        assert frequency == "original"
        return FakeTelemetry(
            {
                "Time": pd.to_timedelta([0, 1], unit="s"),
                "SessionTime": pd.to_timedelta([60, 61], unit="s"),
                "Speed": [210.0, 215.0],
                "Throttle": [80.0, 100.0],
                "Brake": [False, False],
                "nGear": [7, 8],
                "Distance": [0.0, 100.0],
                "RelativeDistance": [0.0, 1.0],
            }
        )


class FakeLaps(pd.DataFrame):
    _metadata = ["fake_laps"]

    @property
    def _constructor(self):
        return FakeLaps

    def pick_drivers(self, driver_number: str) -> "FakeLaps":
        selected = self[self["DriverNumber"] == driver_number].copy()
        selected.fake_laps = [
            lap for lap in self.fake_laps if lap["DriverNumber"] == driver_number
        ]
        return selected

    def iterlaps(self):
        yield from enumerate(self.fake_laps)


class FakeSession:
    def __init__(self) -> None:
        laps = [FakeLap("AAA", "1", 1), FakeLap("BBB", "2", 1)]
        self.laps = FakeLaps(
            {
                "Driver": ["AAA", "BBB"],
                "DriverNumber": ["1", "2"],
                "LapTime": pd.to_timedelta([90, 91], unit="s"),
                "LapNumber": [1.0, 1.0],
                "Stint": [1.0, 1.0],
                "Compound": ["SOFT", "MEDIUM"],
                "TyreLife": [1.0, 1.0],
            }
        )
        self.laps.fake_laps = laps
        self.results = pd.DataFrame(
            {
                "DriverNumber": ["1", "2"],
                "Abbreviation": ["AAA", "BBB"],
                "Position": [1.0, 2.0],
            }
        )
        self.weather_data = pd.DataFrame(
            {
                "Time": pd.to_timedelta([0], unit="s"),
                "AirTemp": [25.0],
                "Rainfall": [False],
            }
        )
        self.event = pd.Series(
            {
                "RoundNumber": 1,
                "Country": "Example",
                "EventName": "Example Grand Prix",
                "EventDate": pd.Timestamp("2024-03-02"),
            }
        )
        self.drivers = ["1", "2"]
        self.name = "Race"
        self.loaded = False

    def load(self, **kwargs: bool) -> None:
        assert kwargs == {
            "laps": True,
            "telemetry": True,
            "weather": True,
            "messages": False,
        }
        self.loaded = True


def test_import_writes_repeatable_parquet_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = FakeSession()
    cache_dir = tmp_path / "cache"
    import_dir = tmp_path / "imports"
    progress_updates: list[tuple[int, str, str]] = []
    monkeypatch.setattr(importer.Cache, "enable_cache", lambda _path: None)
    monkeypatch.setattr(importer.fastf1, "get_session", lambda *_args: session)

    manifest = importer.import_race_session(
        year=2024,
        round_number=1,
        cache_dir=cache_dir,
        import_dir=import_dir,
        progress=lambda *update: progress_updates.append(update),
    )

    artifact_dir = import_dir / "2024-round-01-race"
    assert session.loaded is True
    assert manifest["files"]["laps"]["rows"] == 2
    assert manifest["telemetry_rows"] == 4
    assert (artifact_dir / "manifest.json").is_file()
    assert (artifact_dir / "laps.parquet").is_file()
    assert (artifact_dir / "telemetry" / "AAA.parquet").is_file()
    assert progress_updates[-1][:2] == (100, "complete")

    repeated = importer.import_race_session(
        year=2024,
        round_number=1,
        cache_dir=cache_dir,
        import_dir=import_dir,
    )
    assert repeated == manifest
