from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from freemad.config import Config, ConfigError


_ARTIFACT_DIRS = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"}
)
_ARTIFACT_SUFFIXES = frozenset({".pyc", ".pyo"})


_ARTIFACT_EXCLUDE_PATHSPECS = tuple(
    f":(exclude){pattern}"
    for pattern in (
        *(f"**/{d}/**" for d in sorted(_ARTIFACT_DIRS)),
        *(f"**/*{s}" for s in sorted(_ARTIFACT_SUFFIXES)),
    )
)


def _IS_BUILD_ARTIFACT(rel: Path) -> bool:
    return (
        bool(_ARTIFACT_DIRS.intersection(rel.parts)) or rel.suffix in _ARTIFACT_SUFFIXES
    )


class LineageError(RuntimeError):
    pass


class NoChangesToCommit(LineageError):
    """Nothing was left to commit once protected paths were restored."""


class ProtectedPathTampering(LineageError):
    """The worktree was arranged so that restoring a protected path would act outside it.

    Worker misbehaviour, so it fails the iteration rather than the run.
    """


class Lineage:
    """All git operations for an evolve run: worktrees, commits, tags, branches."""

    def __init__(self, cfg: Config, run_id: str):
        self._cfg = cfg
        self._run_id = run_id
        self._repo = Path(cfg.evolve.repo_path).resolve()
        self._worktree_root = self._repo / ".freemad" / "evolve" / "worktrees" / run_id

    @property
    def repo_root(self) -> Path:
        return self._repo

    @property
    def run_branch(self) -> str:
        return f"{self._cfg.evolve.run_branch_prefix}{self._run_id}"

    def _git(self, *args: str, cwd: Optional[Path] = None) -> str:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=str(cwd or self._repo),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise LineageError(
                f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout

    # ---------- inspection ----------

    def resolve_ref(self, ref: str) -> str:
        out = self._git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
        return out

    def repo_is_clean(self) -> bool:
        out = self._git("status", "--porcelain", "-uno")
        return out.strip() == ""

    def require_clean_repo(self) -> None:
        if not self.repo_is_clean():
            raise ConfigError(
                "evolve requires a clean repository (tracked files); commit or stash first"
            )

    def worktree_path(self, iteration: int) -> Path:
        return self._worktree_root / f"it{iteration}"

    def diff_stat(self, worktree: Path) -> str:
        """Stat of everything `commit_candidate` would stage, additions included.

        `--intent-to-add` registers new paths in the index without their content so
        `git diff` reports them; the worktree is either committed or discarded right
        after, so mutating its index here is inert.
        """
        self._git("add", "-A", "--intent-to-add", cwd=worktree)
        return self._git("diff", "--stat", cwd=worktree).strip()

    # ---------- setup / teardown ----------

    def init_run_branch(self, seed_sha: str) -> None:
        self._git("branch", self.run_branch, seed_sha)

    def create_worktree(self, iteration: int) -> Path:
        path = self.worktree_path(iteration)
        path.parent.mkdir(parents=True, exist_ok=True)
        tip = self.resolve_ref(self.run_branch)
        self._git("worktree", "add", "--detach", str(path), tip)
        return path

    def _remove_worktree_dir(self, path: Path) -> None:
        """Remove a worktree robustly: metadata may be missing after a crash."""
        try:
            self._git("worktree", "remove", "--force", str(path))
        except LineageError:
            import shutil

            shutil.rmtree(path, ignore_errors=True)
            self._git("worktree", "prune")

    def remove_worktree(self, iteration: int) -> None:
        """Best-effort, and deliberately non-throwing.

        This runs in a `finally`, where a raise would *replace* the pending return --
        turning a committed, branch-advanced iteration into a crash. A worktree left
        behind is recoverable (`cleanup_orphan_worktrees` on resume); a lost return is not.
        """
        path = self.worktree_path(iteration)
        if not path.exists():
            return
        try:
            self._remove_worktree_dir(path)
        except (LineageError, OSError):
            return
        try:
            self._worktree_root.rmdir()
        except OSError:
            pass

    def cleanup_orphan_worktrees(self) -> List[str]:
        removed: List[str] = []
        if not self._worktree_root.exists():
            self._git("worktree", "prune")
            return removed
        for entry in sorted(self._worktree_root.iterdir()):
            if entry.is_dir():
                self._remove_worktree_dir(entry)
                removed.append(str(entry))
        self._git("worktree", "prune")
        try:
            self._worktree_root.rmdir()
        except OSError:
            pass
        return removed

    # ---------- candidate admission ----------

    def _lineage_exclude_pathspecs(self) -> list[str]:
        """Paths that must never enter the lineage, whoever produced them.

        Beyond interpreter caches: the debate runtime's own transcript directory. A live
        run on a real repository committed two `transcripts/*.json` debate artefacts
        alongside a genuine optimisation -- the worker had run the freemad CLI inside the
        worktree to check its work, and `git add -A` swept the output into the accepted
        candidate. The run's *own* state under `.freemad/` is excluded for the same reason.
        """
        specs = list(_ARTIFACT_EXCLUDE_PATHSPECS)
        transcript_dir = self._cfg.output.transcript_dir.strip("/") or "transcripts"
        specs.append(f":(exclude){transcript_dir}/**")
        specs.append(":(exclude).freemad/**")
        return specs

    def commit_candidate(
        self, worktree: Path, iteration: int, score_dict_json: str
    ) -> str:
        message = (
            f"evolve({self._run_id}): iteration {iteration} accepted\n\n"
            f"Evolve-Score: {score_dict_json}\n"
        )
        # Exclude interpreter and tool caches explicitly: the judge runs inside the
        # worktree, and a target repo without a .gitignore would otherwise have its
        # bytecode committed as part of every accepted candidate.
        self._git(
            "add", "-A", "--", ".", *self._lineage_exclude_pathspecs(), cwd=worktree
        )
        staged = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(worktree),
            capture_output=True,
            timeout=120,
            check=False,
        )
        if staged.returncode == 0:
            # `git commit` exits 1 with an empty message on stderr, which surfaced as a
            # blank LineageError and took the whole run down. A candidate whose only
            # edits were to protected paths lands here after restoration.
            raise NoChangesToCommit(
                "nothing left to commit after protected paths were restored"
            )
        self._git(
            "-c",
            "user.name=freemad-evolve",
            "-c",
            "user.email=evolve@freemad.local",
            "commit",
            "-m",
            message,
            cwd=worktree,
        )
        return self._git("rev-parse", "HEAD", cwd=worktree).strip()

    def advance_run_branch(self, new_sha: str, expected_old_sha: str) -> None:
        ref = f"refs/heads/{self.run_branch}"
        self._git("update-ref", ref, new_sha, expected_old_sha)

    def tag_version(self, iteration: int, sha: str) -> str:
        """Tag an accepted commit. Idempotent by design.

        A crash between `commit_candidate` and `advance_run_branch` leaves the tag
        pointing at a commit that never reached the run branch. Resume redoes that
        iteration from scratch and must be able to re-tag over the orphan, or the run
        is permanently wedged on `tag already exists`.
        """
        tag = self.tag_name(iteration)
        self._git(
            "-c",
            "user.name=freemad-evolve",
            "-c",
            "user.email=evolve@freemad.local",
            "tag",
            "-f",
            tag,
            sha,
        )
        return tag

    def tag_name(self, iteration: int) -> str:
        return f"{self._cfg.evolve.run_branch_prefix}{self._run_id}/v{iteration}"

    # ---------- judge protection ----------

    def restore_protected(self, worktree: Path, seed_ref: str) -> dict[str, str]:
        """Restore judge-owned paths from seed_ref inside the worktree; return sha256 map.

        The path is *removed* before checkout. `git checkout <ref> -- <path>` only
        overwrites paths present in <ref>, so a worker that adds a file inside a
        protected directory -- a `conftest.py` that empties the suite, say -- would
        otherwise survive restoration and silently steer the measurement. Protected
        means judge-owned: after this runs, the worktree copy equals the seed copy.
        """
        import hashlib
        import shutil

        evolve = self._cfg.evolve
        # Validate the whole set first: restoration deletes, and a raise partway through
        # would leave some paths restored and the rest as the worker left them.
        for rel in evolve.judge.protected_paths:
            self._reject_escaping_path(worktree, rel)

        hashes: dict[str, str] = {}
        for rel in evolve.judge.protected_paths:
            target = worktree / rel
            if self._path_in_ref(seed_ref, rel):
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
                self._git("checkout", seed_ref, "--", rel, cwd=worktree)
                if target.is_dir():
                    digest = self._hash_tree(target)
                else:
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                if target.exists() or target.is_symlink():
                    # The worker created a judge-owned path the seed does not have.
                    # That is precisely what section 4.7 defends against, so it fails
                    # the candidate -- never the run.
                    raise ProtectedPathTampering(
                        f"protected path '{rel}' exists in worktree but not at {seed_ref}"
                    )
                digest = "absent"
            hashes[rel] = digest
        return hashes

    def _reject_escaping_path(self, worktree: Path, rel: str) -> None:
        """Refuse to touch a protected path that does not stay inside the worktree.

        `Path.is_symlink()` lstats only the FINAL component, and `shutil.rmtree` refuses
        only when the path *itself* is a link. A worker that turns a parent component
        into a symlink therefore makes `is_dir()` follow it and hands `rmtree` a
        directory outside the worktree -- deleting operator data with no log line. Walk
        the components and refuse before anything destructive happens.
        """
        root = worktree.resolve()
        current = root
        for part in Path(rel).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ProtectedPathTampering(
                    f"protected path '{rel}' traverses a symlink at "
                    f"'{current.relative_to(root)}'"
                )
        target = worktree / rel
        anchor = target.parent.resolve()
        if anchor != root and root not in anchor.parents:
            raise ProtectedPathTampering(
                f"protected path '{rel}' resolves outside the worktree: {anchor}"
            )

    def _path_in_ref(self, ref: str, rel: str) -> bool:
        """Whether `rel` (file or directory) exists at `ref`.

        Asked of the ref rather than the main working tree: `seed_ref` may be an older
        commit whose contents differ from what is currently checked out.
        """
        out = self._git("ls-tree", "-r", "--name-only", ref, "--", rel)
        return out.strip() != ""

    def _hash_tree(self, root: Path) -> str:
        """Length-delimited so ("ab", b"c") and ("a", b"bc") cannot collide.

        Interpreter and tool caches are excluded: the judge creates them *inside* the
        protected tree while running, so hashing them would make every verification
        fail. Restoration deletes the whole path first, so nothing stale survives into
        an iteration; the residual gap is a worker writing bytecode that Python then
        accepts over its own source, which its source-hash validation already resists.
        """
        import hashlib

        hasher = hashlib.sha256()
        for p in sorted(root.rglob("*")):
            if p.is_symlink() or not p.is_file():
                continue
            if _IS_BUILD_ARTIFACT(p.relative_to(root)):
                continue
            name = str(p.relative_to(root)).encode()
            data = p.read_bytes()
            hasher.update(f"{len(name)}:".encode())
            hasher.update(name)
            hasher.update(f"{len(data)}:".encode())
            hasher.update(data)
        return hasher.hexdigest()

    def verify_protected(self, worktree: Path, seed_ref: str) -> None:
        """Re-check protected paths after judging, against the seed itself.

        Restoration is a point in time. `subprocess.run(timeout=...)` reaps only the
        direct child, so a worker command that daemonises a grandchild can rewrite a
        protected file between restoration and the judge reading it. Stamping a hash and
        never comparing it is provenance, not tamper detection.

        This asks git rather than hashing the directory, for two reasons: it compares
        against `seed_ref` instead of a snapshot of the same possibly-tampered tree, and
        `--exclude-standard` means the repo's own `.gitignore` decides what counts as a
        judge side effect. A denylist of cache directories would be Python-shaped, and
        would reject every candidate for a judge that writes coverage data, a generated
        golden, or a compiled extension into a protected directory.
        """
        for rel in self._cfg.evolve.judge.protected_paths:
            self._reject_escaping_path(worktree, rel)
            # Build artifacts are filtered on BOTH halves. A repo with no .gitignore
            # gets its bytecode committed into the lineage by `git add -A`, after which
            # every later worktree carries it as a *tracked* difference from the seed --
            # and tamper detection would fire on the judge's own leavings forever.
            changed = [
                line
                for line in self._git(
                    "diff", "--name-only", seed_ref, "--", rel, cwd=worktree
                ).splitlines()
                if line.strip() and not _IS_BUILD_ARTIFACT(Path(line.strip()))
            ]
            if changed:
                raise ProtectedPathTampering(
                    f"protected path '{rel}' changed between restoration and judging: "
                    f"{changed[0]}"
                )
            # Untracked additions: the repo's own .gitignore decides first, then the
            # build-artifact filter covers repos that ship no .gitignore. Judges write
            # caches into the tree they are pointed at; a `conftest.py` is a different
            # thing entirely and still lands here.
            added = [
                line
                for line in self._git(
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "--",
                    rel,
                    cwd=worktree,
                ).splitlines()
                if line.strip() and not _IS_BUILD_ARTIFACT(Path(line.strip()))
            ]
            if added:
                raise ProtectedPathTampering(
                    f"protected path '{rel}' gained an untracked file during judging: "
                    f"{added[0]}"
                )

    # ---------- baseline helpers ----------

    def baseline_worktree(self) -> Path:
        """Iteration 0 judges the unmodified seed in its own worktree."""
        return self.create_worktree(0)

    def delete_run_branch(self) -> None:
        self._git("branch", "-D", self.run_branch)
