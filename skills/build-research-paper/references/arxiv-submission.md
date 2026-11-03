# arXiv submission checklist

Compliance notes for submitting to https://arxiv.org.

## Source requirements

arXiv wants LaTeX **sources**, not just a PDF. Prepare a tarball/zip with:

- `main.tex` — single file preferred. If you `\input{other.tex}`, include those.
- `references.bib` — the BibTeX source.
- `main.bbl` — pre-compiled bibliography (recommended; arXiv doesn't run
  BibTeX by default). Generate by running the build once locally:
  `tectonic --keep-intermediates main.tex` produces `main.bbl`.
- `figures/` — all `.pdf` and `.png` (and any `.jpg`) figures used.
- **Do NOT** include: `.aux`, `.log`, `.out`, `.toc`, `.synctex.gz`, `.DS_Store`.

## Format constraints

| Rule | Detail |
|------|--------|
| Document class | `article`, `revtex`, `elsarticle`, or a journal template. Plain `article` is fine, and is what the bundled `main.tex` uses. |
| Figures | `.pdf`, `.png`, or `.jpg`. No `.eps` (arXiv will convert but it's fragile). No proprietary formats. |
| Encoding | UTF-8. Declare with `\usepackage[utf8]{inputenc}` and `\usepackage[T1]{fontenc}`. |
| Hyperref | Use `\usepackage[hidelinks]{hyperref}` to avoid colored borders in print. Load BEFORE cleveref and doi (both patch hyperref). |
| Fonts | Standard LaTeX fonts. Avoid `\usepackage{fontspec}` / XeLaTeX-only features unless you know arXiv will use XeLaTeX for your submission. |
| Size | PDF ≤ 10 MB is comfortable. Hard cap ≈ 50 MB. Compress figures aggressively before pushing over 10 MB. |
| Line length | Keep `.tex` lines ≤ 100 chars. arXiv's tarball keeps line endings, so long lines look bad in the source viewer. |

## Pre-flight checklist

Before hitting "Submit" on arXiv:

- [ ] `tectonic main.tex` builds cleanly (no fatal errors in `main.log`)
- [ ] `bash scripts/check.sh` reports zero undefined refs, zero missing figures
- [ ] Every `\cite{...}` resolves; every `.bib` entry is cited (or intentionally not)
- [ ] Title, abstract, authors, affiliations present on page 1
- [ ] `\thanks{}` used for author emails/affiliations (not `\footnote`)
- [ ] Correct license selected (arXiv default = arXiv nonexclusive; consider CC-BY 4.0)
- [ ] arXiv **primary category** selected (e.g., `cs.LG`, `math.NA`, `physics.comp-ph`)
- [ ] Cross-listed categories if applicable
- [ ] MSC/ACM classification codes if you use them (optional)
- [ ] All coauthors have agreed to the submission
- [ ] The version pushed to arXiv **matches** the version reviewed by coauthors
- [ ] Tarball contents inspected: `tar tzf submission.tar.gz`

## Making the tarball

From the report directory:

```bash
# Ensure main.bbl exists (so arXiv doesn't need to run BibTeX)
tectonic --keep-intermediates main.tex

# Pack. Include the pre-compiled bbl.
tar czf submission.tar.gz \
  main.tex \
  main.bbl \
  references.bib \
  figures/*.pdf figures/*.png

# Inspect
tar tzf submission.tar.gz
ls -lh submission.tar.gz
```

## After acceptance / withdrawal

- To replace a version: log into arXiv, use "Replace" (not "Submit new"). This
  keeps the same arXiv ID (`arXiv:2601.01234`) with `v2`, `v3` suffixes.
- Withdrawal is possible but discouraged; the metadata remains public.
- Version diffs on arXiv are minimal; provide a "changes vs v1" note in the
  comments field if the revision is substantial.

## Related metadata to include on the arXiv submission form

- **Comments field**: page count, figure count, one-line "what's new in v2".
- **DOI** (if the paper is already accepted somewhere): populate the DOI field.
- **Journal-ref** (once published): populate after publication for citation
  discoverability.
