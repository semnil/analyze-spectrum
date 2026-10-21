#!/usr/bin/env bash
# Runs the land step of ffmpeg-watch.yml against a fixture repository (a bare remote and a shallow clone) and a fake gh
# that answers by the token a call carries: a pull request the App's token opens gets successful pull_request runs of
# CI and dependabot-auto-merge.yml and a pull_request_target run of workflow-checks.yml, one GITHUB_TOKEN opens gets
# pull_request runs that wait for an approval and no pull_request_target run, a merge needs the three required checks,
# and a merge with the App's token starts a push run of CI on master. It asserts what lands on master, which token
# opened and merged each pull request, and what land dispatched.
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
        if a in ("--exit-status", "--compact", "--required", "--merge"):
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
                             "merged_by": None, "merge": None})
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
        emit({"number": pr["number"]}, opts)
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
        if not checks_pass(state, git("rev-parse", f"refs/heads/{pr['head']}")):
            print(f"no checks reported on the '{pr['head']}' branch", file=sys.stderr)
            status = 1
    elif (group, verb) == ("pr", "merge"):
        pr = next(p for p in state["prs"] if str(p["number"]) == rest[0])
        head = git("rev-parse", f"refs/heads/{pr['head']}")
        master = git("rev-parse", "refs/heads/master")
        if head != opts.get("--match-head-commit") or git("merge-base", master, head) != master \
                or not checks_pass(state, head):
            print("the base branch policy prohibits the merge", file=sys.stderr)
            status = 1
        else:
            merge = git("commit-tree", f"{head}^{{tree}}", "-p", master, "-p", head,
                        "-m", f"Merge pull request #{pr['number']} from o/{pr['head']}")
            git("update-ref", "refs/heads/master", merge)
            pr.update(state="MERGED", merged_by=token, merge=merge)
            if token == APP:
                add_run(state, "ci.yaml", "push", merge, "success")
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

mkdir -p "$work/bin"
printf '#!/usr/bin/env bash\nexec python3 -I %q "$@"\n' "$work/gh.py" > "$work/bin/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$work/bin/sleep"
chmod +x "$work/bin/gh" "$work/bin/sleep"
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
  printf '{"next_run": 100, "next_pr": 10, "runs": [], "prs": %s, "calls": [], "dispatches": []}\n' \
    "${SEED_PRS:-[]}" > "$work/state.json"
  rm -rf "$work/land"
  git clone -q --depth 1 "file://$work/remote.git" "$work/land" 2>/dev/null
  if out=$(cd "$work/land" && env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
    "$@" PATH="$work/bin:$PATH" FAKE_STATE="$work/state.json" \
    FAKE_REMOTE="$work/remote.git" FAKE_APP_TOKEN="$app_token" FAKE_GITHUB_TOKEN="$github_token" \
    FAKE_APP_SLUG="$app_slug" FAKE_BOT_ID="$bot_id" GH_TOKEN="$github_token" APP_TOKEN="$app_token" \
    APP_SLUG="$app_slug" PIN_UPDATE="$pin_update" BUMP="$bump" SERIES=9.0 VERSION=1.4.1 NEXT_VERSION=1.4.2 \
    RELEASE_SHA="$release_sha" CANDIDATE="$work/candidate.json" GITHUB_SERVER_URL=https://github.com \
    GITHUB_REPOSITORY=o/r GITHUB_RUN_ID=7 GITHUB_RUN_ATTEMPT=1 RUNNER_DEBUG='' \
    bash -e -o pipefail -c "$land" 2>&1 < /dev/null); then status=0; else status=$?; fi
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
