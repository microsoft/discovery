"""Requirement identity: caller-supplied IDs are authoritative, derived ones are labelled.

WHY THIS EXISTS
---------------
Requirement IDs were ORDINALS OVER INPUT LIST ORDER:

    for i, raw in enumerate(reqs, 1):
        "id": "%s-%03d" % (prefix, i)

Insert a requirement in the middle and every subsequent ID silently re-points at
a different requirement. Nothing errors -- every ID stays well-formed and every
ID still resolves -- so the damage surfaces much later as a traceability matrix
that is complete, internally consistent, and WRONG.

THE RULE, FROM chip-specification-authoring-skill
--------------------------------------------------
That skill already states the discipline; the tool simply never implemented it:

  * Assign once; never reuse. A deleted requirement RETIRES its identifier.
  * Derive from content or a monotonic counter, NEVER from order in the file.
  * Renumbering is a breaking change to every artifact that cites the spec.

WHERE IDENTITY LIVES
--------------------
In the SPEC DOCUMENT, not in this tool. A requirement that carries an `id` keeps
it verbatim -- the tool has no business renaming something the author has already
named and that other artifacts already cite. The tool's job is to ENFORCE the
naming system, not to own it: it detects collisions, malformed IDs, and IDs that
would otherwise be silently reassigned.

Only when an ID is ABSENT does the tool derive one, from content, and label it as
tool-assigned so the author can adopt it into the spec.

WHAT THIS CANNOT DO, AND WHY IT IS SAID PLAINLY
------------------------------------------------
"Assign once; never reuse" spans REVISIONS, and this tool sees exactly one
revision per run -- it has no input directory and no prior-state parameter. So it
cannot tell that REQ-007 existed last week and has since been deleted, nor that
an ID was recycled onto a different requirement between runs. Cross-revision
identity requires the caller to carry IDs forward in the spec, which is precisely
why caller-supplied IDs are authoritative here.
"""

import hashlib
import re

# A derived ID is content-addressed: same text -> same identifier, independent of
# position. 6 hex characters is ~16.7M values; for specs of a few hundred
# requirements the accidental-collision probability is negligible, and a real
# collision is detected and reported rather than assumed away.
_HASH_CHARS = 6

_ID_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[A-Za-z0-9_.-]+$")


def normalize_text(text):
    """Canonical form for content addressing: whitespace- and case-insensitive.

    Deliberately NOT punctuation-insensitive. Two requirements differing only by
    a comma are different text, and silently merging them would be a judgement
    this tool is not entitled to make.
    """
    return re.sub(r"\s+", " ", str(text).strip().lower())


def derive_id(text, prefix="REQ"):
    """Content-derived identifier. Stable under reordering; changes if text changes."""
    h = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
    return "%s-%s" % (prefix, h[:_HASH_CHARS].upper())


def assign(reqs, prefix="REQ"):
    """Resolve an identifier for every requirement.

    Returns (assignments, findings) where each assignment is
    {index, id, source, text} and `source` is one of:

      "caller_supplied"  -- the requirement carried an id; used verbatim
      "derived_content"  -- no id supplied; derived from the requirement text

    `findings` carries every identity defect, each with a severity. Nothing is
    silently repaired: a collision is reported, not renamed away.
    """
    assignments, findings = [], []
    by_id = {}
    by_text = {}

    for index, raw in enumerate(reqs):
        if isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("statement") or "")
            supplied = raw.get("id")
        else:
            text, supplied = str(raw), None

        key = normalize_text(text)

        # ABSENT means None or blank -- NOT merely falsy. `if supplied:` would
        # treat an id of 0 as absent and quietly derive a replacement, which is
        # the tool overruling the author's naming without saying so. A weird id
        # must surface as malformed, not vanish.
        absent = supplied is None or not str(supplied).strip()
        if not absent:
            rid, source = str(supplied).strip(), "caller_supplied"
            if not _ID_SHAPE.match(rid):
                findings.append({
                    "kind": "malformed_id", "index": index, "id": rid,
                    "severity": "gating",
                    "detail": ("'%s' does not look like an identifier "
                               "(expected PREFIX-SUFFIX, e.g. REQ-014). A "
                               "citation cannot be resolved against a name with "
                               "no recognisable shape." % rid)})
        else:
            rid, source = derive_id(text, prefix), "derived_content"

        # ASSIGN ONCE, NEVER REUSE -- the part this tool CAN check within a
        # revision. Two requirements sharing an identifier is unambiguously a
        # defect: every downstream citation of that ID becomes ambiguous, and no
        # reader can tell which requirement was meant.
        if rid in by_id:
            findings.append({
                "kind": "duplicate_id", "index": index, "id": rid,
                "also_at": by_id[rid], "severity": "gating",
                "detail": ("identifier '%s' is used by requirement %d and "
                           "requirement %d. Every citation of it is ambiguous. "
                           "NOT auto-renamed: renaming would silently re-point "
                           "one of them, which is the defect this check exists "
                           "to catch." % (rid, by_id[rid], index))})
        else:
            by_id[rid] = index

        # Identical text under DIFFERENT caller-supplied IDs is legitimate (the
        # same sentence may be stated for two blocks), but identical text with
        # DERIVED ids collides by construction -- content addressing cannot
        # separate requirements that have identical content. Reported so the
        # author deduplicates or gives them explicit, distinct IDs.
        if key in by_text and source == "derived_content":
            findings.append({
                "kind": "identical_text_derived_id", "index": index,
                "id": rid, "also_at": by_text[key], "severity": "gating",
                "detail": ("requirements %d and %d have identical text and "
                           "neither carries an explicit id, so both derive the "
                           "SAME identifier. Content addressing cannot "
                           "distinguish identical content: deduplicate them, or "
                           "assign explicit distinct ids."
                           % (by_text[key], index))})
        by_text.setdefault(key, index)

        assignments.append({"index": index, "id": rid, "source": source,
                            "text": text})

    return assignments, findings


def summary(assignments, findings):
    """Identity evidence for the envelope."""
    derived = [a for a in assignments if a["source"] == "derived_content"]
    supplied = [a for a in assignments if a["source"] == "caller_supplied"]
    gating = [f for f in findings if f["severity"] == "gating"]
    return {
        "basis": "caller_supplied_else_content_derived",
        "total": len(assignments),
        "caller_supplied": len(supplied),
        "derived": len(derived),
        "derived_ids": [{"id": a["id"], "text": a["text"][:80]} for a in derived],
        "identity_findings": findings or None,
        "gating_findings": len(gating),
        "stability_note": (
            "IDs are content-derived or caller-supplied -- never positional. "
            "Inserting or reordering a requirement no longer re-points existing "
            "identifiers."),
        "cross_revision_limit": (
            "This tool sees ONE revision per run: it cannot detect an identifier "
            "retired in an earlier revision, nor one recycled onto a different "
            "requirement between runs. Carry ids forward in the spec document to "
            "make identity stable across revisions -- that is what makes "
            "caller-supplied ids authoritative here."),
    }
