from __future__ import annotations

from pathlib import Path

import pytest

from freemad.evolve.models import EvolveRunSnapshot, ScoreVector
from freemad.evolve.store import EvolveStore
from freemad.types import EvolveEventKind, EvolveRunStatus


def snapshot(run_id: str = "r1") -> EvolveRunSnapshot:
    return EvolveRunSnapshot(
        run_id=run_id,
        goal="goal",
        manifest_hash="hash",
        status=EvolveRunStatus.PENDING,
        seed_ref="HEAD",
        run_branch=f"evolve/{run_id}",
        repo_path="/tmp",
    )


@pytest.fixture()
def store(tmp_path: Path) -> EvolveStore:
    s = EvolveStore(tmp_path / "evolve.db")
    yield s
    s.close()


class TestRuns:
    def test_create_and_get_roundtrip(self, store: EvolveStore) -> None:
        stored = store.create_run(snapshot())
        assert stored.created_at_ms > 0 and stored.updated_at_ms > 0
        loaded = store.get_run("r1")
        assert loaded is not None
        assert loaded.run_id == "r1"
        assert loaded.status == EvolveRunStatus.PENDING

    def test_scores_survive_persistence(self, store: EvolveStore) -> None:
        from dataclasses import replace

        snap = snapshot()
        with_scores = replace(
            snap,
            best_score=ScoreVector(components={"ops": 12.5}),
            baseline_score=ScoreVector(components={"ops": 10.0}),
        )
        store.create_run(with_scores)
        loaded = store.get_run("r1")
        assert loaded is not None
        assert loaded.best_score is not None and loaded.best_score.get("ops") == 12.5
        assert loaded.baseline_score is not None

    def test_update_run(self, store: EvolveStore) -> None:
        from dataclasses import replace

        store.create_run(snapshot())
        store.update_run(
            replace(snapshot(), status=EvolveRunStatus.RUNNING, iteration=3)
        )
        loaded = store.get_run("r1")
        assert loaded is not None
        assert loaded.status == EvolveRunStatus.RUNNING
        assert loaded.iteration == 3

    def test_unknown_run_returns_none(self, store: EvolveStore) -> None:
        assert store.get_run("nope") is None

    def test_list_runs_ordered(self, store: EvolveStore) -> None:
        store.create_run(snapshot("b"))
        store.create_run(snapshot("a"))
        ids = [s.run_id for s in store.list_runs()]
        assert ids == ["b", "a"]


class TestEvents:
    def test_append_assigns_increasing_seq(self, store: EvolveStore) -> None:
        e1 = store.append_event("r1", EvolveEventKind.RUN_CREATED, 0, {"a": 1})
        e2 = store.append_event("r1", EvolveEventKind.RUN_STARTED, 1)
        assert e2.seq == e1.seq + 1

    def test_payload_json_roundtrip_sorted_keys(self, store: EvolveStore) -> None:
        payload = {"z": 1, "a": {"c": 2, "b": [1, 2]}}
        store.append_event("r1", EvolveEventKind.CANDIDATE_JUDGED, 1, payload)
        events = store.list_events("r1")
        assert events[0].payload == payload

    def test_list_events_filters_after_seq_and_orders(self, store: EvolveStore) -> None:
        for i in range(5):
            store.append_event("r1", EvolveEventKind.RUN_CREATED, i, {"i": i})
        store.append_event("other", EvolveEventKind.RUN_CREATED, 0)
        tail = store.list_events("r1", after_seq=2)
        assert [e.seq for e in tail] == [3, 4, 5]
        assert all(e.run_id == "r1" for e in tail)

    def test_events_are_durable_via_wal_full(self, tmp_path: Path) -> None:
        db_path = tmp_path / "durable.db"
        s = EvolveStore(db_path)
        s.create_run(snapshot("dur"))
        s.append_event("dur", EvolveEventKind.RUN_STARTED, 1)
        mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = s._conn.execute("PRAGMA synchronous").fetchone()[0]
        s.close()
        assert str(mode).lower() == "wal"
        assert int(sync) == 2  # FULL


class TestReadOnly:
    def test_reader_sees_writer_data(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        writer = EvolveStore(db_path)
        writer.create_run(snapshot("shared"))
        reader = EvolveStore(db_path, read_only=True)
        assert reader.get_run("shared") is not None
        writer.close()
        reader.close()

    def test_reader_rejects_writes(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ro.db"
        writer = EvolveStore(db_path)
        writer.close()
        reader = EvolveStore(db_path, read_only=True)
        with pytest.raises(Exception):
            reader.append_event("x", EvolveEventKind.RUN_STARTED, 0)
        reader.close()
