#!/usr/bin/env bash
# Checks the workflow_dispatch entry of dependabot-auto-merge.yml: both triggers, the step that refuses a dispatch on a
# dependabot/ branch (run here, it has to fail with ::error::), and the Dependabot steps keeping their condition.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/dependabot-auto-merge.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
refuse="Refuse a dispatch on a Dependabot branch"
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

expect "pull_request starts the job" "$(yq '.on | has("pull_request")' "$workflow_path")" true
expect "workflow_dispatch starts the job" "$(yq '.on | has("workflow_dispatch")' "$workflow_path")" true
expect "the job has no condition of its own" "$(yq '.jobs."auto-merge" | has("if")' "$workflow_path")" false
expect "the refusal is the first step" "$(yq '.jobs."auto-merge".steps[0].name' "$workflow_path")" "$refuse"
expect "the refusal runs for a dispatch on a dependabot/ branch" \
  "$(yq ".jobs.\"auto-merge\".steps[] | select(.name == \"${refuse}\") | .if" "$workflow_path")" \
  "github.event_name == 'workflow_dispatch' && startsWith(github.ref_name, 'dependabot/')"
expect "the other steps run for dependabot[bot] only" \
  "$(yq "[.jobs.\"auto-merge\".steps[] | select(.name != \"${refuse}\") | .if] | unique | .[]" "$workflow_path")" \
  "github.event.pull_request.user.login == 'dependabot[bot]'"
expect "two steps besides the refusal" \
  "$(yq "[.jobs.\"auto-merge\".steps[] | select(.name != \"${refuse}\")] | length" "$workflow_path")" 2

script=$(yq ".jobs.\"auto-merge\".steps[] | select(.name == \"${refuse}\") | .run" "$workflow_path")
count=$((count + 1))
if out=$(bash -e -o pipefail -c "$script" 2>&1 < /dev/null); then
  failures=$((failures + 1))
  echo "FAIL the refusal exits 0: ${out}"
elif [[ "$out" != *"::error::"* ]]; then
  failures=$((failures + 1))
  echo "FAIL the refusal fails without ::error::: ${out}"
else
  echo "ok   the refusal fails with ::error::"
fi

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
