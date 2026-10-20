#!/usr/bin/env bash
# Runs the steps of tag-release.yml against a fixture repository (a bare remote and a clone) and a fake gh, and asserts
# which commit gets tagged and whether release.yaml is dispatched: on a push run, on a dispatch with a commit (CI on it
# or on a parent with its tree), and on the dispatches it has to refuse.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/tag-release.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
version_file=$(yq '.jobs.tag.steps[] | select(.name == "Tag and Dispatch Release 🏷️") | .run' "$workflow_path" \
  | sed -n 's/^version_file=//p')
step() {
  yq ".jobs.tag.steps[] | select(.name == \"$1\") | .run" "$workflow_path"
}
precheck=$(step "Check the Dispatched SHA ☑️")
oncheck=$(step "Check the Dispatched Commit ☑️")
tagstep=$(step "Tag and Dispatch Release 🏷️")
for script in "$precheck" "$oncheck" "$tagstep"; do
  if [ -z "$script" ] || [ "$script" = "null" ]; then
    echo "a step of ${workflow} was not found" >&2
    exit 1
  fi
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com \
  GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
count=0
failures=0

# fixture: master = base (1.4.1, tagged v1.4.1) -> bump (1.4.2) -> later (1.4.2, another merge)
#   -> merged (1.4.3, the merge of head, a pull request branched from later: the tree of head) -> other (1.4.3)
#   -> stalemerge (1.4.4, the merge of stale, branched from merged: not the tree of stale); side (1.4.2, off master)
git init -q --bare -b master "$work/remote.git"
git clone -q "$work/remote.git" "$work/seed" 2>/dev/null
mkdir -p "$work/seed/$(dirname "$version_file")"
commit() {
  printf '__version__ = "%s"\n' "$1" > "$work/seed/$version_file"
  printf '%s\n' "$2" > "$work/seed/note.txt"
  git -C "$work/seed" add -A
  git -C "$work/seed" commit -q -m "$2"
  git -C "$work/seed" rev-parse HEAD
}
base=$(commit 1.4.1 base)
git -C "$work/seed" tag v1.4.1
bump=$(commit 1.4.2 bump)
later=$(commit 1.4.2 later)
git -C "$work/seed" push -q origin master v1.4.1
git -C "$work/seed" switch -q -c side "$base"
side=$(commit 1.4.2 side)
git -C "$work/seed" push -q origin side
git -C "$work/seed" switch -q -c pr "$later"
head=$(commit 1.4.3 head)
git -C "$work/seed" switch -q master
git -C "$work/seed" merge -q --no-ff -m "Merge pull request #12" pr
merged=$(git -C "$work/seed" rev-parse HEAD)
git -C "$work/seed" switch -q -c stale "$merged"
stale=$(commit 1.4.4 stale)
git -C "$work/seed" switch -q master
printf 'other\n' > "$work/seed/other.txt"
git -C "$work/seed" add other.txt
git -C "$work/seed" commit -q -m other
git -C "$work/seed" merge -q --no-ff -m "Merge pull request #13" stale
stalemerge=$(git -C "$work/seed" rev-parse HEAD)
git -C "$work/seed" push -q origin master
git -C "$work/remote.git" tag v1.3.9 "$base"

# run_case <name> <event> <sha> <ci successes> <release runs on the tag> <expected: tag commit or "none"> <dispatch: yes|no> [reason]
# The tag is v1.4.2 unless $tag names another.
tag=v1.4.2
run_case() {
  local name="$1" event="$2" sha="$3" successes="$4" releases="$5" want_tag="$6" want_dispatch="$7" reason="${8:-}"
  local dir out status got_tag got_dispatch got
  count=$((count + 1))
  dir="$work/case${count}"
  mkdir -p "$dir/bin"
  git -C "$work/remote.git" tag -d "$tag" > /dev/null 2>&1 || :
  if [ "$want_tag" = "preexisting" ]; then
    git -C "$work/remote.git" tag "$tag" "$bump"
  elif [ "$want_tag" = "elsewhere" ]; then
    git -C "$work/remote.git" tag "$tag" "$side"
  fi
  git clone -q "$work/remote.git" "$dir/checkout" 2>/dev/null
  git -C "$dir/checkout" checkout -q "$sha" 2>/dev/null || :
  cat > "$dir/bin/gh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$dir/calls"
case "\$*" in
  *"run list"*"--workflow ci.yaml"*) n=0; for s in $successes; do case "\$*" in *"--commit \$s"*) n=1 ;; esac; done; echo \$n ;;
  *"run list"*"--workflow release.yaml"*) echo $releases ;;
  *"workflow run release.yaml"*) ;;
  *) echo "unexpected gh call: \$*" >&2; exit 2 ;;
