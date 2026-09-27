# The ratification gate

**This document is authoritative for what the gate checks.** If
`scripts/check_ratification_gate.py` and this file ever disagree, that is a
defect in the script. The requirement it enforces is stated in
[`spec/README.md`](../spec/README.md) § "How ratification works here" and in
[`spec/decision-records/0004-target-spec-ratification.md`](../spec/decision-records/0004-target-spec-ratification.md)
§ "The binding process"; **the documented mechanism and the enforced
mechanism must name the same thing**, which is why the release signal is
described identically in all three places.

## Why it exists

The two-key (`RATIFY-KEY`) mechanism was described in prose and enforced by
nothing.
[`spec/decision-records/0006-two-key-ratification-never-ran.md`](../spec/decision-records/0006-two-key-ratification-never-ran.md)
records what that cost: PR #29 flipped five `Status:` lines to `Ratified` and
merged with **zero** pull-request reviews of any kind — 4 minutes 37 seconds
after a sweep posted a correct, specific, numbered stand-down on the PR
itself. Two things independently failed to stop it:

1. **`loom:auto-merge-ok` is an override, not a precondition.** Both
   `spec/README.md` and DR 0004 named that label as the second key-holder's
   release signal, but in the surrounding pipeline it *releases a merge-risk
   hold*. A PR with no hold merges on the normal path, so the label's
   **absence** blocked nothing. The release signal is now named as what the
   mechanism always said the act was: **the two reviews themselves**.
2. **The stand-down was a PR comment.** Nothing mechanical reads a comment,
   and a later pipeline pass re-entering at Merge had no durable state saying
   a previous pass had deferred. A failing status check is durable, survives
   re-entry, and cannot be re-derived away by a fresh read of the same diff.

Adding more prose could not fix this: the prose was already correct and
already specific. The fix has to be something a merge can fail on.

## What counts as a flip

The gate acts on a **flip**, not on "a change to `spec/`". A flip is a file
matching `spec/**/*.md` whose `Status:` line asserts ratification in the PR's
head tree but did **not** in the merge-base tree.

* A file's status assertion is read from **start-of-line `Status:`** lines
  only. Markdown emphasis (`**`, `_`, backticks) is stripped and the value is
  cut at the first delimiter (`—`, `--`, `(`, `.`, `,`, `;`, `:`), so
  `Status: **Ratified 2026-09-27** — two RATIFY-KEY reviews on PR #99` reads
  as `ratified`, and `Status: **PROPOSED — not ratified.**` reads as
  `proposed`. A quoted line (`> Status: …`, the append-only preserved-verbatim
  blocks DR 0004 and DR 0006 use) is not a start-of-line `Status:` line and is
  ignored, by design.
* A value asserts ratification when it leads with `ratified` or `in force`
  and is not negated (`not ratified`, `never ratified`, `unratified`).
