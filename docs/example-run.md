# A worked example: smoke-002

A real run, executed against a fresh scratch directory on 2026-04-22.
Two tasks. Deliberately trivial code. Eight Claude Code sessions, nine
minutes wall clock, zero retries. The point is not the software — the
software is a three-line Python function and its sibling — but to
show what actually happens between "operator submits a `batch.yaml`"
and "Telegram pings that the batch is complete." For Phase 1 status
and design rationale, see the [README](../README.md). The full
artifacts excerpted below live under
`docs/reference/smoke-002-artifacts/`.

## The batch

From `docs/reference/smoke-002-artifacts/batch.yaml`:

```yaml
batch_id: smoke-002
budgets:
  wall_clock_hours: 2.0
  max_tokens: 3000000
  max_dollars: 20.0
  max_iterations: 2
  session_timeout_minutes: 30
tasks:
- id: task-0001
  title: Add greet() function to hello module
  acceptance_criteria:
  - 'Python module at hello.py (project root) exports a function `greet(name: str) -> str`.'
  - Calling `greet('World')` returns exactly the string `'Hello, World!'`.
  # ...
  depends_on: []
- id: task-0002
  title: Add farewell() function to goodbye module, mirroring hello's structure
  acceptance_criteria:
  - 'Python module at goodbye.py (project root) exports a function `farewell(name: str) -> str`.'
  - The function's structure, type annotations, docstring style, and formatting must
    match `hello.greet` — this is a deliberate stylistic mirror so the two modules
    read as siblings.
  # ...
  depends_on:
  - task-0001
```

Two design choices set up the rest of the run. Task 2's `depends_on:
[task-0001]` forces the supervisor to hold task 2 until task 1 reaches
a terminal state, and routes task 1's completed artifacts to task 2's
architect as context. And the "structural mirror" line in task 2's
acceptance criteria is the lever — it makes the architect's job
*read task 1's source*, not invent a sibling from scratch. The
budgets are deliberately loose; on Max, `max_dollars` is a safety net
rather than a primary gate (see
[`deployment.md`](deployment.md#budget-interpretation-for-max-vs-api)).

## The run timeline

Reconstructed from `docs/reference/smoke-002-artifacts/audit.jsonl`:

| # | Task      | Role        | Model              | Duration | End state |
| - | --------- | ----------- | ------------------ | -------- | --------- |
| 1 | task-0001 | architect   | claude-opus-4-7    | 53.8 s   | clean     |
| 2 | task-0001 | implementer | claude-sonnet-4-6  | 44.8 s   | clean     |
| 3 | task-0001 | testwriter  | claude-sonnet-4-6  | 87.9 s   | clean     |
| 4 | task-0001 | critic      | claude-opus-4-7    | 81.1 s   | clean     |
| 5 | task-0002 | architect   | claude-opus-4-7    | 75.0 s   | clean     |
| 6 | task-0002 | implementer | claude-sonnet-4-6  | 50.3 s   | clean     |
| 7 | task-0002 | testwriter  | claude-sonnet-4-6  | 95.8 s   | clean     |
| 8 | task-0002 | critic      | claude-opus-4-7    | 73.4 s   | clean     |

First session launch: `19:40:06Z`. `batch-complete` audit event:
`19:49:29Z`. Wall clock: 9 minutes, 22 seconds. Sum of session
durations: 562 seconds — sessions are sequential and supervisor
overhead is in the tens of milliseconds, so wall clock and total
session time agree to within a couple of seconds.

The two interesting transitions are the ones the table doesn't show.
After session 4, the critic accepted task 1; the supervisor wrote a
`software-complete → done` history entry (no `session_id` — it's the
supervisor doing the bookkeeping), then walked the task list, found
task 2 newly eligible, and launched session 5 without operator input.
After session 8, every task was terminal; the supervisor's
`_batch_is_complete` check fired, flipped `state.yaml.phase` to
`complete`, wrote a `batch-complete` audit record, and dispatched a
Telegram FYI:

```
{"component": "telegram-dispatcher", "kind": "batch-complete",
 "event": "telegram.send.ok", "level": "info",
 "ts": "2026-04-22T19:49:29.822329Z"}
