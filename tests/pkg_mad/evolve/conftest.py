from __future__ import annotations

from pathlib import Path

import pytest

from tests.pkg_mad.evolve.test_orchestrator import (
    BENCH_FILE,
    SLOW_IMPL,
    TESTS_FILE,
    _git,
)


@pytest.fixture()
def toy_repo(tmp_path: Path) -> Path:
    """A seed repo for the toy: a slow implementation, its tests, and its benchmark."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "impl.py").write_text(SLOW_IMPL)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_impl.py").write_text(TESTS_FILE)
    (repo / "bench.py").write_text(BENCH_FILE)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return repo
