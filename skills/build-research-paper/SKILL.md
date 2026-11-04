---
name: build-research-paper
description: |
  Cross-domain / Scientific writing and publication — Build
  beautifully-formatted, arxiv-ready research paper PDFs from a mix of
  hand-authored LaTeX and/or markdown + PNG figures, using `tectonic`
  (default) or `pandoc` (escape hatch). Captures the reusable pattern that
  research projects keep re-discovering: `report/main.tex` + `references.bib`
  + `generate_figures.py` + iterative feedback/response scaffolding, all
  buildable with a single command. WHEN: write a research paper, arxiv
  submission, prepub, generate PDF from markdown, LaTeX paper, build main.tex,
  journal manuscript, referee revision, response to referee, resubmission
  package, publication-quality figures, matplotlib publication style, tectonic
  build, pandoc build, generate arxiv-ready PDF, bibliography from BibTeX.
license: MIT
metadata:
  author: Tim Meyers
  version: "2"
  category: "Cross-domain"
  subfield: "Scientific writing and publication"
---

# build-research-paper — Research Paper Builder Skill

Turn a project's results + figures + notes into a **publication-quality,
arxiv-ready PDF**. This skill captures a pattern re-discovered across many
research projects, distilled into two build paths: a LaTeX-first path
(`tectonic`, the default) and a Markdown-first path (`pandoc`, the escape
hatch).

## First: a paper is a paper

Read this before touching `main.tex`, and re-read it before declaring done.
Everything below is tooling. **This is the point.**

**A paper is a document a human being reads, front to back, to learn
something they did not know.** That is the whole definition. Not a compliance
artifact. Not a results dump. Not a receipt proving work occurred. Not a
serialization of a task tree.

It follows that:

- **The paper has a thesis** — a story the data is telling. If you cannot say
  in one sentence what this paper found, it is not ready, regardless of how
  many sections exist. Write that sentence down before you write anything else.
- **The reader is a domain expert, not a validator.** They came for the
  finding. They will grant that you did the work carefully if you *show* them
  it holds; they will not read twenty pages of proof that it does before being
  told what "it" is.
- **Figures carry the argument.** A picture shows shape; a table files values.
  A data-analysis paper with no charts has not been written, only assembled.
- **Rigor is the warrant, not the subject.** Provenance, validation, failure
  logs and reproduction tests make the story *trustable*. They are not the
  story. When they migrate to the front, the paper has inverted itself.
- **Nothing in the body may be unresolvable to an outsider.** Internal task
  IDs, ticket numbers, commit SHAs and pipeline filenames mean nothing to a
  reader. If a sentence only parses inside your workspace, it is not prose.
- **A paper is finished when someone has read it**, not when the checks pass.
  Build the PDF, open it, and read it like a stranger would.

The characteristic agent failure mode is producing something that satisfies
every stated requirement and is still not a paper: technically correct,
exhaustively sourced, verifiably reproducible, and unreadable. **Requirements
are a floor, not a specification.** No list of criteria adds up to a document
worth reading — that judgment is yours, and you have to exercise it.

If you find yourself optimizing a metric about the paper rather than the
paper, stop and open the PDF.

## When to use

Trigger this skill whenever the user is working on a research report or
manuscript in a Discovery-style repo and asks to:

- "write / build / compile the paper"
- "produce an arxiv-ready PDF"
- "generate figures for the paper"
- "respond to referee feedback / do a revision pass"
- "package for submission"
- Starts from scratch: "we need to write up these results"

If the repo already has a `report/main.tex`, **prefer editing it** over
regenerating from scratch. If it has no report directory yet, scaffold one
with `new-paper.sh`.

## Locating this skill's scripts and templates

This skill can be installed as a personal skill, a project skill, or as part
of a plugin, so never hardcode its location. Resolve it once per session and
reuse `$SKILL_DIR`:

```bash
SKILL_DIR=$(dirname "$(find ~/.copilot/skills ~/.copilot/installed-plugins \
                            ~/.agents/skills .github/skills .claude/skills \
                            .agents/skills \
                            -name new-paper.sh -path '*build-research-paper*' \
                            2>/dev/null | head -1)")/..
SKILL_DIR=$(cd "$SKILL_DIR" && pwd)
echo "$SKILL_DIR"
```

If `$SKILL_DIR` does not resolve, tell the user the skill payload could not be
located and stop. The scripts themselves self-locate their sibling
`templates/`, so they can be invoked from anywhere once found.

The bundled wrappers require Bash. They run directly on macOS and Linux; on
Windows, use WSL or Git Bash. Before the first build, run
`bash "$SKILL_DIR"/scripts/check-deps.sh` for platform-specific installation
guidance. The Markdown path also requires `pandoc`; the default LaTeX path does
not.

