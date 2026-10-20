#!/usr/bin/env bash
# Checks the workflow_dispatch entry of dependabot-auto-merge.yml: both triggers, the Dependabot steps keeping their
# condition, and the step that refuses a dispatch for a Dependabot commit, run here against a fake gh.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/dependabot-auto-merge.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
refuse="Refuse a dispatch for a Dependabot commit"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
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
expect "the refusal runs for every dispatch" \
  "$(yq ".jobs.\"auto-merge\".steps[] | select(.name == \"${refuse}\") | .if" "$workflow_path")" \
  "github.event_name == 'workflow_dispatch'"
expect "the other steps run for dependabot[bot] only" \
  "$(yq "[.jobs.\"auto-merge\".steps[] | select(.name != \"${refuse}\") | .if] | unique | .[]" "$workflow_path")" \
  "github.event.pull_request.user.login == 'dependabot[bot]'"
expect "two steps besides the refusal" \
  "$(yq "[.jobs.\"auto-merge\".steps[] | select(.name != \"${refuse}\")] | length" "$workflow_path")" 2

script=$(yq ".jobs.\"auto-merge\".steps[] | select(.name == \"${refuse}\") | .run" "$workflow_path")
sha=0123456789abcdef0123456789abcdef01234567
# refusal_case <name> <pass|fail> <ref name> <authors gh prints, or FAIL for a failing gh call>
refusal_case() {
  local name="$1" expected="$2" ref="$3" authors="$4" out status got dir
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/bin"
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$dir/calls"
if [ "$authors" = FAIL ]; then echo "HTTP 502" >&2; exit 1; fi
if [ "\$1 \$2" = "api repos/owner/repo/commits/${sha}/pulls" ]; then printf '%s\\n' "$authors"; exit 0; fi
echo "unexpected gh call: \$*" >&2
exit 2
EOF
  chmod +x "$dir/bin/gh"
  if out=$(PATH="$dir/bin:$PATH" GH_TOKEN=unused GITHUB_REPOSITORY=owner/repo GITHUB_REF_NAME="$ref" GITHUB_SHA="$sha" \
    bash -e -o pipefail -c "$script" 2>&1 < /dev/null); then
    status=0
  else
    status=$?
  fi
  if [ "$status" -eq 0 ]; then
    got=pass
  elif [ "$authors" != FAIL ] && [[ "$out" != *"::error::"* ]]; then
    got="fail without ::error::"
  else
    got=fail
  fi
  if [ "$got" = "$expected" ]; then
    echo "ok   refusal: ${name} (${expected})"
  else
    failures=$((failures + 1))
    echo "FAIL refusal: ${name}: expected ${expected}, got ${got}"
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     /'
  fi
}
refusal_case "a dependabot/ branch, whatever pull requests the commit is in" fail dependabot/pip/yt-dlp-2026.9.1 ""
refusal_case "a commit in a pull request dependabot[bot] opened" fail ffmpeg-watch/pin-9.0 "github-actions[bot] dependabot[bot]"
refusal_case "a commit in a pull request github-actions[bot] opened" pass ffmpeg-watch/pin-9.0 "github-actions[bot]"
refusal_case "a commit in no pull request" pass topic ""
refusal_case "a failing lookup of the commit's pull requests" fail ffmpeg-watch/pin-9.0 FAIL

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