```

Eight sessions launched, eight ended `clean`, every `attempt_count`
is `0`. The full retry-and-classification machinery sat idle.

## What the architect produced

Task 2's spec is the cross-task-coordination test. The architect did
not get a fresh prompt restating task 1's choices; it had to read
task 1's on-disk artifacts and base its spec on them.

From `docs/reference/smoke-002-artifacts/task-0002/spec.md`:

> ## Problem statement
>
> This task adds a sibling module to the `hello.py` seeded by
> `task-0001` ... The `goodbye` module must be a structural mirror of
> `hello` so the two read as a pair — same file shape, same function
> shape, same docstring style, same test layout. **This exercises the
> supervisor's inter-task handoff: the architect must read the
> upstream task's completed artifacts and base its spec on them.**

The architect made the mirror operational in the approach notes:

> - **Read `hello.py` and `test_hello.py` first.** Both files are
>   committed by task-0001 and are the canonical template ... confirm
>   the only differences are: filename, module name, function name
>   (`greet` → `farewell`), greeting word (`Hello` → `Goodbye`), and
>   the docstring noun (`greeting` → `farewell`).
> - **Do not "improve" task-0001's choices.** If you notice something
>   you would have done differently in `hello.py` / `test_hello.py`,
>   leave it alone — those files are out of scope. The point of this
>   task is the mirror, not a cleanup pass.

The "do not improve" line is the one I'd flag. The architect noticed
(correctly) that there are choices in `hello.py` worth questioning —
module-level vs. per-function imports, for instance — and explicitly
forbade the implementer from re-litigating them. That's the kind of
judgment that makes a multi-task batch read as coherent rather than
churn-y.

The locked-implementation block goes a step further:

> - The body **must** be `return f"Goodbye, {name}!"` ... the only
>   single-expression formulation that passes all three whitespace
>   cases simultaneously...
> - Final file should be exactly 3 lines: the `def` line, the
>   docstring line, the `return` line — matching `hello.py`
>   line-for-line.

The downstream implementer has very little room to drift, by
construction.

## What the critic produced

The critic ran the test suite twice — once with the exact command the
spec calls for, once as a broader sanity check — and walked every
acceptance criterion.

From `docs/reference/smoke-002-artifacts/task-0002/review.md`:

> ## Test execution
>
> Command: `python -m pytest test_hello.py test_goodbye.py -v -W error`
>
> - **Passed:** 6 / **Failed:** 0 / **Skipped:** 0
>
> Command: `python -m pytest -v` (full suite from project root)
>
> - **Passed:** 18 / **Failed:** 0 / **Skipped:** 0
>
> Both runs match the numbers reported in `tests.md`. Zero warnings
> on either run.

This dual-verification pattern matters. The 6-test run is what AC-11
literally asks for; the 18-test run is the critic's broader quality
check (it picks up the testwriter-authored `*_acceptance.py` files
and task 1's previously-shipped tests). Both numbers are stated, both
match `tests.md`, and the distinction between *what the AC requires*
and *what's in the suite* is preserved.

The per-criterion walkthrough is real verification, not a
checkmark-fest:

> - AC-3, AC-4, AC-5: `test_farewell_normal_name`,
>   `test_farewell_empty_string`, `test_farewell_whitespace_padded`
>   all pass — body `return f"Goodbye, {name}!"` is the locked
>   formulation called for in spec.md:64.
> - AC-6: `farewell.__annotations__ == {'name': str, 'return': str}`
>   verified by acceptance tests.
> - AC-8: `goodbye.py` is exactly 3 lines, no imports, no
>   module-level side effects — diff against `hello.py` shows only
>   the function name, greeting word, and docstring noun changed.

`mutmut` wasn't installed in the smoke environment. Rather than fail
the review, the critic explained why mutation testing is benign here
(a 3-line pure function whose entire behaviour is pinned by
exact-match assertions on three carefully chosen inputs) and accepted.

Verdict: `accept`. No findings. (Task 1's review carried two
informational `[nit]` findings — one on the mutation skip, one on a
test using a hand-rolled source-line filter rather than AST
inspection — and accepted anyway. The critic exercises judgment rather
than rubber-stamping.)

## What landed on disk

The entire production output of the run, in its entirety:

```python
# hello.py
def greet(name: str) -> str:
    """Return a greeting addressed to name."""
    return f"Hello, {name}!"