## The default pattern (hand-authored LaTeX + tectonic)

This is the workflow that produced the reference paper above. It is the
default because it gives the best equation, theorem-environment, and figure
placement control, and arxiv expects LaTeX sources.

```
<repo>/report/
├── main.tex              # THE manuscript. Hand-authored / agent-edited.
├── references.bib        # BibTeX. Target 40+ entries for a full paper.
├── generate_figures.py   # matplotlib -> figures/*.pdf and figures/*.png
├── figures/              # Both .pdf (vector, embedded in PDF) AND .png (for
│                         #   markdown previews / README). Version subdirs
│                         #   (figures/v5/) when you iterate.
├── feedback_v{N}.md      # Referee report(s), one per revision round.
├── response_to_referee_v{N}.md   # Point-by-point response letter.
├── revision_checklist.md # Triage: A/B/C/D/E categories from feedback.
├── v{N}_polish_log.md    # What changed in each polish pass.
├── v{N}_edit_plan.md     # Plan for the next revision round.
└── RESUBMISSION_PACKAGE.md   # Cover doc that describes the submission.
```

### Build command (default)

```bash
cd <repo>/report
tectonic main.tex          # single command, self-contained, no *.aux junk
```

Or use the wrapper: `bash "$SKILL_DIR"/scripts/build.sh <report-dir>`.

Tectonic auto-fetches missing LaTeX packages, so the first build on a new
machine takes 30–60s; subsequent builds are fast. **Do not use pdflatex +
bibtex + pdflatex + pdflatex** — that's what everyone re-discovers not to do.

### Sanity checks after every build

Run `bash "$SKILL_DIR"/scripts/check.sh <report-dir>` (or do these manually):

1. `grep -n "??" main.pdf.log` — undefined references
2. `grep -n "Warning" main.log | grep -iE "citation|reference"` — missing cites
3. `grep -c "\\\\cite" main.tex` vs `grep -c "@" references.bib` — cite/bib coverage
4. Every `\includegraphics{figures/...}` file exists on disk
5. **The paper contains figures at all** — check 4 passes trivially at zero
6. Any section named "appendix" actually follows an `\appendix` command
7. `main.pdf` opens; page count matches expectations

### Then open the PDF and read it

**Do not skip this, and do not substitute metrics for it.** In the
a project post-mortem, days were spent verifying page counts, citation
coverage and reproduction tests without anyone opening `main.pdf`. Both
defects that eventually mattered — an appendix printed as body section 2, and
zero figures — were visible immediately to the first person who scrolled it.

Read the built PDF front to back and ask:

- Following it from page one, **do I find the story**, or an audit trail?
- **Do the figures carry the argument**, or is every claim a table?
- Does anything in the body reference something a reader cannot resolve?
- Is the machinery at the back where it belongs?

The audience test: **a domain reader is reading this, not a validator.**
Metrics describe the deliverable; they are not the deliverable.

## The escape hatch (markdown + pandoc)

Use this when the user hasn't written any LaTeX and wants a fast draft, or
for shorter pieces (technical notes, RFI responses — the pattern used in
a Markdown-first project directory).

```
<repo>/report/
├── manuscript.md         # Standard markdown with $math$, ![figs](path), refs
├── header.tex            # LaTeX preamble that pandoc will inject
├── references.bib
├── figures/*.png         # PNG is fine here; pandoc will embed
└── build-md.sh
```

Build: `bash "$SKILL_DIR"/scripts/build-md.sh <report-dir>`.

Under the hood: `pandoc manuscript.md -o main.pdf --pdf-engine=tectonic
--include-in-header=header.tex --citeproc --bibliography=references.bib`.

## Starter templates

All under `"$SKILL_DIR"/templates/`:

- `main.tex` — arxiv-ready single-column article skeleton with the exact
  package stack used by the bundled `main.tex` (natbib, booktabs,
  algorithm/algpseudocode, cleveref, hyperref[hidelinks], theorem envs).
- `references.bib` — empty starter with a comment block explaining
  BibTeX key conventions.
- `header.tex` — the pandoc preamble variant (from the Markdown-first pattern).
- `generate_figures.py` — matplotlib publication style + PDF+PNG dual output.

Copy these into the target repo with
`bash "$SKILL_DIR"/scripts/new-paper.sh <target-repo>`, then edit — never
symlink, because each project needs to diverge.

## Figure discipline

The single most re-discovered lesson:

