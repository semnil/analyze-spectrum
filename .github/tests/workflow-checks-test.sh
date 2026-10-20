#!/usr/bin/env bash
# Runs the fetch and check steps of the action pin workflow against fixture git trees served by a fake gh,
# and asserts which fixtures pass and which fail with which reason.
# WORKFLOW_FILE and WORKFLOW_JOB select the workflow under test (relative to the repository root, or absolute).
# WORKFLOW_CHECK_STEP=absent declares a workflow without the pin check step; the pin cases are then skipped.
# Otherwise a missing pin check step fails the test.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/workflow-checks.yml}"
job="${WORKFLOW_JOB:-action-pins}"
check_step_mode="${WORKFLOW_CHECK_STEP:-required}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
protected_path=".github/workflows/$(basename "$workflow")"
fetch_step="Fetch the pull request's workflow and action files"
check_step="Check that every uses is pinned to a commit SHA"
step_field() {
  yq ".jobs.\"${job}\".steps[] | select(.name == \"$1\") | .$2" "$workflow_path"
}
fetch=$(step_field "$fetch_step" run)
check=$(step_field "$check_step" run)
pattern=$(step_field "$fetch_step" env.PROTECTED_PATTERN)
if [ -z "$fetch" ] || [ "$fetch" = "null" ] || [ -z "$pattern" ] || [ "$pattern" = "null" ]; then
  echo "the fetch step or its PROTECTED_PATTERN was not found in ${workflow} (job ${job})" >&2
  exit 1
fi
if [ "$check" = "null" ]; then
  check=""
fi
case "$check_step_mode" in
  required)
    if [ -z "$check" ]; then
      echo "the \"${check_step}\" step was not found in ${workflow} (job ${job}); set WORKFLOW_CHECK_STEP=absent only for a workflow that has no pin check step" >&2
      exit 1
    fi
    ;;
  absent)
    if [ -n "$check" ]; then
      echo "WORKFLOW_CHECK_STEP=absent but ${workflow} (job ${job}) has the \"${check_step}\" step" >&2
      exit 1
    fi
    ;;
  *)
    echo "WORKFLOW_CHECK_STEP must be required or absent (got ${check_step_mode})" >&2
    exit 1
    ;;
esac

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
sha=0123456789abcdef0123456789abcdef01234567
count=0
failures=0
skipped=0

new_case() {
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/blobs" "$dir/bin"
  : > "$dir/entries"
  blobs=0
  head_check=chk
}
entry() {
  blobs=$((blobs + 1))
  printf '%s' "$4" > "$dir/blobs/b${blobs}"
  printf '%s\t%s\t%s\tb%s\n' "$1" "$2" "$3" "$blobs" >> "$dir/entries"
}
file() { entry "$1" 100644 blob "$2"; }
link() { entry "$1" 120000 blob "$2"; }
submodule() { entry "$1" 160000 commit ""; }
tree_json() {
  local first=1 path mode type blob
  printf '{"truncated":false,"tree":['
  while IFS=$'\t' read -r path mode type blob; do
    if [ "$first" -eq 0 ]; then printf ','; fi
    first=0
    printf '{"path":"%s","mode":"%s","type":"%s","sha":"%s"}' "$path" "$mode" "$type" "$blob"
  done < "$1"
  printf ']}'
}

# run <name> <pass|fail> [reason substring]
run() {
  local name="$1" expected="$2" reason="${3:-}" out status got
  cp "$workflow_path" "$dir/blobs/chk"
  { cat "$workflow_path"; printf '\n# changed\n'; } > "$dir/blobs/chk2"
  printf '%s\t100644\tblob\tchk\n' "$protected_path" > "$dir/base-entries"
  { cat "$dir/entries"; printf '%s\t100644\tblob\t%s\n' "$protected_path" "$head_check"; } > "$dir/head-entries"
  tree_json "$dir/base-entries" > "$dir/base-tree.json"
  tree_json "$dir/head-entries" > "$dir/head-tree.json"
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
last="\${@: -1}"
case "\$last" in
  */git/trees/base\?*) cat "$dir/base-tree.json" ;;
  */git/trees/head\?*) cat "$dir/head-tree.json" ;;
  */git/blobs/*) cat "$dir/blobs/\${last##*/}" ;;
  *) echo "unexpected gh call: \$*" >&2; exit 2 ;;
