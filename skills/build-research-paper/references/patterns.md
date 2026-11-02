# Build patterns

Reverse-engineered from two real papers:
- **LaTeX-first** → a 24-page journal-grade paper
- **Markdown-first** → a policy-analysis report

## The two workflows

### 1. Hand-authored LaTeX (the default)

Signature: single-file `main.tex` (~2000 lines), plain `article` class, plus a
familiar package stack:

```latex
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage[hidelinks]{hyperref}
\usepackage[margin=1in]{geometry}
\usepackage{algorithm,algpseudocode}
\usepackage{subcaption}
\usepackage{xcolor}
\usepackage{natbib}
\usepackage{multirow}
\usepackage{cleveref}
\usepackage{doi}
```

Theorem envs are declared once at the top; `\Cref` is used everywhere for
cross-refs; `\citep{...}` for parenthetical cites; figures use `[t]` with an
`\includegraphics` at `\textwidth` or `0.85\textwidth`.

**Build:** `tectonic main.tex`. That's the whole build command.

**Why tectonic:** self-contained, auto-fetches packages, no `.aux/.bbl/.blg`
dance. The old pattern (`pdflatex → bibtex → pdflatex → pdflatex`) is what
every project keeps re-discovering not to bother with.

### 2. Markdown → pandoc → LaTeX (escape hatch)

Signature: `report.md` as source, `knowledge/header.tex` injected as
LaTeX preamble via `pandoc --include-in-header=header.tex`, pandoc handles
markdown→LaTeX and citations via `--citeproc`. Used for RFI-style responses
and shorter technical notes where full LaTeX ceremony isn't warranted.

The `header.tex` extracted from the Markdown-first pattern includes a custom title-page
`\renewcommand{\maketitle}` — that's project-specific chrome, not skill-worthy.

## The figure pipeline (both workflows)

From the bundled `generate_figures.py`:

- Publication style set once at the top (`font.family='serif'`, `dpi=300`,
  `savefig.bbox='tight'`, `text.usetex=False` unless the whole team has LaTeX
  installed inside matplotlib).
- Every figure has a named function.
- **Dual output**: every figure saved as both `.pdf` (vector, for LaTeX) and
  `.png` (raster, for previews). The `save()` helper in the template does this.
- Data lives in `experiments/*.json` — figures are pure functions of that data,
  so revisions never desync.
- Version subdirs (`figures/v5/`) once you start iterating; keeps old builds
  reproducible.

## The revision-cycle scaffolding

That project iterated through five revisions. The reusable convention:

```
report/
├── feedback_v1.md              ← referee report, verbatim
├── revision_checklist.md       ← triage into categories A–E
├── response_to_referee_v1.md   ← point-by-point response letter
├── v1_polish_log.md            ← what changed in this revision
├── v1_edit_plan.md             ← plan for the next round
├── main.v1.bak.tex             ← snapshot of the pre-revision manuscript
└── RESUBMISSION_PACKAGE.md     ← cover doc for the submission bundle
```

Categories in `revision_checklist.md`:

- **A: Theoretical framing** — propositions, theorems, formal statements
- **B: Empirical comparators** — additional baselines, ablations
- **C: Claim discipline** — hedging, scope, evidence-matched wording
- **D: Scope & positioning** — which contributions to keep vs cut
- **E: Writing quality** — clarity, notation, figure captions

`response_to_referee.md` uses a table:

```markdown
| # | Referee point (verbatim excerpt) | Manuscript section | Response |
|---|---|---|---|
| A1 | "H2: clarify mathematical status…" | §3.2 | Added Proposition 1 (§3.2.1). |
```

## Anti-patterns (things projects keep re-discovering)

- ❌ **`pdflatex + bibtex + pdflatex + pdflatex`** — use `tectonic`.
- ❌ **`.eps` figures** — arxiv accepts PDF/PNG, PDF is better for vector.
- ❌ **`\input{}` into many `.tex` files** — arxiv prefers one flat `main.tex`.
- ❌ **Hardcoded numbers in figures** — always drive from experiment JSON.
- ❌ **Hyperref loaded after cleveref** — cleveref must load AFTER hyperref (it patches hyperref's internals). doi also loads after hyperref. Order: `natbib` → `hyperref` → `cleveref` → `doi`.
- ❌ **Fabricating a table row that doesn't match the JSON** — real referee
  bait. Regenerate all tables from data every build.
- ❌ **Hand-editing figure PDFs** — always regenerate; version the script.
