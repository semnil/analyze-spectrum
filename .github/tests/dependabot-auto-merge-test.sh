#!/usr/bin/env bash
# Checks that dependabot-auto-merge.yml reports `auto-merge` on every pull request: only pull_request starts it, the
# job has no condition of its own, and its steps alone are limited to pull requests dependabot[bot] opened.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/dependabot-auto-merge.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
count=0
failures=0

# expect <name> <actual> <expected>
expect() {
  count=$((count + 1))
  if [ "$2" = "$3" ]; then
    echo "ok   $1"
  else
    failures=$((failures + 1))
    echo "FAIL $1: expected $3, got $2"
  fi
}

expect "only pull_request starts the job" "$(yq -o=json -I=0 '.on | keys' "$workflow_path")" '["pull_request"]'
expect "the job has no condition of its own" "$(yq '.jobs."auto-merge" | has("if")' "$workflow_path")" false
expect "every step runs for dependabot[bot] only" \
  "$(yq '[.jobs."auto-merge".steps[].if] | unique | .[]' "$workflow_path")" \
  "github.event.pull_request.user.login == 'dependabot[bot]'"
expect "two steps" "$(yq '.jobs."auto-merge".steps | length' "$workflow_path")" 2

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
