#!/bin/sh
# Map a workspace area or source path to the fastest cargo/nextest
# invocation for that area, and apply the portable cache topology so a
# new worktree actually gets isolated build-dir (+ sccache only when
# incremental is already off). Developer iteration aid only; no product
# behavior.
#
# Usage:
#   scripts/dev-test.sh <area|path> [filter...]
#   scripts/dev-test.sh --list
#   scripts/dev-test.sh --status
#
# Examples:
#   scripts/dev-test.sh config
#   scripts/dev-test.sh tui elapsed::
#   scripts/dev-test.sh crates/tui/src/elapsed.rs
#
# Environment:
#   HAKUS_DEV_NEXTEST  auto|1|0  (default auto: use cargo-nextest when
#                          it is on PATH; 0 forces cargo test)
#   Cache knobs are documented in scripts/dev-cache.sh.
set -eu

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# shellcheck source=scripts/dev-cache.sh
. "$repo_root/scripts/dev-cache.sh"

usage() {
  printf '%s\n' "usage: scripts/dev-test.sh <area|path> [filter...]" >&2
  printf '%s\n' "       scripts/dev-test.sh --list|--status|--self-check" >&2
  exit 2
}

list_areas() {
  cat <<'EOF'
area              command
----              -------
agent             cargo test -p hakus-agent --lib --locked
app-server        cargo test -p hakus-app-server --lib --locked
build-support     cargo test -p hakus-build-support --lib --locked
cli               cargo test -p hakus-cli --lib --locked
command-contract  cargo test -p hakus-command-contract --lib --locked
config            cargo test -p hakus-config --lib --locked
core              cargo test -p hakus-core --lib --locked
execpolicy        cargo test -p hakus-execpolicy --lib --locked
hooks             cargo test -p hakus-hooks --lib --locked
lane              cargo test -p hakus-lane --lib --locked
mcp               cargo test -p hakus-mcp --lib --locked
paths             cargo test -p hakus-paths --lib --locked
protocol          cargo test -p hakus-protocol --lib --locked
release           cargo test -p hakus-release --lib --locked
secrets           cargo test -p hakus-secrets --lib --locked
state             cargo test -p hakus-state --lib --locked
telemetry         cargo test -p hakus-telemetry --lib --locked
tools             cargo test -p hakus-tools --lib --locked
tui               cargo test -p hakus-tui --lib --locked
tui-integration   cargo test -p hakus-tui --test integration --locked
tui-cucumber      cargo test -p hakus-tui --test cucumber --locked
workflow          cargo test -p hakus-workflow --lib --locked
workflow-js       cargo test -p hakus-workflow-js --lib --locked

path prefix                         area / extra filter
-----------                         -------------------
crates/<crate>/                     <crate>
crates/tui/src/tui/                 tui  tui::
crates/tui/src/tools/               tui  tools::
crates/tui/src/core/                tui  core::
crates/tui/src/commands/            tui  commands::
crates/tui/src/<file>.rs            tui  <file>::
crates/tui/tests/integration/       tui-integration  <stem>
crates/tui/tests/cucumber/          tui-cucumber  <stem>
crates/tui/tests/                  tui-integration

When cargo-nextest is on PATH, the run stage is `cargo nextest run`
instead of `cargo test` (same binaries; process per test). Set
HAKUS_DEV_NEXTEST=0 to force libtest. New worktrees get an isolated
Cargo build-dir via scripts/dev-cache.sh; sccache wraps rustc only when
incremental is already off. Do not use cargo test --workspace for a
single-area edit. --lib and --tests are disjoint; a green --lib run does
not cover crates/tui/tests/.
EOF
}