* Because the comparison is **base state vs. head state per file**, these are
  *not* flips and are not gated: editing a `Proposed` record, reflowing or
  amending prose on an already-`Ratified` line, and reconciling a line *away*
  from `Ratified` (DR 0006's own repair shape). A **new file born `Ratified`**
  *is* a flip.
* A `Status: Ratified` line outside `spec/` is out of scope.

The documented status vocabulary is `DRAFT` / `Proposed` / `Ratified` /
`Recorded` (`spec/README.md` § "Status vocabulary"). The gate's self-test
asserts that every real `Status:` line under `spec/` still parses into that
vocabulary, so a new, undocumented status word is a test failure rather than
a silent hole.

## What the gate requires when a flip is present

All of the following, evaluated against the carrying PR's
`/pulls/<N>/reviews`:

| # | Requirement |
|---|---|
| 1 | At least one `<!-- RATIFY-KEY: ee … -->` marker **and** at least one `<!-- RATIFY-KEY: market … -->` marker, each in a non-`DISMISSED` review, each well-formed per its skill's § "Output format" grammar — `verdict=`, `block=`, `reviewer=`, `date=` all present, none left as the skill's `<angle-bracket>` placeholder, `date=` ISO-8601. |
| 2 | A **releasing verdict** on each: `ee` must be `approve`; `market` must be `competitive` or `adequate-for-catalog`. `request-changes` / `uncompetitive` / `escalate` is a review that happened, not a release. |
| 3 | The two markers' `reviewer=` values **distinct** (case-insensitively) — two keys means two holders. |
| 4 | **Neither key attributable to the PR author**: neither the review's forge login nor the marker's `reviewer=` value may equal the PR author's login. |
| 5 | The same diff must not modify the gate's own files (`scripts/check_ratification_gate.py`, `scripts/test_check_ratification_gate.py`, `.github/workflows/ratification-gate.yml`). A PR may not ratify and rewrite its own gate in one move. |

Marker grammar comes from the installed key skills, unchanged:

```
<!-- RATIFY-KEY: ee     verdict=<approve|request-changes> block=<repo>#<PR-or-issue> reviewer=<agent-id> date=<ISO-8601> -->
<!-- RATIFY-KEY: market verdict=<competitive|adequate-for-catalog|uncompetitive|escalate> block=<repo>#<PR-or-issue> reviewer=<agent-id> date=<ISO-8601> -->
```

Only **reviews** count. A PR *comment* naming `RATIFY-KEY` is not a key — DR
0006 § "One false positive to expect" names the two comments in this repo's
history that mention the marker while explicitly disclaiming being one.

## What the gate deliberately does not decide

DR 0006 § "Routed, not decided" routes one question to an operator: whether
two agent sessions sharing a single forge identity satisfy *"neither held by
… the design's author"*, or whether **distinct forge principals** are
required. The gate does not pre-empt that ruling. It enforces distinct
`reviewer=` values and non-authorship, and it **prints each key's forge
login** so the record shows it; when both keys share a login it emits a
`NOTE` naming the open question. Once an operator rules that distinct
principals are required, `--require-distinct-principals` (and the same flag
in the workflow step) turns that `NOTE` into a failure with no code change.

## Where it runs

| Surface | Command | Role |
|---|---|---|
| `.github/workflows/ratification-gate.yml`, job **`two-key gate (spec Status flips)`** | `check_ratification_gate.py --pr <N>` | **Authoritative.** Triggers on `pull_request` *and* `pull_request_review` — a key review arrives after the last push, so without the review trigger the gate would never see the reviews that release the PR. |
| `npm run lint` → `npm run check:ci` | `test_check_ratification_gate.py`, then `check_ratification_gate.py --base-ref origin/main` | Composable local/CI copy of the same assertion, plus the gate's own self-test. |

The local invocation auto-discovers the PR for the current branch via `gh pr
view`. With a flip present and **no** resolvable PR context (no PR yet, no
`gh` auth) it prints `SKIP` and exits 0 — the unverifiable case is left to
the workflow job, which always has PR context. It never passes a flip it
*could* evaluate.

## Making it blocking

Branch protection is an operator-only surface — an agent token gets `403
Resource not accessible by integration` on
`repos/:owner/:repo/branches/main/protection`. To make the gate block rather
than merely report, an operator adds the job to `main`'s required status
checks:

```bash
gh api -X PATCH repos/2AMLogic/sg13cmos5l-protocol-emulator/branches/main/protection \
  -F 'required_status_checks[strict]=true' \
  -f 'required_status_checks[checks][][context]=two-key gate (spec Status flips)'
```

Until that is done the gate is a **red check on the PR** plus a failing
`npm run check:ci` — neither of which Judge approves past or Champion merges
past — rather than a forge-level block. That is strictly stronger than the
prose-only state it replaces, and the residual gap is named here rather than
assumed away.

## Known limits, stated rather than hidden

* **It is a textual gate.** A PR that asserts ratification in wording the
  vocabulary does not contain (`Status: **In effect**`) is not detected. The
  mitigation is that the vocabulary is documented and self-tested, not that
  the gate is exhaustive.
* **It does not verify a verdict's substance.** Whether an EE-key `approve`
  was *earned* is the key skill's rubric's job; the gate checks that the act
  happened, by whom, and that it released.
* **A required check gates the merge, not the repository's history.** A
  direct push to `main` bypassing a PR is outside its reach; that is what
  branch protection's "require a pull request" setting is for.
