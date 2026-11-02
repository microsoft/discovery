#!/usr/bin/env bash
# Post-build sanity checks. Run after build.sh.
#
# Usage: check.sh [report-dir]

set -uo pipefail
DIR="${1:-report}"
cd "$DIR"

fail=0
warn() { echo "  ⚠ $*"; fail=$((fail+1)); }
ok()   { echo "  ✓ $*"; }

echo "→ checking ${DIR}/"

# 1. PDF exists
if [[ -f main.pdf ]]; then
  ok "main.pdf exists ($(ls -lh main.pdf | awk '{print $5}'))"
else
  warn "main.pdf missing — build failed?"
fi

# 2. Undefined refs / citations in log
if [[ -f main.log ]]; then
  undef=$(grep -cE "LaTeX Warning:.*(undefined|multiply-defined)" main.log || true)
  if [[ "$undef" -eq 0 ]]; then
    ok "no undefined refs/cites in log"
  else
    warn "$undef undefined-reference or duplicate warning(s) in main.log"
    grep -nE "LaTeX Warning:.*(undefined|multiply-defined)" main.log | head -5 | sed 's/^/      /'
  fi
else
  warn "main.log not found (build with --keep-logs)"
fi

# 3. Citation coverage
if [[ -f main.tex && -f references.bib ]]; then
  cites=$(grep -oE '\\cite[pt]?\*?\{[^}]+\}' main.tex \
          | sed -E 's/\\cite[pt]?\*?\{//; s/\}//' \
          | tr ',' '\n' | sed 's/^ *//; s/ *$//' | sort -u | grep -c . || true)
  bibs=$(grep -cE '^@[a-zA-Z]+\{' references.bib || true)
  ok "unique cite keys in main.tex: ${cites}"
  ok "entries in references.bib: ${bibs}"
fi

# 4. Every \includegraphics target exists
#    NOTE: this check is VACUOUSLY TRUE when the paper has zero figures --
#    "all targets found" passes trivially with nothing to find. Check 4b below
#    is the existence check that makes it meaningful. See SKILL.md.
if [[ -f main.tex ]]; then
  missing=0
  while IFS= read -r figpath; do
    # strip any width/option, keep only the path
    if [[ -n "$figpath" && ! -f "$figpath" && ! -f "${figpath}.pdf" && ! -f "${figpath}.png" ]]; then
      warn "missing figure: $figpath"
      missing=$((missing+1))
    fi
  done < <(grep -oE '\\includegraphics(\[[^]]*\])?\{[^}]+\}' main.tex \
           | sed -E 's/\\includegraphics(\[[^]]*\])?\{([^}]+)\}/\2/')
  if [[ "$missing" -eq 0 ]]; then
    ok "all \\includegraphics targets found on disk"
  fi
fi

# 4b. THE PAPER ACTUALLY HAS FIGURES (non-vacuous companion to check 4)
#     A 47-page paper once passed every check in this script with ZERO charts:
#     "every figure is pipeline-emitted" and "all targets found" are both TRUE
#     of nothing. Any universally-quantified check needs an existence partner.
if [[ -f main.tex ]]; then
  nfigs=$(cat main.tex sections/*.tex 2>/dev/null \
          | grep -cE '\\includegraphics' || true)
  if [[ "$nfigs" -eq 0 ]]; then
    warn "ZERO figures in the paper. Tables are not figures. If this is a data"
    warn "  analysis, ask what the reader should SEE, not just read."
  elif [[ "$nfigs" -lt 4 ]]; then
    warn "only ${nfigs} figure(s) — thin for a full paper; confirm that is intended"
  else
    ok "${nfigs} \\includegraphics call(s) in the manuscript"
  fi

  if [[ -f generate_figures.py ]]; then
    ok "generate_figures.py present (figures regenerable from data)"
  elif [[ "$nfigs" -gt 0 ]]; then
    warn "figures exist but generate_figures.py is missing — are they hand-made?"
  fi
fi

# 4c. Appendices come AFTER the body
#     Sections assembled in task-completion order once put a 20-page process
#     appendix at section 2 of 5, before any finding.
if [[ -f main.tex ]]; then
  if grep -qiE '\\(section|input|include)\{[^}]*appendix' main.tex \
     || grep -qliE '\\section\{[^}]*appendix' sections/*.tex 2>/dev/null; then
    if grep -q '\\appendix' main.tex; then
      apx_line=$(grep -n '\\appendix' main.tex | head -1 | cut -d: -f1)
      last_input=$(grep -n '\\input{' main.tex | tail -1 | cut -d: -f1)
      if [[ -n "$apx_line" && -n "$last_input" && "$apx_line" -lt "$last_input" ]]; then
        ok "\\appendix present and body content precedes it"
      else
        ok "\\appendix present"
      fi
    else
      warn "a section is named 'appendix' but main.tex never issues \\appendix --"
      warn "  it will render as a NUMBERED BODY SECTION, not a lettered appendix"
    fi
  fi
fi

# 5. arxiv soft limit
if [[ -f main.pdf ]]; then
  bytes=$(stat -f%z main.pdf 2>/dev/null || stat -c%s main.pdf)
  mb=$((bytes / 1024 / 1024))
  if [[ "$mb" -gt 10 ]]; then
    warn "main.pdf is ${mb} MB (arxiv soft limit is 10 MB)"
  else
    ok "main.pdf is ${mb} MB (under arxiv 10 MB soft limit)"
  fi
fi

echo
if [[ "$fail" -eq 0 ]]; then
  echo "✓ all mechanical checks passed"
  echo
  echo "  These checks cannot tell you whether the paper is any good."
  echo "  OPEN main.pdf AND READ IT before calling it done:"
  echo "    - Does a reader meet the story before the machinery?"
  echo "    - Do the figures carry the argument, or just decorate it?"
  echo "    - Any internal identifiers, ticket numbers, or commit SHAs in the body?"
  exit 0
else
  echo "⚠ ${fail} check(s) flagged — review above"
  exit 1
fi