[ $# -ge 1 ] || usage

if [ "$1" = "--list" ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  list_areas
  exit 0
fi

if [ "$1" = "--status" ] || [ "$1" = "--self-check" ]; then
  exec "$repo_root/scripts/dev-cache.sh" "$1"
fi

area=$1
shift

# Path form: map a source path onto an area, and invent a filter only when
# the caller did not already pass one.
if [ -e "$area" ] || printf '%s' "$area" | grep -q /; then
  rel=${area#./}
  extra=
  case $rel in
    crates/tui/tests/integration/*)
      area=tui-integration
      extra=$(basename "$rel" .rs)
      ;;
    crates/tui/tests/cucumber/*)
      area=tui-cucumber
      extra=$(basename "$rel" .rs)
      ;;
    crates/tui/tests/*)
      area=tui-integration
      extra=$(basename "$rel" .rs)
      ;;
    crates/tui/src/tui/*)
      area=tui
      extra=tui::
      ;;
    crates/tui/src/tools/*)
      area=tui
      extra=tools::
      ;;
    crates/tui/src/core/*)
      area=tui
      extra=core::
      ;;
    crates/tui/src/commands/*)
      area=tui
      extra=commands::
      ;;
    crates/tui/src/*)
      area=tui
      extra=$(basename "$rel" .rs)::
      ;;
    crates/tui/*|crates/tui)
      area=tui
      ;;
    crates/*)
      crate=$(printf '%s' "$rel" | awk -F/ '{print $2}')
      area=$crate
      ;;
    *)
      printf '%s\n' "dev-test: no area mapping for path: $area" >&2
      exit 2
      ;;
  esac
  case $extra in
    ''|main|main::|lib::|mod|mod::) extra= ;;
  esac
  if [ $# -eq 0 ] && [ -n "${extra:-}" ]; then
    set -- "$extra"
  fi
fi

pkg=
target=--lib
case $area in
  agent) pkg=hakus-agent ;;
  app-server) pkg=hakus-app-server ;;
  build-support) pkg=hakus-build-support ;;
  cli) pkg=hakus-cli ;;
  command-contract) pkg=hakus-command-contract ;;
  config) pkg=hakus-config ;;
  core) pkg=hakus-core ;;
  execpolicy) pkg=hakus-execpolicy ;;
  hooks) pkg=hakus-hooks ;;
  lane) pkg=hakus-lane ;;
  mcp) pkg=hakus-mcp ;;
  paths) pkg=hakus-paths ;;
  protocol) pkg=hakus-protocol ;;
  release) pkg=hakus-release ;;
  secrets) pkg=hakus-secrets ;;
  state) pkg=hakus-state ;;
  telemetry) pkg=hakus-telemetry ;;
  tools) pkg=hakus-tools ;;
  tui) pkg=hakus-tui ;;
  workflow) pkg=hakus-workflow ;;
  workflow-js) pkg=hakus-workflow-js ;;
  tui-integration)
    pkg=hakus-tui
    target=--test
    harness=integration
    ;;
  tui-cucumber)
    pkg=hakus-tui
    target=--test
    harness=cucumber
    ;;
  *)
    printf '%s\n' "dev-test: unknown area: $area (try --list)" >&2
    exit 2
    ;;
esac

hakus_dev_cache_apply
if [ -z "${RUST_MIN_STACK:-}" ]; then
  RUST_MIN_STACK=16777216
  export RUST_MIN_STACK
fi

use_nextest=0
_cw_nextest=${HAKUS_DEV_NEXTEST:-auto}
if hakus_dev_cache_falsey "$_cw_nextest"; then
  use_nextest=0
elif command -v cargo-nextest >/dev/null 2>&1; then
  use_nextest=1
elif hakus_dev_cache_truthy "$_cw_nextest"; then
  printf '%s\n' "dev-test: HAKUS_DEV_NEXTEST=${_cw_nextest} but cargo-nextest is not on PATH" >&2
  exit 2
fi

if [ "$target" = "--test" ]; then
  if [ "$use_nextest" -eq 1 ]; then
    set -- nextest run -p "$pkg" --test "$harness" --locked "$@"
    printf '+ cargo %s\n' "$*"
    hakus_dev_cache_exec_cargo "$@"
  fi
  set -- test -p "$pkg" --test "$harness" --locked "$@"
else
  if [ "$use_nextest" -eq 1 ]; then
    set -- nextest run -p "$pkg" --lib --locked "$@"
    printf '+ cargo %s\n' "$*"
    hakus_dev_cache_exec_cargo "$@"
  fi
  set -- test -p "$pkg" --lib --locked "$@"
fi

printf '+ cargo %s\n' "$*"
hakus_dev_cache_exec_cargo "$@"
