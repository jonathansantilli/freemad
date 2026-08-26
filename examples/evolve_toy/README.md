# Evolve toy example

Proving ground for the `evolve` runtime. See [`docs/evolve-runtime.md`](../../docs/evolve-runtime.md)
and the handoff plan at the repository root (`evolve.md`).

Contents:

- `toy.py` — deliberately slow pure function
- `tests/test_toy.py` — correctness gate (judge stage `tests`)
- `bench.py` — benchmark printing `{"components": {"ops_per_sec": N}}` (judge stage `bench`)
- `evolve.yaml` — evolve configuration with protected paths
- `endurance.yaml` — long-run config for the manual endurance sign-off (`ENDURANCE.md`)
- `compare_operators.py` — harness running the toy under both variation operators

Run:

Evolve needs its own git repository to build worktrees and lineage in, so work on a
*copy* — running `git init` inside the checkout would make this an embedded repo that
clones as an empty directory.

    export PATH="$(poetry env info -p)/bin:$PATH"   # puts the `freemad` script on PATH
    cp -R examples/evolve_toy /tmp/evolve_toy && cd /tmp/evolve_toy
    git init -q . && git add -A && git commit -qm init
    freemad evolve validate --config evolve.yaml
    freemad evolve start --config evolve.yaml "make slow_sum as fast as possible"

`repo_path` and `store_path` in `evolve.yaml` resolve against the **config file's**
directory, like every other config-managed path, so these work from anywhere.