esac
EOF
  chmod +x "$dir/bin/gh"
  if out=$(PATH="$dir/bin:$PATH" RUNNER_TEMP="$dir/runner" GITHUB_REPOSITORY=owner/repo HEAD_SHA=head GITHUB_SHA=base \
    GH_TOKEN=unused PROTECTED_PATTERN="$pattern" bash -e -o pipefail -c "${fetch}"$'\n'"${check}" 2>&1 < /dev/null); then
    status=0
  else
    status=$?
  fi
  if [ "$status" -eq 0 ]; then
    got=pass
  elif [[ "$out" != *"::error::"* ]]; then
    got="crash (exit ${status} without ::error::)"
  elif [ -n "$reason" ] && [[ "$out" != *"$reason"* ]]; then
    got="fail without \"${reason}\""
  else
    got=fail
  fi
  if [ "$got" = "$expected" ]; then
    echo "ok   ${name} (${expected})"
  else
    failures=$((failures + 1))
    echo "FAIL ${name}: expected ${expected}, got ${got}"
    printf '%s\n' "$out" | tail -n 12 | sed 's/^/     /'
  fi
}
skip_without_check() {
  if [ -z "$check" ]; then
    skipped=$((skipped + 1))
    echo "skip $1 (WORKFLOW_CHECK_STEP=absent)"
    return 0
  fi
  return 1
}

workflow_yml() {
  printf 'name: w\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@%s # v5.1.0\n%s' "$sha" "$1"
}
composite_yml() {
  printf 'name: x\ndescription: x\nruns:\n  using: composite\n  steps:\n%s' "$1"
}
layout() {
  file .github/actions/ok/action.yml "$(composite_yml "    - run: echo ok
      shell: bash
")"
  link docs/link ../README.md
  submodule third_party/lib
  submodule vendor
  submodule Tools/Sub
  link alias vendor
}
step_case() {
  new_case
  layout
  file .github/workflows/w.yml "$(workflow_yml "      - uses: $4
")"
  run "workflow step: $1" "$2" "$3"
}
composite_case() {
  new_case
  layout
  file .github/workflows/w.yml "$(workflow_yml "      - uses: \$/.github/actions/x
")"
  file .github/actions/x/action.yml "$(composite_yml "    - uses: $4
")"
  run "composite step: $1" "$2" "$3"
}
reusable_yml() {
  printf 'name: r\non:\n  workflow_call:\njobs:\n  r:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@%s # v5.1.0\n' "$sha"
}
job_case() {
  new_case
  layout
  file .github/workflows/r.yml "$(reusable_yml)"
  file .github/workflows/w.yml "$(workflow_yml "")
  b:
    uses: $4
"
  run "job: $1" "$2" "$3"
}
workspace='runner workspace; use $/)'

for kind in step_case composite_case; do
  $kind "\$/ reference to an ordinary action (unrelated symlink and submodules present)" pass "" '$/.github/actions/ok'
  $kind "./ reference to an ordinary action" fail "$workspace" ./.github/actions/ok
  $kind "./ reference into a submodule" fail "$workspace" ./vendor
  $kind "\$/ into a submodule" fail "(submodule vendor)" '$/vendor'
  $kind "\$/ below a submodule" fail "(submodule vendor)" '$/vendor/act'
  $kind "\$/ through a symlink" fail "(symlink alias)" '$/alias'
  $kind "\$/ case-changed submodule" fail "(submodule vendor)" '$/VENDOR/act'
  $kind "\$/ case-changed symlink" fail "(symlink alias)" '$/Alias/act'
  $kind "\$/ lower-case reference to the submodule Tools/Sub" fail "(submodule Tools/Sub)" '$/tools/sub/act'
  $kind "\$/ .. component" fail "(non-canonical path)" '$/docs/../vendor'
  $kind "\$/ backslash" fail "(characters other than" '$/x\..\vendor'
  if ! skip_without_check "${kind%_case}: unpinned action"; then
    $kind "unpinned action" fail "uses must be @<40-char commit SHA>" actions/checkout@v5
  fi
done

job_case "./ reusable workflow in the repository" pass "" ./.github/workflows/r.yml
job_case "\$/ reusable workflow in the repository" pass "" '$/.github/workflows/r.yml'
job_case "./ reusable workflow inside a submodule" fail "(submodule vendor)" ./vendor/.github/workflows/r.yml
job_case "./ reusable workflow through a case-changed submodule path" fail "(submodule vendor)" ./VENDOR/.github/workflows/r.yml
job_case "./ reusable workflow with a .. component" fail "(non-canonical path)" ./docs/../.github/workflows/r.yml

new_case
layout
file .github/workflows/w.yml "$(workflow_yml "      - uses: actions/checkout@$sha # v5.1.0
        with:
          repository: someone/external
          path: external-action
      - uses: ./external-action
