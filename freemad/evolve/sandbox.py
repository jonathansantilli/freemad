"""Environment scrubbing for subprocesses that execute worker-authored code.

Hygiene, not isolation. Judge stages and worker-proposed commands run arbitrary code
that an agent wrote, with the host user's privileges. Scrubbing stops the *run's own*
credentials -- API keys, cloud tokens -- from being visible to that code, and points
proxy variables at a black hole when `judge.network` is false so well-behaved HTTP
clients fail fast.

It does not stop raw sockets, does not confine the filesystem, and is not a sandbox.
Container isolation remains the production posture and is deliberately not built
(`evolve.md` section 6). `docs/evolve-runtime.md` says so to the reader too.
"""

from __future__ import annotations

import os
from typing import Dict, Sequence

# Enough to start a process and run an interpreter, and nothing that carries a secret.
BASE_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TMPDIR",
    "TEMP",
    "TMP",
    # Windows cannot spawn a process without these.
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "NUMBER_OF_PROCESSORS",
)

PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "ALL_PROXY",
)

# Port 9 is discard; nothing listens, so a client fails immediately rather than hanging.
BLACKHOLE_PROXY = "http://127.0.0.1:9"


def scrubbed_env(
    passthrough: Sequence[str] = (), network: bool = False
) -> Dict[str, str]:
    """Build the environment for a subprocess running worker-authored code.

    `passthrough` names extra variables a judge legitimately needs (`judge.env_passthrough`);
    without that escape hatch a real judge would break and the scrub would just get
    turned off. Absent names are skipped rather than set empty, so a stage can still
    distinguish "unset" from "empty".
    """
    names = list(BASE_ALLOWLIST) + [str(name) for name in passthrough]
    if network:
        # Stripping proxy variables would leave a network-enabled stage with no route
        # out from behind a corporate proxy: "allowed" has to mean reachable.
        names += [*PROXY_VARS, "NO_PROXY", "no_proxy"]
    env = {name: os.environ[name] for name in names if name in os.environ}
    if not network:
        for var in PROXY_VARS:
            env[var] = BLACKHOLE_PROXY
        # An inherited NO_PROXY would punch a hole straight through the above.
        env["NO_PROXY"] = ""
        env["no_proxy"] = ""
    return env


__all__ = ["BASE_ALLOWLIST", "BLACKHOLE_PROXY", "PROXY_VARS", "scrubbed_env"]
