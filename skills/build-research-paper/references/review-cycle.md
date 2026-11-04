# The revision cycle — file conventions & workflow

Adopted from the actual v1→v5 revision history of a journal-grade paper.

## File naming

For revision round N:

| File | Purpose |
|------|---------|
| `feedback_v{N}.md` | Referee report or internal reviewer report, verbatim. |
| `feedback_v{N}_round{K}.md` | If a single round triggers multiple internal re-reviews. |
| `revision_checklist.md` | Triage of every referee point into categories A–E. |
| `response_to_referee_v{N}.md` | Point-by-point response letter. |
| `v{N}_edit_plan.md` | Plan for the round (before you touch `main.tex`). |
| `v{N}_polish_log.md` | Change log for the round (as you edit). |
| `main.v{N}.bak.tex` | Snapshot of `main.tex` at the START of round N (safety net). |
| `RESUBMISSION_PACKAGE.md` | Cover doc for the submission bundle. |

## Triage categories

Use these five buckets in `revision_checklist.md`:

- **A. Theoretical framing** — propositions, theorems, formal statements,
  assumptions, invariance properties. Highest cost, highest reviewer impact.
- **B. Empirical comparators** — additional baselines, ablations, sensitivity
  studies, larger problem sizes. Requires re-running experiments.
- **C. Claim discipline** — abstract/intro/conclusion wording, hedging,
  matching evidence scope, deleting overclaims. Cheap, high-signal.
- **D. Scope & positioning** — decide which contributions stay in vs get cut
  or moved to appendix. Sometimes the reviewer is asking for a different paper.
- **E. Writing quality** — notation consistency, figure captions, section
  ordering, typos, `\Cref` vs `\ref`, bibliography formatting.

## Response letter template

Every entry follows this shape:

```markdown
### Referee comment A1

> "H2: Clarify mathematical status of ρ₂g predictor; conditions under which
> it reliably surrogates solve-phase savings."

**Response.** We added Proposition 1 (§3.2.1) that formalizes the ρ₂g
surrogate under assumption (A1) …

**Location of change.** `main.tex` §3.2.1, lines 412–458.
Diff summary: +47 lines, 0 deletions.
```

## Suggested loop

1. Save `feedback_v{N}.md` verbatim. Don't paraphrase.
2. Read carefully; write `revision_checklist.md` with every point triaged.
3. Snapshot: `cp main.tex main.v{N-1}.bak.tex` (safety net).
4. Draft `v{N}_edit_plan.md` — grouped by category, ordered by cost.
5. Execute the plan, editing `main.tex`. Log each change to
   `v{N}_polish_log.md` as you go (running log, not summary at the end).
6. Draft `response_to_referee_v{N}.md` in parallel with editing — cite the
   exact section/line numbers as you land each change.
7. Build: `tectonic main.tex`. Run `bash check.sh` for undefined refs and
   missing figures.
8. Read the whole PDF end-to-end. Look for orphaned claims, broken cross-refs,
   captions that no longer match figures.
9. Update `RESUBMISSION_PACKAGE.md` with the changed files and summary.
10. Zip: `zip -r resubmission_v{N}.zip main.tex references.bib figures/ response_to_referee_v{N}.md`.

## When the referee is fundamentally right

If categories A or D dominate — i.e., the referee is asking for different
theorems or a different scope — **write `v{N}_edit_plan.md` first and
sanity-check it with the user before touching `main.tex`**. Reworking the
scaffolding after 500 lines of edits is expensive.