0. **THE PAPER MUST ACTUALLY HAVE FIGURES.** Before the rules below can help
   you, figures have to exist. Rules 1–4 are all *universally quantified* —
   "every figure has a script", "every figure is saved as both formats" — and
   **every one of them is vacuously true of a paper with zero figures.**
   A reviewed 47-page data-analysis paper passed a
   requirement reading "every published figure is emitted by committed
   pipeline code" while containing **no charts at all**, and shipped with 55
   tables instead. A human found it in ten seconds of scrolling; no automated
   gate ever could, because nothing was false.

   > **General rule, applies far beyond this skill: any "every X must Y"
   > criterion is satisfied by producing no X. Pair every universally
   > quantified check with an existence check.** `scripts/check.sh` now
   > counts figures for exactly this reason.

   A contributing cause was lexical: that project used "figure" to mean
   *number* throughout ("headline figures", "prevalence figures"), so the
   visual sense was never tested. When a project overloads the word, say
   **chart / plot / visualization** in requirements so the check is unambiguous.

   Sizing guidance: a full empirical paper wants **6+ figures**. If you are
   below 4, ask what the reader should *see*. **Tables do not count** — a
   table files data, a figure shows shape. Where a chart renders a
   distribution better than a table, *replace* the table; do not print both.
   Forty tables in one section is a filing cabinet, not an argument.

1. **Every figure has a `.py` script** that regenerates it deterministically
   from experimental data (results JSON/CSV). Never hand-edit figure files.
2. **Every figure is saved as BOTH `.pdf` (vector) AND `.png` (raster)** in
   the same directory. `main.tex` uses `.pdf`; markdown previews use `.png`.
3. **Set publication style once** at the top of `generate_figures.py`
   (see template — font.family='serif', dpi=300, savefig.bbox='tight').
4. **Version the figures directory** (`figures/v3/`, `figures/v5/`) when
   revising, so old paper builds stay reproducible.
5. **Place figures in the body, beside the claim they support.** Never
   warehouse them in an appendix. Captions state N and, where more than one
   denominator is in play, which one applies.
6. **A figure must never contradict its table.** If both survive, have the
   verification script check the figure's source values against the same
   artifact the table reads, so a chart cannot silently drift.

## Document order and register

Mechanically correct papers fail here, and only a human reader notices.

### Default paper shape

Use this as the starting skeleton for any new paper unless the user's
prompt calls for something different (a short technical note, a specific
journal template, a workshop 4-pager, etc.). It reflects the reading order
that works for the empirical Discovery-style papers this skill exists to
support.

```
1. Abstract
2. Introduction
3. Background and Related Work
4. <A section (with subsections) describing the work we did>
5. <A section (with subsections) describing the findings>
6. Limitations and/or Future Work                    [optional]
7. Acknowledgements                                  [optional]
8. Conclusion
9. References  (a.k.a. Bibliography or Citations)
10. Appendix 1 - <Title>
    Appendix 2 - <Title>
    …                                                [zero or more]
```

Notes on the shape:

- **Sections 4 and 5 are placeholders** — name them for *this* paper's
  contribution, not literally "The Work" and "The Findings". "Methods",
  "System", "Approach", "Experiments", "Evaluation", "Results", and
  domain-specific titles are all fair game. What matters is that the
  work-we-did section precedes the findings section, and both precede
  the conclusion.
