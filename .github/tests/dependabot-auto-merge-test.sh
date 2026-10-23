#!/usr/bin/env bash
# Checks that dependabot-auto-merge.yml reports `auto-merge` on every pull request: only pull_request starts it, the
# job has no condition of its own, and its steps alone are limited to pull requests dependabot[bot] opened. Then runs
# the step that decides, against a fake gh, for each package ecosystem and update type fetch-metadata can report and
# for the commits of the pull request (their authors, how many there are, whether the last is the head, who committed
# it and whether its signature is verified): which get auto-merge enabled (pinned to the head commit), which get an
# earlier auto-merge turned off, and that a failure to read the commits or the auto-merge state fails the step. The
# fake gh answers the commits query by running its --jq expression with jq on a commits document of the case, and the
# REST commit list with the same commits in the shape the pulls API returns.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/dependabot-auto-merge.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
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

expect "only pull_request starts the job" "$(yq -o=json -I=0 '.on | keys' "$workflow_path")" '["pull_request"]'
expect "the job has no condition of its own" "$(yq '.jobs."auto-merge" | has("if")' "$workflow_path")" false
expect "every step runs for dependabot[bot] only" \
  "$(yq '[.jobs."auto-merge".steps[].if] | unique | .[]' "$workflow_path")" \
  "github.event.pull_request.user.login == 'dependabot[bot]'"
expect "two steps" "$(yq '.jobs."auto-merge".steps | length' "$workflow_path")" 2
decide='.jobs."auto-merge".steps[] | select(has("run"))'
expect "the deciding step reads the ecosystem from fetch-metadata" "$(yq "${decide} | .env.ECOSYSTEM" "$workflow_path")" \
  '${{ steps.metadata.outputs.package-ecosystem }}'
expect "the deciding step reads the update type from fetch-metadata" "$(yq "${decide} | .env.UPDATE_TYPE" "$workflow_path")" \
  '${{ steps.metadata.outputs.update-type }}'

script=$(yq "${decide} | .run" "$workflow_path")
head=0123456789abcdef0123456789abcdef01234567
url=https://github.com/owner/repo/pull/7
other=fedcba9876543210fedcba9876543210fedcba98
# decision_case <name> <ecosystem> <update type> <commit authors: commits split by ";", the authors of a commit by ","|FAIL>
#   <auto-merge state gh reports: true|false|FAIL> <expected: enable|disable|none|fail>
#   [<the REST commit list: ok|FAIL> <signature of the commits: verified|unverified> <sha of the last commit: head|other>
#   <sha of the other commits: other|head> <committer of the commits: web-flow|another login>]
# In the REST commit list each commit's author is the first of its authors, the last commit carries the given sha and
# the others the other given one.
decision_case() {
  local name="$1" ecosystem="$2" update="$3" commits="$4" state="$5" expected="$6" rest="${7:-ok}"
  local signature="${8:-verified}" last="${9:-head}" first="${10:-other}" committer="${11:-web-flow}" dir out status got
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/bin"
  : > "$dir/calls"
  jq -n -c --arg c "$commits" \
    '{commits: ($c | if . == "" then [] else split(";") end | map({authors: (split(",") | map({login: .}))}))}' \
    > "$dir/commits.json"
  jq -c --arg last "$([ "$last" = head ] && echo "$head" || echo "$other")" \
    --arg first "$([ "$first" = head ] && echo "$head" || echo "$other")" \
    --argjson verified "$([ "$signature" = verified ] && echo true || echo false)" --arg committer "$committer" \
    '.commits | length as $n | to_entries | map({sha: (if .key == ($n - 1) then $last else $first end),
      author: {login: (.value.authors[0].login // null)}, committer: {login: $committer},
      commit: {verification: {verified: $verified}}})' \
    "$dir/commits.json" > "$dir/rest-commits.json"
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$dir/calls"
case "\$*" in
  "pr view ${url} --json autoMergeRequest --jq .autoMergeRequest != null")
    if [ "${state}" = FAIL ]; then echo "HTTP 502" >&2; exit 1; fi
    echo "${state}" ;;
  "pr view ${url} --json commits --jq "*)
    if [ "${commits}" = FAIL ]; then echo "HTTP 502" >&2; exit 1; fi
    jq -r "\$7" "$dir/commits.json" ;;
  "api repos/owner/repo/pulls/7/commits?per_page=100")
    if [ "${rest}" = FAIL ]; then echo "HTTP 502" >&2; exit 1; fi
    cat "$dir/rest-commits.json" ;;
  "pr merge --auto --merge --match-head-commit ${head} ${url}" | "pr merge --disable-auto ${url}") ;;
  *) echo "unexpected gh call: \$*" >&2; exit 2 ;;
