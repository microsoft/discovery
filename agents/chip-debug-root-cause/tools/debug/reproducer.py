"""Real reproducer reduction (delta debugging) and OBSERVED determinism.

TWO DEFECTS THIS REPLACES
-------------------------
1. `_reduce` performed no reduction whatsoever. It was an alias for the
   root-cause path and passed the supplied test and seed straight back out, so
   a "minimal reproducer" was simply the original failure relabelled.

2. Worse, determinism was asserted from the PRESENCE OF A FIELD:

       "deterministic": f.get("seed") is not None

   Nothing was ever re-run. A fixed seed is necessary for determinism and
   nowhere near sufficient: uninitialised state, wall-clock and PID entropy,
   hash/iteration order, thread scheduling and simulator version drift all
   survive a fixed seed. Declaring a reproducer deterministic on that basis
   sends an engineer off to debug an intermittent failure believing they can
   reproduce it on demand -- and when it does not reproduce, the tool has cost
   them the time it claimed to save.

THE RULE HERE
-------------
Determinism is a claim about BEHAVIOUR, so it is only ever established by
OBSERVING behaviour: run the thing repeatedly and compare outcomes. With no way
to execute the test, determinism is `not_assessable` -- never True, and never
False either, because "we could not check" is not evidence of flakiness.

Note the asymmetry, which is not a defect but the nature of the evidence:
observing N identical runs CANNOT prove determinism (a 1-in-1000 flake will
survive 5 runs); observing one differing run DOES prove non-determinism. So
`runs_agreed` is reported as bounded evidence carrying its own N, while a single
disagreement is reported as a definitive `non_deterministic`.
"""

import hashlib
import os
import re
import shlex
import shutil
import subprocess


def _normalize(text):
    """Strip run-to-run noise that is not evidence of non-determinism.

    Timestamps, durations, PIDs, memory addresses and temp-file paths differ on
    every run of a perfectly deterministic program. Comparing raw output would
    therefore report EVERYTHING as non-deterministic, and a check that always
    fires is as useless as one that never does.
    """
    t = text or ""
    t = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", t)
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\S*", "TIMESTAMP", t)
    t = re.sub(r"\b\d+(\.\d+)?\s*(ms|us|ns|s|sec|seconds|minutes)\b",
               "DURATION", t, flags=re.I)
    t = re.sub(r"\b(pid|PID)[= ]\s*\d+", "PID", t)
    t = re.sub(r"/tmp/[^\s'\"]+", "/tmp/TMPPATH", t)
    t = re.sub(r"\b\d+(\.\d+)?\s*(MB|KB|GB)\b", "SIZE", t, flags=re.I)
    return t.strip()