")"
run "workflow step: ./ to another repository checked out into the workspace" fail "$workspace"

new_case
file .github/workflows/w.yml "$(workflow_yml "      - uses: \$/key
")"
submodule "$(printf '\342\204\252')ey"
run "submodule whose name starts with KELVIN SIGN, reached by \$/key" fail "(submodule "

new_case
layout
file .github/workflows/w.yml "$(workflow_yml "")"
head_check=chk2
run "check file differs from the default branch" fail "must be identical to the default branch"

new_case
layout
file .github/workflows/w.yml "$(workflow_yml "")"
link .github/actions/l/action.yml ../ok/action.yml
run "symlinked action.yml" fail "must be regular files"

new_case
layout
file .github/workflows/w.yml "$(workflow_yml "")"
file .github/actions/u/Action.yml "$(composite_yml "    - run: echo ok
      shell: bash
")"
run "action file name that is not lowercase" fail "must be lowercase"

# The workflow_dispatch entry: the resolve step, the report job, and how they are wired.
# WORKFLOW_DISPATCH_STEPS=absent declares a workflow without them; these cases are then skipped.
resolve_step="Resolve the pull request"
report_job="${WORKFLOW_REPORT_JOB:-report}"
report_step="Post action-pins on the pull request's head commit"
dispatch_mode="${WORKFLOW_DISPATCH_STEPS:-required}"
resolve=$(step_field "$resolve_step" run)
report=$(yq ".jobs.\"${report_job}\".steps[] | select(.name == \"${report_step}\") | .run" "$workflow_path")
if [ "$resolve" = "null" ]; then resolve=""; fi
if [ "$report" = "null" ]; then report=""; fi
case "$dispatch_mode" in
  required)
    if [ -z "$resolve" ] || [ -z "$report" ]; then
      echo "the \"${resolve_step}\" step or the ${report_job} job's \"${report_step}\" step was not found in ${workflow}; set WORKFLOW_DISPATCH_STEPS=absent only for a workflow without the dispatch entry" >&2
      exit 1
    fi
    ;;
  absent)
    if [ -n "$resolve" ] || [ -n "$report" ]; then
      echo "WORKFLOW_DISPATCH_STEPS=absent but ${workflow} has the dispatch steps" >&2
      exit 1
    fi
    ;;
  *)
    echo "WORKFLOW_DISPATCH_STEPS must be required or absent (got ${dispatch_mode})" >&2
    exit 1
    ;;
