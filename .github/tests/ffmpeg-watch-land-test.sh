#!/usr/bin/env bash
# Runs the land step of ffmpeg-watch.yml against a fixture repository (a bare remote and a shallow clone) and a fake gh
# that answers by the token a call carries: a pull request the App's token opens gets successful pull_request runs of
# CI and dependabot-auto-merge.yml and a pull_request_target run of workflow-checks.yml, one GITHUB_TOKEN opens gets
# pull_request runs that wait for an approval and no pull_request_target run, a merge needs the three required checks
# and codecov/project, which reports only after land has polled the pull request (CODECOV_AFTER polls; CODECOV=failure
# reports a failure, CODECOV=never reports nothing), auto-merge merges once they have all passed, and a merge with the
# App's token starts a push run of CI on master. VIEW_FAIL fails every poll of a pull request's state, AUTO_FAIL fails
# the call that enables auto-merge after enabling it, DISABLE_FAIL fails turning it off, and LAND_SIGNAL cancels land
# during its first wait between polls (the sleep stub below). It asserts what lands on master, which token
# opened and merged each pull request, and what land dispatched. It also checks that a queued detect reads the
# updated pin, version and tags from master after an earlier run completes, that smoke uses its recorded commit, that
# the detect step hands the next attempt to retry when the CLI exits 3, and that retry dispatches it with GITHUB_TOKEN.
# WORKFLOW_FILE selects the workflow under test (relative to the repository root, or absolute).
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
workflow="${WORKFLOW_FILE:-.github/workflows/ffmpeg-watch.yml}"
case "$workflow" in
  /*) workflow_path="$workflow" ;;
  *) workflow_path="$root/$workflow" ;;
esac
land=$(yq '.jobs.land.steps[] | select(.name == "Land 🛬") | .run' "$workflow_path")
if [ -z "$land" ] || [ "$land" = "null" ]; then
  echo "the Land step of ${workflow} was not found" >&2
  exit 1
fi
version_file=$(printf '%s\n' "$land" | sed -n 's/^version_file=//p')
pin_file=$(printf '%s\n' "$land" | sed -n 's/^pin_file=//p')

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com \
  GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com \
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.useConfigOnly GIT_CONFIG_VALUE_0=true
app_token=app-token
github_token=github-token
app_slug=ffmpeg-watch-test
bot_id=424242
count=0
failures=0

cat > "$work/gh.py" <<'EOF'
"""The gh calls of the land step, answered from $FAKE_STATE (JSON) and the bare remote $FAKE_REMOTE."""
import json
import os
import subprocess
import sys

STATE, REMOTE = os.environ["FAKE_STATE"], os.environ["FAKE_REMOTE"]
APP, GITHUB = os.environ["FAKE_APP_TOKEN"], os.environ["FAKE_GITHUB_TOKEN"]
REQUIRED = {"ci.yaml": "pull_request", "dependabot-auto-merge.yml": "pull_request",
            "workflow-checks.yml": "pull_request_target"}
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="GitHub", GIT_AUTHOR_EMAIL="noreply@github.com",
               GIT_COMMITTER_NAME="GitHub", GIT_COMMITTER_EMAIL="noreply@github.com")


def git(*args):
    r = subprocess.run(["git", "-C", REMOTE, *args], capture_output=True, text=True, env=GIT_ENV)
    if r.returncode != 0:
        sys.exit(f"fake gh: git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def emit(obj, opts):
    data = json.dumps(obj)
    if "--jq" in opts:
        r = subprocess.run(["jq", "-r", opts["--jq"]], input=data, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"fake gh: jq {opts['--jq']}: {r.stderr.strip()}")
        sys.stdout.write(r.stdout)
    else:
        print(data)


def parse(args):
    opts, rest, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a in ("--exit-status", "--compact", "--required", "--merge", "--auto", "--disable-auto"):
            opts[a] = True
        elif a.startswith("-"):
            if a == "-f":
                opts.setdefault("-f", []).append(args[i + 1])
            else:
                opts[a] = args[i + 1]
            i += 1
        else:
            rest.append(a)
        i += 1
    return opts, rest


def add_run(state, workflow, event, sha, conclusion):
    state["next_run"] += 1
    state["runs"].append({"id": state["next_run"], "workflow": workflow, "event": event, "sha": sha,
                          "conclusion": conclusion})


def checks_pass(state, sha):
    return all(any(r["workflow"] == w and r["event"] == e and r["sha"] == sha and r["conclusion"] == "success"
                   for r in state["runs"]) for w, e in REQUIRED.items())


def codecov(state, sha):
    """codecov/project on sha: None until it reports, then its conclusion."""
    outcome = os.environ.get("CODECOV", "success")
    if outcome == "never" or state["polls"].get(sha, 0) < int(os.environ.get("CODECOV_AFTER", "2")):
        return None
    return outcome


def merge_pr(state, pr, head, token):
    master = git("rev-parse", "refs/heads/master")
    merge = git("commit-tree", f"{head}^{{tree}}", "-p", master, "-p", head,
                "-m", f"Merge pull request #{pr['number']} from o/{pr['head']}")
    git("update-ref", "refs/heads/master", merge)
    pr.update(state="MERGED", merged_by=token, merge=merge)
    if token == APP:
        add_run(state, "ci.yaml", "push", merge, "success")


def main():
    args = sys.argv[1:]
    token = os.environ.get("GH_TOKEN", "")
    with open(STATE, encoding="utf-8") as f:
        state = json.load(f)
    state["calls"].append({"args": args, "token": token})
    opts, rest = parse(args[2:])
    group, verb = args[0], args[1]
    status = 0
    if token not in (APP, GITHUB):
        print(f"fake gh: unknown token {token!r}", file=sys.stderr)
        status = 4
    elif (group, verb) == ("pr", "list"):
        emit([{"number": p["number"], "headRefName": p["head"]} for p in state["prs"] if p["state"] == "OPEN"], opts)
    elif (group, verb) == ("api", "users/" + os.environ["FAKE_APP_SLUG"] + "[bot]"):
        emit({"id": int(os.environ["FAKE_BOT_ID"])}, opts)
    elif (group, verb) == ("pr", "create"):
        head = opts["--head"]
        sha = git("rev-parse", f"refs/heads/{head}")
        state["next_pr"] += 1
        state["prs"].append({"number": state["next_pr"], "head": head, "state": "OPEN", "opened_by": token,
                             "merged_by": None, "merge": None, "auto": None})
        if token == APP:
            for workflow, event in REQUIRED.items():
                failing = os.environ.get("FAIL_RUN") == workflow
                if not (os.environ.get("NO_TARGET_RUN") and event == "pull_request_target"):
                    add_run(state, workflow, event, sha, "failure" if failing else "success")
        else:
            for workflow, event in REQUIRED.items():
                if event == "pull_request":
                    add_run(state, workflow, event, sha, "action_required")
        print(f"https://github.com/o/r/pull/{state['next_pr']}")
    elif (group, verb) == ("pr", "view"):
        pr = next(p for p in state["prs"] if str(p["number"]) == rest[0] or p["head"] == rest[0])
        if "state" in opts.get("--json", "").split(",") and pr["state"] == "OPEN" and os.environ.get("VIEW_FAIL"):
            print("HTTP 502: Bad Gateway (https://api.github.com/graphql)", file=sys.stderr)
            status = 1
        elif "state" in opts.get("--json", "").split(",") and pr["state"] == "OPEN":
            head = git("rev-parse", f"refs/heads/{pr['head']}")
            state["polls"][head] = state["polls"].get(head, 0) + 1
            if pr.get("auto") and checks_pass(state, head) and codecov(state, head) == "success":
                merge_pr(state, pr, head, pr["auto"])
        if status == 0:
            emit({"number": pr["number"], "state": pr["state"]}, opts)
    elif (group, verb) == ("run", "list"):
        runs = [r for r in state["runs"] if r["workflow"] == opts.get("--workflow")
                and r["event"] == opts.get("--event") and r["sha"] == opts.get("--commit")]
        runs.sort(key=lambda r: -r["id"])
        emit([{"databaseId": r["id"]} for r in runs[: int(opts.get("--limit", 20))]], opts)
    elif (group, verb) == ("run", "watch"):
        run = next(r for r in state["runs"] if str(r["id"]) == rest[0])
        if run["conclusion"] != "success":
            print(f"run {run['id']} {run['conclusion']}", file=sys.stderr)
            status = 1
    elif (group, verb) == ("pr", "checks"):
        pr = next(p for p in state["prs"] if str(p["number"]) == rest[0])
        head = git("rev-parse", f"refs/heads/{pr['head']}")
        if not checks_pass(state, head):
            print(f"no checks reported on the '{pr['head']}' branch", file=sys.stderr)
            status = 1
        elif codecov(state, head) == "failure":
            print("codecov/project\tfail", file=sys.stderr)
            status = 1
    elif (group, verb) == ("pr", "merge") and "--disable-auto" in opts:
        pr = next(p for p in state["prs"] if str(p["number"]) == rest[0])
        if os.environ.get("DISABLE_FAIL"):
            print("HTTP 502: Bad Gateway (https://api.github.com/graphql)", file=sys.stderr)
            status = 1
        else:
            pr["auto"] = None
    elif (group, verb) == ("pr", "merge"):
        pr = next(p for p in state["prs"] if str(p["number"]) == rest[0])
        head = git("rev-parse", f"refs/heads/{pr['head']}")
        master = git("rev-parse", "refs/heads/master")
        if head != opts.get("--match-head-commit") or git("merge-base", master, head) != master:
            print("the base branch policy prohibits the merge", file=sys.stderr)
            status = 1
        elif "--auto" in opts:
            pr["auto"] = token
            if os.environ.get("AUTO_FAIL"):
                print("HTTP 502: Bad Gateway (https://api.github.com/graphql)", file=sys.stderr)
                status = 1
        elif not checks_pass(state, head) or codecov(state, head) != "success":
            print('Required status check "codecov/project" is expected.', file=sys.stderr)
            status = 1
        else:
            merge_pr(state, pr, head, token)
    elif (group, verb) == ("workflow", "run"):
        state["dispatches"].append({"workflow": rest[0], "ref": opts.get("--ref"), "inputs": opts.get("-f", []),
                                    "token": token})
    else:
        print(f"fake gh: unexpected {' '.join(args)}", file=sys.stderr)
        status = 3
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    sys.exit(status)


main()
EOF

# fixture: master = base (version 1.4.1, pin series 8.1, tagged v1.4.1)
git init -q --bare -b master "$work/remote.git"
git clone -q "$work/remote.git" "$work/seed" 2>/dev/null
mkdir -p "$work/seed/$(dirname "$version_file")" "$work/seed/$(dirname "$pin_file")"
printf '__version__ = "1.4.1"\n' > "$work/seed/$version_file"
printf '{"series": "8.1"}\n' > "$work/seed/$pin_file"
git -C "$work/seed" add -A
git -C "$work/seed" commit -q -m base
base=$(git -C "$work/seed" rev-parse HEAD)
git -C "$work/seed" tag v1.4.1
git -C "$work/seed" push -q origin master v1.4.1
printf '{"series": "9.0"}\n' > "$work/candidate.json"

# A queued run retains the event's commit while an earlier run advances master.
printf '{"series": "9.0"}\n' > "$work/seed/$pin_file"
printf '__version__ = "1.4.2"\n' > "$work/seed/$version_file"
git -C "$work/seed" add -- "$pin_file" "$version_file"
git -C "$work/seed" commit -q -m "an earlier run completed the update"
completed=$(git -C "$work/seed" rev-parse HEAD)
git -C "$work/seed" tag v1.4.2
git -C "$work/seed" push -q origin master v1.4.2
detect_ref=$(yq '.jobs.detect.steps[] | select(.uses | test("^actions/checkout@")) | .with.ref // ""' "$workflow_path")
git clone -q --no-checkout "file://$work/remote.git" "$work/detect" 2>/dev/null
git -C "$work/detect" checkout -q --detach "${detect_ref:-$base}"
count=$((count + 1))
if [ "$(git -C "$work/detect" rev-parse HEAD)" = "$completed" ] \
  && [ "$(git -C "$work/detect" show "HEAD:$pin_file" | jq -r .series)" = 9.0 ] \
  && [ "$(git -C "$work/detect" show "HEAD:$version_file")" = '__version__ = "1.4.2"' ] \
  && [ "$(git -C "$work/detect" rev-parse v1.4.2)" = "$completed" ] \
  && [ "$(yq '.jobs.detect.steps[] | select(.uses | test("^actions/checkout@")) | .with.fetch-depth' "$workflow_path")" = 0 ] \
  && [ "$(yq '.concurrency.group' "$workflow_path")" = ffmpeg-watch ] \
  && [ "$(yq '.concurrency.cancel-in-progress' "$workflow_path")" = false ]; then
  echo "ok   a queued detect reads master's completed pin, version and tag under serial execution"
else
  failures=$((failures + 1))
  echo "FAIL a queued detect must read master's completed pin, version and tag under serial execution"
  echo "     event=$base checked_out=$(git -C "$work/detect" rev-parse HEAD) master=$completed"
fi

snapshot=$(yq '.jobs.detect.steps[] | select(.id == "snapshot") | .run' "$workflow_path")
if [ -z "$snapshot" ] || [ "$snapshot" = null ]; then
  echo "FAIL detect must record its checkout commit" >&2
  exit 1
fi
(cd "$work/detect" && GITHUB_OUTPUT="$work/snapshot-output" bash -e -o pipefail -c "$snapshot")
snapshot_commit=$(sed -n 's/^commit=//p' "$work/snapshot-output")
count=$((count + 1))
if [ "$snapshot_commit" = "$completed" ] \
  && [ "$(yq '.jobs.detect.outputs.commit' "$workflow_path")" = '${{ steps.snapshot.outputs.commit }}' ] \
  && [ "$(yq '.jobs.smoke.steps[] | select(.uses | test("^actions/checkout@")) | .with.ref' "$workflow_path")" = '${{ needs.detect.outputs.commit }}' ]; then
  echo "ok   smoke checks out the commit recorded and exported by detect"
else
  failures=$((failures + 1))
  echo "FAIL smoke must check out the commit recorded and exported by detect"
fi

mkdir -p "$work/bin"
printf '#!/usr/bin/env bash\nexec python3 -I %q "$@"\n' "$work/gh.py" > "$work/bin/gh"
chmod +x "$work/bin/gh"

detect_step=$(yq '.jobs.detect.steps[] | select(.id == "detect") | .run' "$workflow_path")
max_attempts=$(yq '.jobs.detect.steps[] | select(.id == "detect") | .env.MAX_DETECT_ATTEMPTS' "$workflow_path")
retry_step=$(yq '.jobs.retry.steps[] | select(.name == "Dispatch the Next Attempt 🔁") | .run' "$workflow_path")
if [ -z "$detect_step" ] || [ "$detect_step" = null ] || [ -z "$retry_step" ] || [ "$retry_step" = null ] \
  || ! [[ "$max_attempts" =~ ^[0-9]+$ ]]; then
  echo "FAIL the detect step, its MAX_DETECT_ATTEMPTS or the step of retry was not found in ${workflow}" >&2
  exit 1
fi
mkdir -p "$work/detect-bin"
cat > "$work/detect-bin/python" <<'EOF'
#!/usr/bin/env bash
# The detect CLI: exits FAKE_DETECT_STATUS, and appends two outputs to --github-output when that is 0.
if [ "$1 $2 $3" != "-m analyze_common.ffmpeg_release detect" ]; then
  echo "fake python: unexpected $*" >&2
  exit 99
fi
echo run >> "$FAKE_DETECT_CALLS"
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = --github-output ]; then out="$2"; fi
  shift
done
if [ "$FAKE_DETECT_STATUS" -eq 0 ]; then printf 'pin_update=false\nbump=false\n' >> "$out"; fi
exit "$FAKE_DETECT_STATUS"
EOF
chmod +x "$work/detect-bin/python"

# check_detect <name> <cli exit> <detect_attempt> <step exit> <runs of the cli> <output lines...>: runs the detect step
# with a CLI that exits <cli exit> and compares the step's exit, how many times it ran the CLI and its outputs; the
# step's own output must contain $want_error when it is set.
check_detect() {
  local name="$1" cli="$2" attempt="$3" want_exit="$4" want_runs="$5" out step_exit got want
  shift 5
  count=$((count + 1))
  : > "$work/detect-output"
  : > "$work/detect-calls"
  if out=$(env PATH="$work/detect-bin:$PATH" FAKE_DETECT_STATUS="$cli" FAKE_DETECT_CALLS="$work/detect-calls" \
    DETECT_ATTEMPT="$attempt" MAX_DETECT_ATTEMPTS="$max_attempts" GITHUB_OUTPUT="$work/detect-output" \
    RUNNER_TEMP="$work" GH_TOKEN="$github_token" bash -e -o pipefail -c "$detect_step" 2>&1 < /dev/null); then
    step_exit=0
  else
    step_exit=$?
  fi
  got=$(printf 'exit=%s\nruns=%s\n' "$step_exit" "$(wc -l < "$work/detect-calls" | tr -d ' ')"; cat "$work/detect-output")
  want=$(printf 'exit=%s\nruns=%s\n' "$want_exit" "$want_runs"; if [ $# -gt 0 ]; then printf '%s\n' "$@"; fi)
  if [ "$got" != "$want" ]; then
    failures=$((failures + 1))
    echo "FAIL ${name}"
    diff <(printf '%s\n' "$want") <(printf '%s\n' "$got") | sed 's/^/     /' || :
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     | /'
  elif [ -n "${want_error:-}" ] && [[ "$out" != *"$want_error"* ]]; then
    failures=$((failures + 1))
    echo "FAIL ${name}: expected the output to contain \"${want_error}\""
    printf '%s\n' "$out" | tail -n 4 | sed 's/^/     | /'
  else
    echo "ok   ${name}"
  fi
  want_error=""
}

want_error="::warning::detect could not connect on attempt 1 of ${max_attempts}"
check_detect "detect that could not connect on attempt 1 passes and hands attempt 2 to retry" 3 1 0 1 "next_attempt=2"
check_detect "detect that could not connect on attempt $((max_attempts - 1)) hands the last attempt to retry" \
  3 $((max_attempts - 1)) 0 1 "next_attempt=${max_attempts}"
check_detect "detect that could not connect on the last attempt fails with the CLI's exit" 3 "$max_attempts" 3 1
check_detect "detect that fails otherwise fails without a next attempt" 1 1 1 1
check_detect "detect that succeeds keeps the CLI's outputs and has no next attempt" 0 1 0 1 "pin_update=false" "bump=false"
for attempt in 0 x 1.5 ''; do
  want_error="detect_attempt must be a positive integer, not '${attempt}'"
  check_detect "detect_attempt '${attempt}' fails before the CLI runs" 3 "$attempt" 1 0
done

count=$((count + 1))
printf '{"next_run": 100, "next_pr": 10, "runs": [], "prs": [], "calls": [], "dispatches": []}\n' > "$work/state.json"
if out=$(env PATH="$work/bin:$PATH" FAKE_STATE="$work/state.json" FAKE_REMOTE="$work/remote.git" \
  FAKE_APP_TOKEN="$app_token" FAKE_GITHUB_TOKEN="$github_token" FAKE_APP_SLUG="$app_slug" FAKE_BOT_ID="$bot_id" \
  GH_TOKEN="$github_token" NEXT_ATTEMPT=2 GITHUB_REPOSITORY=o/r bash -e -o pipefail -c "$retry_step" 2>&1 < /dev/null) \
  && [ "$(jq -r '[.dispatches[] | "\(.workflow)@\(.ref) \(.inputs | join(",")) by \(.token)"] | join("; ")' "$work/state.json")" \
    = "$(basename "$workflow_path")@master detect_attempt=2 by ${github_token}" ]; then
  echo "ok   retry dispatches this workflow on master with the next attempt, with GITHUB_TOKEN"
else
  failures=$((failures + 1))
  echo "FAIL retry must dispatch this workflow on master with the next attempt, with GITHUB_TOKEN"
  printf '%s\n' "$out" | tail -n 4 | sed 's/^/     | /'
  jq -c .dispatches "$work/state.json" | sed 's/^/     /'
fi

count=$((count + 1))
detect_env='.jobs.detect.steps[] | select(.id == "detect") | .env'
retry_env='.jobs.retry.steps[] | select(.name == "Dispatch the Next Attempt 🔁") | .env'
if [ "$(yq '.on.workflow_dispatch.inputs.detect_attempt | [.type, .default] | to_json(0)' "$workflow_path")" = '["number",1]' ] \
  && [ "$(yq "${detect_env}.DETECT_ATTEMPT" "$workflow_path")" = '${{ inputs.detect_attempt || 1 }}' ] \
  && [ "$(yq '.jobs.detect.outputs.next_attempt' "$workflow_path")" = '${{ steps.detect.outputs.next_attempt }}' ] \
  && [ "$(yq '.permissions | to_json(0)' "$workflow_path")" = '{"contents":"read"}' ] \
  && [ "$(yq '.jobs.detect.permissions' "$workflow_path")" = null ] \
  && [ "$(yq '.jobs.retry.needs' "$workflow_path")" = detect ] \
  && [ "$(yq '.jobs.retry.if' "$workflow_path")" = "needs.detect.outputs.next_attempt != ''" ] \
  && [ "$(yq '.jobs.retry.permissions | to_json(0)' "$workflow_path")" = '{"actions":"write"}' ] \
  && [ "$(yq '[.jobs.retry.steps[] | select(has("uses"))] | length' "$workflow_path")" = 0 ] \
  && [ "$(yq "${retry_env}.GH_TOKEN" "$workflow_path")" = '${{ github.token }}' ] \
  && [ "$(yq "${retry_env}.NEXT_ATTEMPT" "$workflow_path")" = '${{ needs.detect.outputs.next_attempt }}' ]; then
  echo "ok   wiring: detect reads detect_attempt and reads only contents, and retry runs no action, after detect hands it the next attempt, with actions write only"
else
  failures=$((failures + 1))
  echo "FAIL wiring: the input detect_attempt, detect's attempt, outputs or permissions, or retry's condition, permissions, steps or env changed"
fi

# The sleep stub returns at once. With LAND_SIGNAL set, its first call stands for a wait the job is cancelled during: it
# sends SIGINT to the land shell alone, SIGTERM 7.5 seconds later and SIGKILL 2.5 seconds after that, each only while
# the land shell is still running, then kills whatever is left of the process group run_land started land in, and it
# lasts longer than all of that. The killer is in that group itself, so the group's id and the land shell's pid stay
# unused by any other process for as long as it signals them.
cat > "$work/bin/sleep" <<'EOF'
#!/usr/bin/env bash
if [ -n "${LAND_SIGNAL:-}" ] && mkdir "$LAND_DIR/signalled" 2> /dev/null; then
  exec > /dev/null 2>&1
  pid=$(cat "$LAND_DIR/pid")
  (
    kill -INT "$pid"
    for step in 7.5:TERM 2.5:KILL; do
      /bin/sleep "${step%%:*}"
      kill -0 "$pid" 2> /dev/null || break
      kill -"${step#*:}" "$pid"
    done
    kill -KILL -- -"$pid"
  ) &
  exec /bin/sleep 12
fi
exit 0
EOF
chmod +x "$work/bin/sleep"
if ! sed --version > /dev/null 2>&1; then
  cat > "$work/bin/sed" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = -i ]; then shift; exec /usr/bin/sed -i '' "$@"; fi
exec /usr/bin/sed "$@"
EOF
  chmod +x "$work/bin/sed"
fi

# run_land <pin_update> <bump> <release_sha> [VAR=value...]: one land step on a fresh state of the remote.
run_land() {
  local pin_update="$1" bump="$2" release_sha="$3" status
  shift 3
  git -C "$work/remote.git" update-ref refs/heads/master "$base"
  git -C "$work/remote.git" for-each-ref --format='%(refname)' refs/heads/ffmpeg-watch \
    | while read -r ref; do git -C "$work/remote.git" update-ref -d "$ref"; done
  printf '{"next_run": 100, "next_pr": 10, "runs": [], "prs": %s, "calls": [], "dispatches": [], "polls": {}}\n' \
    "${SEED_PRS:-[]}" > "$work/state.json"
  rm -rf "$work/land" "$work/land-process"
  mkdir "$work/land-process"
  git clone -q --depth 1 "file://$work/remote.git" "$work/land" 2>/dev/null
  if out=$(cd "$work/land" && env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
    "$@" PATH="$work/bin:$PATH" LAND_DIR="$work/land-process" FAKE_STATE="$work/state.json" \
    FAKE_REMOTE="$work/remote.git" FAKE_APP_TOKEN="$app_token" FAKE_GITHUB_TOKEN="$github_token" \
    FAKE_APP_SLUG="$app_slug" FAKE_BOT_ID="$bot_id" GH_TOKEN="$github_token" APP_TOKEN="$app_token" \
    APP_SLUG="$app_slug" PIN_UPDATE="$pin_update" BUMP="$bump" SERIES=9.0 VERSION=1.4.1 NEXT_VERSION=1.4.2 \
    RELEASE_SHA="$release_sha" CANDIDATE="$work/candidate.json" GITHUB_SERVER_URL=https://github.com \
    GITHUB_REPOSITORY=o/r GITHUB_RUN_ID=7 GITHUB_RUN_ATTEMPT=1 RUNNER_DEBUG='' \
    python3 -c 'import os, sys; os.setpgid(0, 0); os.execvp(sys.argv[1], sys.argv[1:])' \
    bash -c 'echo "$$" > "$LAND_DIR/pid"; exec bash -e -o pipefail -c "$1"' land "$land" 2>&1 < /dev/null); then
    status=0
  else
    status=$?
  fi
  land_out="$out"
  land_status="$status"
}

# summary: what landed and how, as one line per fact.
summary() {
  echo "exit=$( [ "$land_status" -eq 0 ] && echo 0 || echo nonzero )"
  echo "master=$(git -C "$work/remote.git" log --first-parent --reverse --format=%s "$base..master" \
    | awk 'BEGIN { ORS = "" } { print (NR > 1 ? " | " : "") $0 }')"
  echo "version=$(git -C "$work/remote.git" show "master:$version_file" | sed -n 's/^__version__ = "\(.*\)"$/\1/p')"
  echo "pin=$(git -C "$work/remote.git" show "master:$pin_file" | jq -r .series)"
  jq -r '.prs[] | select(.number > 10) | "pr \(.head | sub("-7-1$"; "")) \(.state) opened_by=\(.opened_by) merged_by=\(.merged_by)"' \
    "$work/state.json"
  jq -r '"dispatches=\([.dispatches[] | "\(.workflow)@\(.ref) \(.inputs | join(",")) by \(.token)"] | join("; "))"' \
    "$work/state.json"
  local merge
  merge=$(jq -r '[.prs[] | select(.merge != null)] | last | .merge // empty' "$work/state.json")
  if [ -n "$merge" ]; then
    echo "push_ci_on_last_merge=$(jq -r --arg m "$merge" '[.runs[] | select(.workflow == "ci.yaml" and .event == "push" and .sha == $m)] | length' "$work/state.json")"
  fi
  jq -r '.prs[] | select(.number > 10) | .head' "$work/state.json" | while read -r head; do
    if git -C "$work/remote.git" rev-parse -q --verify "refs/heads/$head" > /dev/null; then
      echo "author $(git -C "$work/remote.git" log -1 --format='%an <%ae>' "refs/heads/$head")"
    fi
  done
}

# check <name> <expected summary lines...>: compares the summary of the last run_land with the lines, and with the
# error text in $want_error when it is set.
check() {
  local name="$1" got want
  shift
  count=$((count + 1))
  got=$(summary)
  want=$(printf '%s\n' "$@")
  if [ "$got" != "$want" ]; then
    failures=$((failures + 1))
    echo "FAIL ${name}"
    diff <(printf '%s\n' "$want") <(printf '%s\n' "$got") | sed 's/^/     /' || :
    printf '%s\n' "$land_out" | tail -n 4 | sed 's/^/     | /'
  elif [ -n "${want_error:-}" ] && [[ "$land_out" != *"$want_error"* ]]; then
    failures=$((failures + 1))
    echo "FAIL ${name}: expected the output to contain \"${want_error}\""
    printf '%s\n' "$land_out" | tail -n 4 | sed 's/^/     | /'
  else
    echo "ok   ${name}"
  fi
  want_error=""
}

author="author ${app_slug}[bot] <${bot_id}+${app_slug}[bot]@users.noreply.github.com>"

run_land true true ""
check "a new pin and a bump land with the App's token, and the bump's merge starts CI on master" \
  "exit=0" \
  "master=Merge pull request #11 from o/ffmpeg-watch/pin-9.0-7-1 | Merge pull request #12 from o/ffmpeg-watch/bump-v1.4.2-7-1" \
  "version=1.4.2" "pin=9.0" \
  "pr ffmpeg-watch/pin-9.0 MERGED opened_by=${app_token} merged_by=${app_token}" \
  "pr ffmpeg-watch/bump-v1.4.2 MERGED opened_by=${app_token} merged_by=${app_token}" \
  "dispatches=" "push_ci_on_last_merge=1" "$author" "$author"

run_land false true ""
check "a bump left by an earlier run lands on its own" \
  "exit=0" "master=Merge pull request #11 from o/ffmpeg-watch/bump-v1.4.2-7-1" "version=1.4.2" "pin=8.1" \
  "pr ffmpeg-watch/bump-v1.4.2 MERGED opened_by=${app_token} merged_by=${app_token}" \
  "dispatches=" "push_ci_on_last_merge=1" "$author"

run_land false false "$base"
check "a version without its tag dispatches tag-release.yml with release_sha" \
  "exit=0" "master=" "version=1.4.1" "pin=8.1" \
  "dispatches=tag-release.yml@master sha=${base} by ${github_token}"

want_error="pull requests from an earlier run are still open: #5"
SEED_PRS='[{"number": 5, "head": "ffmpeg-watch/pin-9.0-6-1", "state": "OPEN", "opened_by": "x", "merged_by": null, "merge": null}]' \
  run_land true true ""
check "an open pull request from an earlier run stops land before it pushes" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" "dispatches="
if git -C "$work/remote.git" for-each-ref --format='%(refname)' refs/heads/ffmpeg-watch | grep -q .; then
  failures=$((failures + 1))
  echo "FAIL an open pull request from an earlier run stops land before it pushes: a branch was pushed"
fi

want_error="run 103 failure"
run_land true true "" FAIL_RUN=workflow-checks.yml
check "a failing required run stops land before the merge" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"

want_error="no pull_request_target run of workflow-checks.yml on"
run_land true true "" NO_TARGET_RUN=1
check "a pull request without its pull_request_target run stops land" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"

# codecov/project reports after the runs, so the merge waits for it: here on the fifth poll.
run_land true true "" CODECOV_AFTER=5
check "a required check that reports after the runs is waited for before the merge" \
  "exit=0" \
  "master=Merge pull request #11 from o/ffmpeg-watch/pin-9.0-7-1 | Merge pull request #12 from o/ffmpeg-watch/bump-v1.4.2-7-1" \
  "version=1.4.2" "pin=9.0" \
  "pr ffmpeg-watch/pin-9.0 MERGED opened_by=${app_token} merged_by=${app_token}" \
  "pr ffmpeg-watch/bump-v1.4.2 MERGED opened_by=${app_token} merged_by=${app_token}" \
  "dispatches=" "push_ci_on_last_merge=1" "$author" "$author"
count=$((count + 1))
merges=$(jq -r '[.calls[] | select(.args[0] == "pr" and .args[1] == "merge")
  | "\(.args | index("--auto") != null) \(.args | index("--match-head-commit") != null) \(.token)"] | unique | join(";")' \
  "$work/state.json")
if [ "$merges" = "true true ${app_token}" ]; then
  echo "ok   every merge is an auto-merge of the head commit with the App's token"
else
  failures=$((failures + 1))
  echo "FAIL every merge must be an auto-merge of the head commit with the App's token: ${merges}"
fi

# late_success <name>: once land has stopped, codecov/project passes on #11; nothing may merge it, since land turned
# its auto-merge off before stopping.
late_success() {
  local state
  count=$((count + 1))
  state=$(env PATH="$work/bin:$PATH" FAKE_STATE="$work/state.json" FAKE_REMOTE="$work/remote.git" \
    FAKE_APP_TOKEN="$app_token" FAKE_GITHUB_TOKEN="$github_token" FAKE_APP_SLUG="$app_slug" FAKE_BOT_ID="$bot_id" \
    GH_TOKEN="$github_token" CODECOV=success CODECOV_AFTER=0 gh pr view 11 --json state --jq .state)
  if [ "$state" = OPEN ] && [ "$(git -C "$work/remote.git" rev-parse master)" = "$base" ] \
    && [ "$(jq -r '.prs[] | select(.number == 11) | .auto' "$work/state.json")" = null ]; then
    echo "ok   $1: a check passing after land stopped merges nothing"
  else
    failures=$((failures + 1))
    echo "FAIL $1: a check passing after land stopped must merge nothing (state=${state})"
  fi
}

want_error="a required check of #11 failed"
run_land true true "" CODECOV=failure
check "a required check that fails after the runs stops land before the merge" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"
late_success "a required check that fails after the runs"

want_error="#11 did not merge within 10 minutes of its runs passing"
run_land true true "" CODECOV=never
check "a pull request that does not merge stops land after its wait" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"
late_success "a pull request that does not merge in time"

# Once the auto-merge is enabled, whatever else ends land turns it off on the way out.
want_error="HTTP 502"
run_land true true "" CODECOV=never VIEW_FAIL=1
check "a poll that fails after the auto-merge is enabled stops land" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"
late_success "a poll that fails after the auto-merge is enabled"

want_error="HTTP 502"
run_land true true "" CODECOV=never AUTO_FAIL=1
check "a call that enables the auto-merge and then fails stops land" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"
late_success "a call that enables the auto-merge and then fails"

run_land true true "" CODECOV=never LAND_SIGNAL=1
check "a job cancelled while land waits stops land" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"
count=$((count + 1))
if [ "$land_status" -eq 130 ]; then
  echo "ok   a job cancelled while land waits: land ends at the SIGINT, before the SIGTERM"
else
  failures=$((failures + 1))
  echo "FAIL a job cancelled while land waits: land must end at the SIGINT, before the SIGTERM (status=${land_status})"
fi
late_success "a job cancelled while land waits"

want_error="could not turn the auto-merge of #11 off, so it can still merge"
run_land true true "" CODECOV=failure DISABLE_FAIL=1
check "an auto-merge that cannot be turned off is reported" \
  "exit=nonzero" "master=" "version=1.4.1" "pin=8.1" \
  "pr ffmpeg-watch/pin-9.0 OPEN opened_by=${app_token} merged_by=null" "dispatches=" "$author"

count=$((count + 1))
wired() {
  [ "$(yq ".jobs.land$1" "$workflow_path")" = "$2" ]
}
token_step='.steps[] | select(.id == "app-token")'
land_env='.steps[] | select(.name == "Land 🛬") | .env'
if wired "${token_step} | .uses | test(\"^actions/create-github-app-token@[0-9a-f]{40}\$\")" true \
  && wired "${token_step} | .with[\"client-id\"]" '${{ vars.FFMPEG_WATCH_APP_CLIENT_ID }}' \
  && wired "${token_step} | .with[\"private-key\"]" '${{ secrets.FFMPEG_WATCH_APP_PRIVATE_KEY }}' \
  && wired "${token_step} | .with | to_entries | map(select(.key | test(\"^permission-\"))) | from_entries | to_json(0)" \
    '{"permission-contents":"write","permission-pull-requests":"write"}' \
  && wired '.steps[] | select(.uses | test("^actions/checkout@")) | .with.token' '${{ steps.app-token.outputs.token }}' \
  && wired "${land_env}.APP_TOKEN" '${{ steps.app-token.outputs.token }}' \
  && wired "${land_env}.APP_SLUG" '${{ steps.app-token.outputs.app-slug }}' \
  && wired "${land_env}.GH_TOKEN" '${{ github.token }}' \
  && wired '.permissions | to_entries | map(select(.value == "write")) | map(.key) | to_json(0)' '["actions"]'; then
  echo "ok   wiring: the App's token has contents and pull requests write only, the checkout and land use it, and GITHUB_TOKEN writes nothing but dispatches"
else
  failures=$((failures + 1))
  echo "FAIL wiring: the App's token step, its permissions, the token the checkout and land use, or the job's permissions changed"
fi

echo "${count} cases, ${failures} failed"
if [ "$failures" -ne 0 ]; then
  exit 1
fi