def _fingerprint(rc, out, err):
    """Outcome identity: exit status plus normalized output."""
    h = hashlib.sha256()
    h.update(str(rc).encode())
    h.update(b"\x00")
    h.update(_normalize(out).encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(_normalize(err).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def _run(cmd, cwd=None, timeout=600, env=None):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd,
                           capture_output=True, text=True, timeout=timeout,
                           env=env)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        # A timeout is a real, reportable OUTCOME, not an error to swallow: a
        # test that sometimes hangs is precisely the non-determinism we hunt.
        return "timeout", "", "timed out after %ss" % timeout
    except OSError as e:
        return "oserror", "", str(e)


# Exit statuses that mean THE COMMAND NEVER RAN, as opposed to ran and failed.
# 127 is POSIX "command not found"; 126 is "found but not executable"; 9009 is
# the cmd.exe equivalent. "oserror" is our own marker for a failed spawn.
# This is a BACKSTOP only -- see _executable_missing for the primary check,
# because a shell's not-found status is not portable (cmd.exe was observed
# returning plain 1).
_NEVER_RAN = {127, 126, 9009, "oserror"}

# Characters that mean the string is a shell program, not a simple invocation,
# so its first token cannot be resolved to an executable.
_SHELL_META = set("|&;<>()$`\n*?[]{}")


def _executable_missing(cmd):
    """Positively determine that a simple command's executable does not exist.

    PRIMARY guard against the worst failure mode this module can have: a
    reproducer command that never runs fails identically every time, so the
    outcomes agree perfectly and a naive comparison calls it `deterministic:
    True` -- reporting "this never ran" as "this reproduces reliably".

    Deliberately CONSERVATIVE. It returns True only when the command is a plain
    invocation whose program cannot be found; anything with shell metacharacters
    is left to run and be judged by exit status. A false positive here would
    refuse to assess a working reproducer, so the check declines to guess.
    """
    if not isinstance(cmd, str):
        cmd = list(cmd or [])
        if not cmd:
            return True, "empty command"
        prog = cmd[0]
    else:
        if any(c in _SHELL_META for c in cmd):
            return False, None
        try:
            parts = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError:
            return False, None
        if not parts:
            return True, "empty command"
        prog = parts[0].strip('"').strip("'")

    if os.sep in prog or (os.altsep and os.altsep in prog):
        if not os.path.exists(prog):
            return True, "executable path does not exist: %s" % prog
        return False, None
    if shutil.which(prog) is None:
        return True, "executable not found on PATH: %s" % prog
    return False, None


def _did_not_execute(observations):
    """True when EVERY attempt failed to launch the command at all."""
    return bool(observations) and all(
        o["returncode"] in _NEVER_RAN for o in observations)


def check_determinism(cmd, runs=3, cwd=None, timeout=600, fail_regex=None):
    """Re-run `cmd` and report whether the OUTCOME is reproducible.

    Returns a dict that ALWAYS distinguishes three states:
      assessable=False        -> no command; determinism unknown (never True)
      deterministic=False     -> outcomes differed; PROVEN non-deterministic
      deterministic=True      -> N runs agreed; evidence bounded BY THAT N
    """
    if not cmd:
        return {
            "assessable": False, "deterministic": None, "runs": 0,
            "note": ("no reproducer command supplied, so nothing was executed "
                     "and determinism is UNKNOWN. It is not assumed from the "
                     "presence of a seed: a fixed seed does not constrain "
                     "uninitialised state, wall-clock or PID entropy, "
                     "iteration order, or simulator drift.")}
    if runs < 2:
        return {"assessable": False, "deterministic": None, "runs": runs,
                "note": ("determinism needs at least 2 runs to compare; %d "
                         "requested" % runs)}

    missing, why = _executable_missing(cmd)
    if missing:
        return {
            "assessable": False, "deterministic": None, "runs": 0,
            "basis": "command_never_executed",
            "note": ("the reproducer command cannot be executed (%s), so "
                     "determinism is UNKNOWN. It is NOT reported as "
                     "deterministic: a command that never runs fails "
                     "identically every time, and perfect agreement between "
                     "failures to LAUNCH says nothing about whether the test "
                     "reproduces." % why)}

    observations = []
    for i in range(runs):
        rc, out, err = _run(cmd, cwd=cwd, timeout=timeout)
        failed = None
        if fail_regex:
            failed = bool(re.search(fail_regex, (out or "") + (err or ""),
                                    re.I | re.M))
        observations.append({
            "run": i + 1, "returncode": rc,
            "fingerprint": _fingerprint(rc, out, err),
            "matched_fail_regex": failed})

    prints = {o["fingerprint"] for o in observations}
    agreed = len(prints) == 1

    if _did_not_execute(observations):
        return {
            "assessable": False, "deterministic": None, "runs": runs,
            "observations": observations,
            "basis": "command_never_executed",
            "note": ("the reproducer command could not be executed on any of "
                     "the %d attempts (exit status indicates not-found or "
                     "not-executable). Determinism is UNKNOWN: identical "
                     "failures to LAUNCH are not evidence that the test "
                     "reproduces reliably." % runs)}

    verdicts = {o["matched_fail_regex"] for o in observations}
    failure_reproduced = None
    if fail_regex:
        failure_reproduced = (True if verdicts == {True}
                              else False if verdicts == {False} else "intermittent")

    return {
        "assessable": True,
        "deterministic": agreed,
        "runs": runs,
        "distinct_outcomes": len(prints),
        "observations": observations,
        "failure_reproduced": failure_reproduced,
        "basis": "observed_by_reexecution",
        "note": (("all %d runs produced the same outcome. This is BOUNDED "
                  "evidence: N=%d cannot exclude a rarer flake."
                  % (runs, runs)) if agreed else
                 ("runs produced %d DIFFERENT outcomes -- the reproducer is "
                  "NOT deterministic, so any debug session that assumes it "
                  "reproduces on demand will waste time."
                  % len(prints)))}


def ddmin(items, oracle, max_steps=200):
    """Classic delta-debugging minimisation (Zeller's ddmin).

    `oracle(subset) -> True` means the failure STILL REPRODUCES with only that
    subset. Returns the 1-minimal subset: removing any single remaining element
    makes the failure disappear.

    This is the actual reduction the `reduce` scenario claimed to perform. It
    matters because a 10,000-transaction failing test and a 3-transaction one
    describe the same bug, but only the second can be understood.
    """
    items = list(items or [])
    if not items:
        return [], {"steps": 0, "note": "nothing to reduce"}
    if not oracle(items):
        # The failure must be present in the full input, or every later
        # judgement is meaningless. Fail closed and say so.
        return None, {"steps": 1, "reduced": False,
                      "note": ("the failure did NOT reproduce with the full "
                               "input, so there is nothing to minimise and the "
                               "oracle or the input is wrong")}

    n = 2
    steps = 1
    current = items
    while len(current) >= 2 and steps < max_steps:
        chunk = max(1, len(current) // n)
        subsets = [current[i:i + chunk] for i in range(0, len(current), chunk)]
        reduced = False

        for sub in subsets:                      # try each chunk alone
            steps += 1
            if steps >= max_steps:
                break
            if sub and oracle(sub):
                current, n, reduced = sub, 2, True
                break

        if not reduced:
            for sub in subsets:                  # try each complement
                comp = [x for x in current if x not in sub]
                steps += 1
                if steps >= max_steps:
                    break
                if comp and oracle(comp):
                    current = comp
                    n = max(n - 1, 2)
                    reduced = True
                    break

        if not reduced:
            if n >= len(current):
                break
            n = min(len(current), 2 * n)

    return current, {"steps": steps,
                     "reduced": len(current) < len(items),
                     "from": len(items), "to": len(current),
                     "hit_step_cap": steps >= max_steps,
                     "basis": "ddmin_with_executed_oracle"}


def make_command_oracle(cmd_template, fail_regex, cwd=None, timeout=600,
                        writer=None):
    """Build a ddmin oracle that EXECUTES the test on a candidate subset.

    `cmd_template` must contain `{input}`; `writer(subset, path)` serialises a
    candidate. The oracle reports True only when the failure signature is
    observed again -- reduction driven by real execution, not by assumption.
    """
    import json
    import os
    import tempfile

    def _default_writer(subset, path):
        with open(path, "w") as fh:
            json.dump(subset, fh)

    w = writer or _default_writer

    def oracle(subset):
        d = tempfile.mkdtemp(prefix="ddmin_")
        path = os.path.join(d, "candidate.json")
        try:
            w(subset, path)
            cmd = cmd_template.replace("{input}", path)
            rc, out, err = _run(cmd, cwd=cwd, timeout=timeout)
            return bool(re.search(fail_regex, (out or "") + (err or ""),
                                  re.I | re.M))
        finally:
            try:
                os.remove(path)
                os.rmdir(d)
            except OSError:
                pass

    return oracle