- **Every appendix is titled `Appendix N - <Title>`** (e.g., "Appendix 1
  - Provenance and Data Sources", "Appendix 2 - Validation History").
  Issue `\appendix` before the first one so LaTeX letters them properly
  (A, B, C…) — the `N` in the label is the reader-facing ordinal, not
  necessarily the LaTeX section number.
- Provenance, validation history, failure logs, exhaustive method
  detail, and long tables belong in appendices — not in the body.
- Prefer the singular "Conclusion" over "Conclusions" unless there
  really are several distinct concluding claims.
- **This is guidance, not a straitjacket.** A more specific prompt
  instruction (e.g., "follow the NeurIPS template", "this is a
  two-page RFI response", "combine background into introduction")
  overrules the default shape. When in doubt, ask.

### Order sections for a reader, not for the author

Assembling `\input{}` lines in the order tasks finished is how a 20-page
process/validation appendix ended up as **body section 2 of 5**, ahead of
every finding. Reading order is:

```
abstract → introduction → background → work → FINDINGS → discussion
        → conclusion → references → \appendix → provenance, validation, logs
```

- Issue `\appendix` before the back-matter `\input{}`s. Without it LaTeX
  renders them as numbered body sections — the file name says "appendix" but
  the PDF says "2". `check.sh` flags this.
- Consider putting findings **before** an evidence-appraisal section: a reader
  wants the story before an assessment of the evidence beneath it.
- Methodology in the body should be short and readable; the exhaustive version
  belongs in the appendix.

**Purge internal identifiers from body prose.** Task IDs (`DX-17`), ticket
numbers, commit SHAs, pipeline artifact names and `.py` filenames are
unresolvable to anyone outside the workspace. Replace the handle with the
thing itself, cross-referencing the appendix where provenance matters — but
**never silently delete a reference that carried meaning**; the replacement
must still get the reader there by a route they can follow. Internal IDs are
correct *inside* the provenance appendix. Stable public identifiers (dataset
record IDs, DOIs, accession numbers) stay.

**Reproducibility is the paper's warrant, not its subject.** Sourcing and
validation make the narrative trustable; they are not the narrative. When
process material crowds out findings, the paper has inverted itself.

**Use American English spelling and usage throughout.** This is a hard rule
for every artifact this skill produces — `main.tex`, `manuscript.md`,
figure captions, `references.bib` comments, response letters, checklists,
polish logs, and the `RESUBMISSION_PACKAGE.md` cover doc. Prefer `-ize` over
`-ise` (organize, analyze, optimize, characterize, summarize), `-or` over
`-our` (color, behavior, favor, labor), `-er` over `-re` (center, fiber,
liter), and American variants elsewhere (gray, program, catalog, defense,
license as a noun, toward, while, among, learned, spelled). Preserve
British spellings only inside proper nouns, direct quotations, and cited
titles in `references.bib` — never "fix" a quote or a published title.
When editing pre-existing prose from a user or referee, silently normalize
their spellings to American English in the manuscript unless the user
explicitly requests otherwise.

## Iterative revision pattern

When the user shares referee feedback, run this loop:

1. Save the referee report verbatim as `feedback_v{N}.md`.
2. Create `revision_checklist.md` triaging every point into categories
   (A: theory, B: empirics, C: claim discipline, D: scope, E: writing).
3. Draft `response_to_referee_v{N}.md` with a point-by-point table:
   `| # | Referee point | Section | Response |`.
4. Edit `main.tex` addressing each item; log what changed in
   `v{N}_polish_log.md`.
5. Build. Re-check. Update `RESUBMISSION_PACKAGE.md`.

Keep real examples of all five artifacts in your own `report/` directory —
read them for style before drafting the next revision.

## arXiv submission checklist

Before declaring "arxiv-ready":

- [ ] Single self-contained `main.tex` (no `\input{}` chains beyond the bib)
- [ ] All figures are PDF or PNG (no EPS, no proprietary formats)
- [ ] **The paper HAS figures** — 6+ for a full empirical paper; tables don't count
- [ ] `generate_figures.py` committed, and it emits every published figure
- [ ] Sections in reading order; `\appendix` issued before back-matter
- [ ] No internal task IDs, ticket numbers or commit SHAs in body prose
- [ ] American English spelling and usage throughout (see "Document order and register")
- [ ] `references.bib` present; every `\cite{...}` resolves
- [ ] No undefined references / `??` in the PDF
- [ ] `\usepackage{hyperref}` loaded **before** cleveref/doi (cleveref patches hyperref, so it must load after; doi also depends on hyperref)
- [ ] Title, single-line author with affiliation footnote, abstract present
- [ ] Line length ≤ 100 chars in `.tex` (arxiv's tar preserves lines)
- [ ] Build produces PDF ≤ 10 MB (arxiv soft limit)
- [ ] **Someone opened the PDF and read it end to end**
- [ ] Zip: `zip -r submission.zip main.tex references.bib figures/`

See `references/arxiv-submission.md` for the full checklist.

## Files this skill provides

```
build-research-paper/
├── SKILL.md                          # this file
├── templates/
│   ├── main.tex                      # LaTeX skeleton
│   ├── references.bib                # empty starter
│   ├── header.tex                    # pandoc preamble
│   └── generate_figures.py           # matplotlib pub style
├── scripts/
│   ├── check-deps.sh                 # dependency and platform preflight
│   ├── new-paper.sh                  # scaffold report/ dir
│   ├── build.sh                      # tectonic build (default)
│   ├── build-md.sh                   # pandoc build (escape hatch)
│   └── check.sh                      # post-build sanity checks
└── references/
    ├── patterns.md                   # deeper notes from both build patterns
    ├── review-cycle.md               # feedback_vN convention details
    └── arxiv-submission.md           # arxiv rules & full pre-submit checklist
```

## Installing from the Microsoft Discovery catalog

Install the skill directly from the public Microsoft Discovery repository:

```bash
gh skill install microsoft/discovery build-research-paper
```

After installation, use it whenever building or revising `report/main.tex`,
generating publication figures, or packaging a submission.