```

```python
# goodbye.py
def farewell(name: str) -> str:
    """Return a farewell addressed to name."""
    return f"Goodbye, {name}!"
```

```python
# test_hello.py
from hello import greet


def test_greet_normal_name():
    assert greet('World') == 'Hello, World!'


def test_greet_empty_string():
    assert greet('') == 'Hello, !'


def test_greet_whitespace_padded():
    assert greet('  Alice  ') == 'Hello,   Alice  !'
```

`test_goodbye.py` is `test_hello.py` with `hello → goodbye`,
`greet → farewell`, and `Hello → Goodbye`. Diff-able with no
surprises, exactly as the spec required. The testwriter additionally
produced `test_hello_acceptance.py` and `test_goodbye_acceptance.py`
covering annotations, docstring shape, line count, and
module-level-side-effect absence; those live in the same artifacts
directory.

The software is trivial. The orchestration that produced two trivial
modules with no operator intervention is the point.

## The budget

`huragok status`, run live against the preserved scratch directory:

```
huragok — smoke-002 (complete)
═══════════════════════════════════════════════════════════════
Elapsed:        0h 09m / 2h 00m    (8%)
Tokens:         36.5K / 3.00M    (1%)
  input:        388
  output:       36.1K
  cache read:   6.53M
  cache write:  702.6K
Dollars:        $15.76 / $20.00    (79%)  (table est., not reconciled)
Iterations:     0 / 2
Sessions:       8 launched, 8 clean, 0 retry

Tasks:          2 total · 2 done · 0 in-flight · 0 pending · 0 blocked

Pending notifications:  (none)
```

Two patterns to internalise:

**Cache tokens dominate real-token usage.** 36.5K input+output vs.
~7.2M cache reads+writes is roughly a 200× ratio. Claude Code
aggressively caches system prompts, agent definition files, and
project context across sessions; on a small task most per-session
cost is cache reads of the same context being primed for each new
subprocess. The cache sub-lines exist so this is visible — the main
`Tokens:` percentage uses input+output only (matching the budget's
enforcement aggregate), so the displayed percent will look
implausibly low until you read the breakdown.

**`$15.76 of $20.00` looks alarming and isn't.** That figure is the
*theoretical* API cost computed from `orchestrator/pricing.yaml`
applied to every token the run touched, including cache reads. On
Claude Max — what this run used — the daemon does not consume API
credits; it consumes session-window quota, and ~$15 of theoretical
cost is a small fraction of a Max session window. The CLI's
`(table est., not reconciled)` annotation is the daemon flagging that
the figure has not been crosschecked against the Anthropic Cost API.
On Max, the budgets that bite are `wall_clock_hours` and
`max_iterations`; treat `max_dollars` as a safety net. See
[`deployment.md`](deployment.md#budget-interpretation-for-max-vs-api).

## What this run did NOT test

Nine clean minutes is a happy-path validation, not a stress test. The
following all sat idle and remain unverified at this scale:

- **The UI gate (ADR-0001 D6).** Both tasks were `foundational: false`
  with no UI surface. The human-in-the-loop checkpoint never armed.
- **Iteration cycles.** Every session ended `clean` on the first
  attempt. The reject-and-retry path, the `iterate` reply verb, and
  the per-retry-family attempt cap were all bypassed.
- **Rate-limit handling.** The run sat well under the 5-hour Max
  session window. The pre-flight rate-limit gate had nothing to defer.
- **Multi-hour batches.** Nine minutes does not exercise budget
  pacing, dispatcher reachability degradation, or Telegram cursor
  persistence across restarts.
- **Realistic complexity.** Three-line Python functions don't
  approach the per-agent context window or surface the kind of
  architectural ambiguity that real ADR-driven work generates.

This run proves the pipeline works on a happy path. It does not prove
Huragok is ready for production workloads. That validation is the
work of Phase 2 and beyond.

## Where next

- Set up your own install: [`deployment.md`](deployment.md).
- Design and run your own smoke test: [`smoke-tests.md`](smoke-tests.md).
- System charter:
  [`adr/ADR-0001-huragok-orchestration.md`](adr/ADR-0001-huragok-orchestration.md).
