# Long-running campaign status

**On-demand by default.** Ask "status", "progress", or "is it still running?"
in chat. The companion and skill take **one fresh read-only snapshot** of the
existing campaign and give a short answer in chat. No timer, background service,
continuous polling, or change to the campaign's supervision is required.

## On-demand chat check

1. Use the campaign's **original recorded native path** and run/study IDs
  directly, whether in project results or a legacy external store. Ask which
  campaign only when the intended one is ambiguous. Do not initialize a results
  folder, use the results helper's `run` wrapper, or create wrapper logs merely
  to observe existing work. Do not assume a campaign moved because results
  routing changed.
2. Read existing `status` / `study-status` results. Before saying it is currently
  running, cross-check the exact run against a live container or executor and
  a bounded solver-log tail. A saved `running` label or old heartbeat alone
  does not establish process liveness.
3. Reply with one or two lines or a compact table: checked time, finalized/total
  runs, current case, observed iteration or solver time, output freshness,
  and any verified failures or pending design decision. State when status is
  unavailable or liveness is uncertain; do not infer a hang or acceptance.
4. Stop after the snapshot. A status question authorizes observation only, not
  starting, resuming, retrying, cancelling/recovering, changing supervision,
  extending budgets, or editing frozen inputs/signed evidence. Do not keep
  the chat active or add an observer just to answer the question. No new report,
  reassessment, finalization or generated analysis is part of a status-only check.

Periodic monitoring is **opt-in**. The previously added terminal observer stays
an optional diagnostic, not a requirement for manual chat updates. This
instruction-only default change does not start, stop, or modify an existing
campaign or observer.

## Chat delivery is host-dependent

The following limitations concern requested automatic updates, not the manual
status check above. Asking in chat supplies the opportunity to answer normally.

Agent instructions are not a background timer. During a blocking tool call,
after a chat turn yields, or while a parent waits for a subagent, the host may
not allow a new chat message. A delegated agent's private output is not
necessarily visible; the parent owns user-facing progress. Use supported host
progress events or timed notifications where available, without hot-polling
tools or issuing sleep commands to hold the conversation open.

If the host cannot deliver timed chat updates, disclose that limitation at the
start and identify the visible terminal/log instead. **Terminal stdout does
not send proactive chat messages.** Exact one-minute background chat delivery
requires host scheduler/notification integration; this entry does not install
or qualify such an integration, modify Discovery, or add a new MCP server.

## Passive terminal heartbeat

The standard-library-only [watcher](../scripts/watch_campaign.py) can observe an
**existing** private run-store directory without importing the physics package,
calling a container engine, reading signing keys, or changing any run. It prints
and flushes an initial line, then a line every **60 seconds** by default. It can
be attached to an already running campaign without editing its registered
coordinator, inputs, contracts or decision logic.

Run from the acquired entry, using the existing campaign's actual runs path:

```powershell
$py = "$env:LOCALAPPDATA\DiscoveryPhysics\venv\Scripts\python.exe"
$runs = '<original-recorded-absolute-runs-path>' # Existing project or legacy store.
& $py .\scripts\watch_campaign.py --runs-root $runs --label 'Channel study' `
    --interval 60 --max-seconds 18000
```

The path above is illustrative; the observer refuses a nonexistent directory.
It does not discover, start, resume or authorize a campaign. The helper is
part of the acquired runtime entry, **not** bundled with the standalone copied
skill. Do not assume it exists in a target project's scripts directory.

For a single immediate snapshot, add `--once`. To retain stdout, use a separate
destination under the explicit user project's marked results/logs directory,
outside the observed signed run directories. Retaining a new log is a separately
requested output, not part of a status-only question. If the legacy campaign
has no project results container, select the user project explicitly and
initialize one only for that authorized new output, leaving the original native
store and key unchanged. Never write into project `agents`, acquired contribution
source, a signed case or an evidence tree. The observer remains alive
only while its process/terminal is alive; closing it does not stop the solver.

The monitor's default five-hour observation cap bounds only its own lifetime,
not the run budgets or operator queue timeout. At the cap it reports that
observation stopped and leaves the campaign untouched. It also stops when every
observed run has a structurally valid finalization-file hint; this is **not**
proof of a final study decision, verified acceptance, or a winning design.
It never cancels or extends a solve and never retries a failed run.

## Interpret the line correctly

- State files, finalization files and bounded solver-log tails are **unverified
  operational hints**. Scientific claims still require the installed CLI's
  signed verification, proposal, finalization and study-assessment workflow.
- A steady-state iteration is not physical elapsed time. The watcher labels
  steady iterations separately and makes no percent-complete or ETA claim.
- Before the solver log exists, report startup/meshing or unavailable progress,
  not a missing-executable failure. Output files can be temporarily partial
  while being written; partial/mismatched records are unknown, not completion.
- Old log timestamps are reported as stale/uncertain after two intervals.
  Neither an unchanged log nor a recorded `running` state establishes process
  liveness, a hang, or numerical health. Investigate separately if needed.
- New cases added to the same store can change its count. Point the watcher at
  a campaign-specific store so unrelated historical runs are not mixed in.
- Stopping the observer, a reporting error, or a host notification delay must
  not alter resource policy, thresholds, signed records, or retry authorization.

The [synthetic tests](../tests/test_watch_campaign.py) use a fake clock to
exercise minute cadence without real-time sleeps or CFD. They cover partial
files, startup without a log, stale output, finalization hints, bounded tails,
and read-only behavior. Terminal cadence tests are not evidence that an inactive
chat receives timer-driven updates.

New campaigns initialize their project results before authoring/freezing and
record source/native paths and IDs in the manifest; private runtime app data,
keys, resource policy and shared slots stay separate. See
[results routing](configuration.md) and [explicit report delivery](reporting.md).
Neither changes the one-snapshot, original-path status procedure above.