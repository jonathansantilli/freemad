# Dependency-update example (M4)

Goal given to the runtime: "update vendored lib to 2.x and keep behavior identical".

Layout:

- `src/app.py` — uses `vendored_lib` (pinned API v1 style)
- `vendor/vendored_lib/__init__.py` — the pinned dependency (v1.2.0); its docstring pins the version
- `tests/test_app.py` — editable unit tests (workers may update these for 2.x)
- `characterization.py` — **protected** judge stage: golden behavioral checks that must pass
  before and after the upgrade; demonstrates the editable-tests + protected-benchmark pattern
- `evolve.yaml` — judge config: tests (exit_code) + characterization (exit_code, gated) +
  bench (json_stdout, protected)

The characterization script is what makes this safe: workers may rewrite
`tests/` freely while migrating to the 2.x API, and they may modify
`vendor/vendored_lib/` itself — that *is* the upgrade — but every measured
component derives from the protected `characterization.py` / `bench_stub.py`
stages, so the measurement cannot be gamed by the measured.

Gate versus target, which this example exists to show. The **target**
(`compat_score >= 100`) is the goal: all five golden behaviors holding *and*
`vendored_lib` reporting 2.x. The **gate** (`compat_score >= 50`) is only an
admissibility floor. The seed scores exactly 50, and a gate set at the goal would fail
the seed against its own judge and stop the run before it started.

Read the score lattice before copying this design — `compat_score` multiplies the
fraction of passing goldens by 0.5 (1.x) or 1.0 (2.x):

| goldens passing | at 1.x | at 2.x |
|---|---|---|
| 5/5 | **50** | **100** |
| 4/5 | 40 | **80** |
| 3/5 | 30 | **60** |

`>= 50` therefore also admits 2.x at 3/5 and 4/5 — states with **broken** behaviors that
still beat the seed. What actually stops them here is the protected `characterization.py`
stage: it exits non-zero, short-circuits the pipeline, and the gate then fails closed on
the missing component. **The gate does not encode the invariant; stage ordering does.**
That is fragile — reorder or drop that stage and broken candidates get committed. A
single component that conflates "behavior" with "version" cannot express "never regress
behavior"; a second, separately gated component would.

Run it on a copy, never by `git init`-ing the checkout:

    cp -R examples/evolve_dependency_update /tmp/dep && cd /tmp/dep
    git init -q . && git add -A && git commit -qm init
    python -m freemad.cli evolve validate --config evolve.yaml
    python -m freemad.cli evolve start --config evolve.yaml "update vendored lib to 2.x and keep behavior identical"
