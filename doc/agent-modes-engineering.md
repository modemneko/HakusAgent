# Agent Modes Engineering Contract

HakusAI exposes three agent run modes through one shared contract:

- `swift`: single AgentCore loop. Optional rule tester can be enabled with `HAKUS_SWIFT_RULE_TESTER=1`.
- `deep`: complexity-routed orchestrator path for higher-quality multi-agent work.
- `fleet`: Commander plus dynamically created experts, scheduled in parallel with file-scope locks.

The canonical mode list lives in `hakus/modes.py`. Backend routes, frontend request types, and benchmarks should use that contract instead of spelling mode strings independently.

## Runtime Configuration

- `HAKUS_MODE`: process default mode. Unknown values normalize to `swift`.
- Per-request `run_mode`: accepted values are `swift`, `deep`, or `fleet`. The FastAPI request model rejects unknown values.
- `HAKUS_FLEET_CONCURRENCY`: Fleet scheduler concurrency, default `10`.
- `HAKUS_HOME`: Fleet experience-store root. Defaults to `~/.hakus`.

Deep mode uses a lean sidecar profile by default so successful work can finish the turn instead of being dragged through an expensive pipeline:

- `HAKUS_DEEP_BATCH_SIZE`, default `1`
- `HAKUS_DEEP_MAX_FIX_ROUNDS`, default `1`
- `HAKUS_DEEP_PLANNER_TIMEOUT`, default `120`
- `HAKUS_DEEP_DEV_TIMEOUT`, default `240`
- `HAKUS_DEEP_TESTER_TIMEOUT`, default `120`
- `HAKUS_DEEP_MULTI_DIM`, default `0`
- `HAKUS_DEEP_FINAL_TEST`, default `0`
- `HAKUS_DEEP_AUTO_RECOVER`, default `0`

Set `HAKUS_DEEP_MULTI_DIM=1` and `HAKUS_DEEP_FINAL_TEST=1` only for deliberate high-assurance runs.

## Fleet Safety Rules

Fleet experts must declare `file_scope` in the Commander JSON. The scheduler derives lock keys from that scope:

- Same lock key: tasks run serially.
- Different lock keys: tasks may run concurrently.
- Write-capable tasks without a file scope get a coarse `__workspace_write__` lock.

Fleet success is strict: all scheduled experts must complete. A run with at least 80% completed experts is only `partial_success` and is reported as incomplete to the caller.

## Benchmark Entry Points

`benchmark_swe.py` supports:

- `swift`
- `deep`
- `fleet`
- `both` for `swift` plus `deep`
- `all` for all three modes

Useful environment variables:

- `SIDECAR_URL`
- `BENCH_OUTPUT_DIR`
- `BENCH_PROVIDER`
- `BENCH_RUN_ID`
- `BENCH_MODE`

Example:

```powershell
$env:BENCH_OUTPUT_DIR = "D:\bench\hakus"
$env:BENCH_PROVIDER = "opencode"
python benchmark_swe.py all bugfix-01 refactor-01
```

The benchmark writes one run directory per `BENCH_RUN_ID` and persists a `benchmark_results.json` with a `modes` object keyed by run mode.