esac
EOF
  chmod +x "$dir/bin/gh"
  if out=$(PATH="$dir/bin:$PATH" GH_TOKEN=unused GITHUB_REPOSITORY=owner/repo PR_URL="$url" PR_NUMBER=7 \
    HEAD_SHA="$head" ECOSYSTEM="$ecosystem" UPDATE_TYPE="$update" \
    bash -e -o pipefail -c "$script" 2>&1 < /dev/null); then status=0; else status=$?; fi
  if [ "$status" -ne 0 ]; then
    got=fail
  elif grep -qx "pr merge --auto --merge --match-head-commit ${head} ${url}" "$dir/calls"; then
    got=enable
  elif grep -qx "pr merge --disable-auto ${url}" "$dir/calls"; then
    got=disable
  else
    got=none
  fi
  if [ "$got" = "$expected" ]; then
    echo "ok   decision: ${name} (${expected})"
  else
    failures=$((failures + 1))
    echo "FAIL decision: ${name}: expected ${expected}, got ${got}"
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     /'
  fi
}
patch=version-update:semver-patch
minor=version-update:semver-minor
major=version-update:semver-major
bot='dependabot[bot]'
decision_case "a uv patch" uv "$patch" "$bot" false enable
decision_case "a uv minor" uv "$minor" "$bot" false enable
decision_case "a uv major" uv "$major" "$bot" false enable
decision_case "a uv update without a type" uv "" "$bot" false none
decision_case "a submodule update (fetch-metadata reports a commit change as major)" submodules "$major" "$bot" false enable
decision_case "a submodule update without a type" submodules "" "$bot" false enable
decision_case "a GitHub Action patch" github_actions "$patch" "$bot" false enable
decision_case "a GitHub Action minor" github_actions "$minor" "$bot" false enable
decision_case "a GitHub Action major" github_actions "$major" "$bot" false none
decision_case "a GitHub Action major after auto-merge was enabled" github_actions "$major" "$bot" true disable
decision_case "a GitHub Action update without a type" github_actions "" "$bot" true disable
decision_case "another ecosystem's patch" pip "$patch" "$bot" false none
decision_case "no ecosystem" "" "$patch" "$bot" true disable
decision_case "a GitHub Action major when the auto-merge state cannot be read" github_actions "$major" "$bot" FAIL fail
decision_case "an unexpected auto-merge state" github_actions "$major" "$bot" maybe fail
decision_case "a uv patch with two Dependabot commits" uv "$patch" "$bot;$bot" false none
decision_case "a uv patch with two Dependabot commits after auto-merge was enabled" uv "$patch" "$bot;$bot" true disable
decision_case "a uv patch with two Dependabot commits, the head listed first" uv "$patch" "$bot;$bot" true disable ok verified other head
decision_case "a uv major with a commit someone else wrote" uv "$major" "$bot;someone" false none
decision_case "a uv major with a commit someone else wrote after auto-merge was enabled" uv "$major" "$bot;someone" true disable
decision_case "a submodule update with a merge commit someone else made" submodules "$major" "$bot;someone,other" true disable
decision_case "a GitHub Action minor whose commit has a second author" github_actions "$minor" "$bot,someone" true disable
decision_case "a GitHub Action patch whose commit has an author without a GitHub login" github_actions "$patch" "$bot," true disable
decision_case "a uv patch with no commits" uv "$patch" "" true disable
decision_case "a uv patch when the commits cannot be read" uv "$patch" FAIL false fail
decision_case "a uv patch whose only commit is unverified" uv "$patch" "$bot" true disable ok unverified
decision_case "a GitHub Action patch whose Dependabot commit someone else amended and signed" github_actions "$patch" \
  "$bot" true disable ok verified head other someone
decision_case "a GitHub Action minor whose Dependabot commit is not the head" github_actions "$minor" "$bot" true disable ok verified other
decision_case "a submodule update when the REST commit list cannot be read" submodules "$major" "$bot" false fail FAIL

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
