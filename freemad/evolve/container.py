"""Container isolation for the code the runtime executes on an agent's behalf.

Env scrubbing is the wrong layer for this project's real exposure. Auth is the agent
CLI's own subscription session, stored on disk under `~/.claude/` and `~/.codex/` — so
stripping variables buys nothing while `HOME` still points at the operator's home
directory. Judge stages run agent-authored code as the operator, with that directory
readable. Only a filesystem boundary closes it.

`evolve.md` section 6 lists container isolation as a non-goal ("document as production
posture only"). That decision was overridden deliberately; this module is the result.

What a containerised stage gets:

- the worktree bind-mounted at a fixed workdir, and **nothing else** — no `$HOME`, so
  `~/.claude/.credentials.json` is not merely unreadable, it is not present
- `--network=none` when `judge.network` is false, which is a real boundary rather than
  the proxy-variable hygiene it replaces: raw sockets, DNS and ssh are all covered
- the operator's uid/gid, so files it writes stay `git`-usable on the host
- `--cap-drop=ALL`, `--security-opt=no-new-privileges`, and optional cpu/memory caps

Availability is checked up front and a missing runtime is a hard failure. A security
control that silently falls back to the unprotected path is worse than not having one,
because the operator believes it is on.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from freemad.config import ContainerConfig


class ContainerUnavailable(RuntimeError):
    """The configured runtime is missing or its daemon is not reachable."""


def runtime_available(runtime: str) -> Optional[str]:
    """Return None when usable, else a human-readable reason it is not."""
    if shutil.which(runtime) is None:
        return f"'{runtime}' is not on PATH"
    probe = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [runtime, "info"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip().splitlines()
        return f"'{runtime} info' failed: {detail[0] if detail else 'unknown error'}"
    return None


def require_runtime(cfg: ContainerConfig) -> None:
    reason = runtime_available(cfg.runtime)
    if reason is not None:
        raise ContainerUnavailable(
            f"judge.container.enabled is true but {reason}. Install it, start it, or set "
            f"judge.container.enabled: false — this will not silently run on the host."
        )


def container_name(prefix: str = "freemad-evolve") -> str:
    """A unique name, so a timed-out stage can be killed rather than left running."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def build_argv(
    cfg: ContainerConfig,
    command: Sequence[str],
    worktree: Path,
    env: Dict[str, str],
    *,
    network: bool,
    name: str,
    uid_gid: Optional[str] = None,
) -> List[str]:
    """Wrap `command` so it runs inside a container over `worktree`.

    `env` is the already-scrubbed environment. It is passed explicitly because a
    container starts with none — the allowlist stays the source of truth for what a stage
    can see, and the mount list decides what it can reach.
    """
    argv: List[str] = [
        cfg.runtime,
        "run",
        "--rm",
        "--name",
        name,
        "--workdir",
        cfg.workdir,
        # The worktree, and nothing else. No HOME, so the on-disk session credentials
        # this project actually authenticates with are outside the container entirely.
        "--mount",
        f"type=bind,source={worktree.resolve()},target={cfg.workdir}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    ]

    if not network:
        # The real thing, not the proxy-variable approximation it replaces.
        argv += ["--network", "none"]

    if uid_gid:
        # Otherwise the stage writes root-owned files into the worktree and the next
        # `git add -A` on the host fails.
        argv += ["--user", uid_gid]

    if cfg.memory:
        argv += ["--memory", cfg.memory]
    if cfg.cpus:
        argv += ["--cpus", cfg.cpus]

    # Writable scratch, since the root filesystem stays read-only. This "/tmp" is a
    # path INSIDE the container -- a fresh tmpfs, not the host's temp directory.
    argv += ["--read-only", "--tmpfs", "/tmp:rw,exec,size=512m"]  # nosec B108

    for source, target in _mount_pairs(cfg.read_only_mounts):
        argv += ["--mount", f"type=bind,source={source},target={target},readonly"]

    for key, value in sorted(env.items()):
        # HOME would defeat the point: it must not name a host path.
        if key == "HOME":
            continue
        argv += ["-e", f"{key}={value}"]
    # Tools need *a* HOME; give them a writable one inside the container.
    argv += ["-e", "HOME=/tmp"]  # nosec B108 - container-internal tmpfs

    argv.append(cfg.image)
    argv.extend(command)
    return argv


def _mount_pairs(mounts: Sequence[str]) -> List[tuple[str, str]]:
    pairs: List[tuple[str, str]] = []
    for raw in mounts:
        source, _, target = raw.partition(":")
        pairs.append((str(Path(source).expanduser().resolve()), target or source))
    return pairs


def kill_container(runtime: str, name: str) -> None:
    """Stop a container whose client was killed by a timeout.

    `subprocess.run(timeout=...)` reaps the `docker run` client only; without this the
    stage keeps running and holds the bind-mounted worktree open.
    """
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [runtime, "kill", name],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


__all__ = [
    "ContainerUnavailable",
    "build_argv",
    "container_name",
    "kill_container",
    "require_runtime",
    "runtime_available",
]