esac

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
head=89abcdef0123456789abcdef0123456789abcdef
pr_json() {
  printf '{"state":"%s","base":{"ref":"%s"},"head":{"sha":"%s"}}' "$1" "$2" "$3"
}
# resolve_case <name> <pass|fail> <reason or expected head_sha> <event> <ref> <pr> [pr json]
resolve_case() {
  local name="$1" expected="$2" detail="$3" event="$4" ref="$5" pr="$6" json="${7:-}" out status got written
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/bin" "$dir/runner"
  printf '%s' "$json" > "$dir/pr.json"
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
if [ "\$*" = "api repos/owner/repo/pulls/${pr}" ]; then cat "$dir/pr.json"; exit 0; fi
echo "unexpected gh call: \$*" >&2
exit 2
EOF
  chmod +x "$dir/bin/gh"
  : > "$dir/output"
  if out=$(PATH="$dir/bin:$PATH" RUNNER_TEMP="$dir/runner" GITHUB_REPOSITORY=owner/repo GITHUB_OUTPUT="$dir/output" \
    GITHUB_REF="$ref" GH_TOKEN=unused EVENT_NAME="$event" EVENT_HEAD_SHA="$sha" PR="$pr" DEFAULT_BRANCH=main \
    bash -e -o pipefail -c "$resolve" 2>&1 < /dev/null); then
    status=0
  else
    status=$?
  fi
  written=$(cat "$dir/output")
  if [ "$status" -eq 0 ]; then
    if [ "$written" = "head_sha=${detail}" ]; then got=pass; else got="pass writing \"${written}\""; fi
  elif [[ "$out" != *"::error::"* ]]; then
    got="crash (exit ${status} without ::error::)"
  elif [[ "$out" != *"$detail"* ]]; then
    got="fail without \"${detail}\""
  elif [ -n "$written" ]; then
    got="fail writing \"${written}\""
  else
    got=fail
  fi
  if [ "$got" = "$expected" ]; then
    echo "ok   resolve: ${name} (${expected})"
  else
    failures=$((failures + 1))
    echo "FAIL resolve: ${name}: expected ${expected}, got ${got}"
    printf '%s\n' "$out" | tail -n 6 | sed 's/^/     /'
  fi
}
# report_case <name> <job result> <expected conclusion>
report_case() {
  local name="$1" result="$2" conclusion="$3" out want
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/bin"
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$@" > "$dir/calls"
EOF
  chmod +x "$dir/bin/gh"
  if ! out=$(PATH="$dir/bin:$PATH" GITHUB_REPOSITORY=owner/repo GH_TOKEN=unused HEAD_SHA="$head" RESULT="$result" \
    RUN_URL=https://github.com/owner/repo/actions/runs/1 bash -e -o pipefail -c "$report" 2>&1 < /dev/null); then
    failures=$((failures + 1))
    echo "FAIL report: ${name}: exited non-zero"
    printf '%s\n' "$out" | tail -n 6 | sed 's/^/     /'
    return
  fi
  for want in "--method" "POST" "repos/owner/repo/check-runs" "name=action-pins" "head_sha=${head}" \
    "status=completed" "conclusion=${conclusion}"; do
    if ! grep -qxF -- "$want" "$dir/calls"; then
      failures=$((failures + 1))
      echo "FAIL report: ${name}: the check run was posted without ${want}"
      sed 's/^/     /' "$dir/calls"
      return
    fi
  done
  echo "ok   report: ${name} (${conclusion})"
}

if [ "$dispatch_mode" = absent ]; then
  skipped=$((skipped + 1))
  echo "skip dispatch entry (WORKFLOW_DISPATCH_STEPS=absent)"
else
  on_pr_target=$(yq '.on | has("pull_request_target")' "$workflow_path")
  dispatch_input=$(yq '.on.workflow_dispatch.inputs.pr.required' "$workflow_path")
  expect "wiring: still runs on pull_request_target" "$on_pr_target" true
  expect "wiring: workflow_dispatch requires the pr input" "$dispatch_input" true
  for step in "$fetch_step" "$check_step"; do
    if [ "$step" = "$check_step" ] && [ -z "$check" ]; then continue; fi
    expect "wiring: \"${step}\" reads the resolved head commit" "$(step_field "$step" env.HEAD_SHA)" \
      '${{ steps.target.outputs.head_sha }}'
  done
  expect "wiring: ${job} exports the resolved head commit" "$(yq ".jobs.\"${job}\".outputs.head_sha" "$workflow_path")" \
    '${{ steps.target.outputs.head_sha }}'
  expect "wiring: ${job} keeps the read-only token" "$(yq ".jobs.\"${job}\" | has(\"permissions\")" "$workflow_path")" false
  expect "wiring: ${report_job} only gets checks: write" \
    "$(yq -o=json -I=0 ".jobs.\"${report_job}\".permissions" "$workflow_path")" '{"checks":"write"}'
  expect "wiring: ${report_job} waits for ${job}" "$(yq ".jobs.\"${report_job}\".needs" "$workflow_path")" "$job"
  expect "wiring: ${report_job} runs after a failed check on a dispatch only" \
    "$(yq ".jobs.\"${report_job}\".if" "$workflow_path")" \
    "always() && github.event_name == 'workflow_dispatch' && needs.${job}.outputs.head_sha != ''"

  resolve_case "pull_request_target passes the event's head commit" pass "$sha" pull_request_target refs/pull/7/merge ""
  resolve_case "dispatch on the default branch for an open pull request" pass "$head" workflow_dispatch refs/heads/main 7 \
    "$(pr_json open main "$head")"
  resolve_case "dispatch on another branch" fail "dispatch this check on the default branch" workflow_dispatch \
    refs/heads/topic 7 "$(pr_json open main "$head")"
  resolve_case "dispatch with a pr that is not a number" fail "pr must be a pull request number" workflow_dispatch \
    refs/heads/main "7;id" ""
  resolve_case "dispatch for a closed pull request" fail "is closed, not open" workflow_dispatch refs/heads/main 7 \
    "$(pr_json closed main "$head")"
  resolve_case "dispatch for a pull request against another branch" fail "targets release, not the default branch" \
    workflow_dispatch refs/heads/main 7 "$(pr_json open release "$head")"
  resolve_case "dispatch for a pull request without a full head SHA" fail "no 40-character head commit SHA" \
    workflow_dispatch refs/heads/main 7 "$(pr_json open main 89abcdef)"

  report_case "a passing check" success success
  report_case "a failing check" failure failure
  report_case "a cancelled check" cancelled failure
fi

echo "${count} cases, ${failures} failed, ${skipped} skipped"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