esac
EOF
  chmod +x "$dir/bin/gh"
  if [ "$event" = workflow_dispatch ]; then
    if out=$(cd "$dir/checkout" && PATH="$dir/bin:$PATH" GH_TOKEN=x GITHUB_REPOSITORY=o/r SHA="$sha" \
      bash -e -o pipefail -c "$precheck"$'\n'"$oncheck" 2>&1 < /dev/null); then status=0; else status=$?; fi
  else
    status=0
    out=""
  fi
  if [ "$status" -eq 0 ]; then
    if out=$(cd "$dir/checkout" && PATH="$dir/bin:$PATH" GH_TOKEN=x HEAD_SHA="$sha" RUNNER_DEBUG='' \
      bash -e -o pipefail -c "$tagstep" 2>&1 < /dev/null); then status=0; else status=$?; fi
  fi
  got_tag=$(git -C "$work/remote.git" rev-parse -q --verify "refs/tags/${tag}^{commit}" || echo none)
  if [ "$want_tag" = "preexisting" ]; then want_tag="$bump"; fi
  if [ "$want_tag" = "elsewhere" ]; then want_tag="$side"; fi
  if grep -q "workflow run release.yaml" "$dir/calls" 2>/dev/null; then got_dispatch=yes; else got_dispatch=no; fi
  got="tag=${got_tag} dispatch=${got_dispatch} exit=${status}"
  if [ "$got_tag" != "$want_tag" ] || [ "$got_dispatch" != "$want_dispatch" ]; then
    failures=$((failures + 1))
    echo "FAIL ${name}: expected tag=${want_tag} dispatch=${want_dispatch}, got ${got}"
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     /'
  elif [ -n "$reason" ] && { [ "$status" -eq 0 ] || [[ "$out" != *"::error::"*"$reason"* ]]; }; then
    failures=$((failures + 1))
    echo "FAIL ${name}: expected a failure with \"${reason}\", got exit ${status}"
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     /'
  else
    echo "ok   ${name}"
  fi
}

run_case "push run on the bump tags it and starts release.yaml" workflow_run "$bump" "" 0 "$bump" yes
run_case "push run on a later merge is not a release" workflow_run "$later" "" 0 none no
run_case "dispatch with the bump tags it while master has moved on" workflow_dispatch "$bump" "$bump" 0 "$bump" yes
run_case "dispatch with a later commit is not a release" workflow_dispatch "$later" "$later" 0 none no
run_case "dispatch without a successful CI run on the commit" workflow_dispatch "$bump" "$later" 0 none no \
  "no successful CI run"
run_case "dispatch with a commit off master" workflow_dispatch "$side" "$side" 0 none no "is not on master"
run_case "dispatch with something other than a commit SHA" workflow_dispatch "master" "" 0 none no \
  "40-character commit SHA"
run_case "rerun after the release started leaves the tag alone" workflow_dispatch "$bump" "$bump" 1 preexisting no
run_case "rerun before the release started dispatches it again" workflow_dispatch "$bump" "$bump" 0 preexisting yes
run_case "a tag already on another commit is not moved" workflow_dispatch "$bump" "$bump" 0 elsewhere no
tag=v1.4.3
run_case "dispatch with a merge commit whose pull request head passed CI tags it" workflow_dispatch "$merged" "$head" 0 \
  "$merged" yes
run_case "dispatch with a merge commit whose first parent alone passed CI" workflow_dispatch "$merged" "$later" 0 none no \
  "no successful CI run"
tag=v1.4.4
run_case "dispatch with a merge commit whose head passed CI on another tree" workflow_dispatch "$stalemerge" "$stale" 0 \
  none no "no successful CI run"
run_case "dispatch with a merge commit that passed CI itself" workflow_dispatch "$stalemerge" "$stalemerge" 0 \
  "$stalemerge" yes

count=$((count + 1))
if [ "$(yq '.on.workflow_dispatch.inputs.sha.required' "$workflow_path")" = true ] \
  && [ "$(yq '.jobs.tag.if' "$workflow_path")" = "github.event_name == 'workflow_dispatch' || (github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event == 'push')" ] \
  && [ "$(yq '.jobs.tag.steps[0].name' "$workflow_path")" = "Check the Dispatched SHA ☑️" ] \
  && [ "$(yq '.jobs.tag.steps[1].uses | test("^actions/checkout@")' "$workflow_path")" = true ] \
  && [ "$(yq '.jobs.tag.steps[2].name' "$workflow_path")" = "Check the Dispatched Commit ☑️" ] \
  && [ "$(yq '.jobs.tag.steps[] | select(.uses | test("^actions/checkout@")) | .with.ref' "$workflow_path")" = '${{ github.event.workflow_run.head_sha || inputs.sha }}' ] \
  && [ "$(yq '.jobs.tag.steps[] | select(.name == "Tag and Dispatch Release 🏷️") | .env.HEAD_SHA' "$workflow_path")" = '${{ github.event.workflow_run.head_sha || inputs.sha }}' ]; then
  echo "ok   wiring: sha is required, push runs and dispatches only, the SHA is checked before the checkout and the commit after it, which and the tag step use it"
else
  failures=$((failures + 1))
  echo "FAIL wiring: the dispatch input, the job condition, the step order or the commit the steps use changed"
fi

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
