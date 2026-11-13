# Stable app community scenarios

These recipes pair reusable prompts with observable outcomes for the Stable app
documentation proposal, target version **0.0.5**. They complement the product
guides on [Microsoft Learn](https://learn.microsoft.com/azure/microsoft-discovery/);
they don't establish supported formats or guarantee scientific correctness.

Use a fresh project with non-sensitive sample inputs. Check the current project,
selected model, and agent before starting each exercise.

## Ground an answer in a bookshelf

Prepare a small collection of related plain-text research notes that you're
authorized to process. Create a bookshelf in **AI capabilities** > **Bookshelves**,
review the data-handling notice, choose an answer-generation model, and add the
files.

Use an agent with **discovery.bookshelf.listShelves** and
**discovery.bookshelf.ask**. In a new session, try:

```text
Use the research-notes bookshelf. Identify the main research questions
represented in these documents. For each finding, identify its supporting
source and explain what the collection doesn't establish.
Don't infer source content from filenames.
```

Check that the intended bookshelf was used, that the answer reflects your sample
notes, and that you can identify the evidence. A success notification isn't a
retrieval check.

Product guidance reports a known working indexing size of **180 MB**, not a
confirmed maximum. There is no embedded OCR for interpreting PDF tables or
images. Start small and verify extraction before scaling a collection.

## Compare a source with a collection

Select **New session** and attach a source with **+** >
**Upload files and folders** > **Files**. Choose an agent with access to the
intended bookshelf.

```text
First check whether you can read the attached source's contents.
If you can, compare its research question and findings with the
research-notes bookshelf. Separate evidence from the attachment and the
indexed documents. Identify agreements, disagreements, and missing evidence.
If either source isn't accessible, explain the limitation and don't guess.
```

Check that both the attachment and the bookshelf were actually read. The product
walkthrough includes a PDF that couldn't be read despite its filename appearing
in the conversation. Explicitly reporting that limitation is preferable to a
fabricated comparison.

Attaching the source doesn't add it to the bookshelf. Index it separately if you
want it included in future collection queries.

## Visualize caffeine

In a separate session, try:

```text
Help me visualize a caffeine molecule.
Explain whether the coordinates are generated or experimentally sourced,
and provide the structure file used for the visualization.
```

Review any requested permissions before code execution or file creation.
Inspect the returned molecular file card and select **Open**.

The walkthrough demonstrates `caffeine.xyz` with a ball-and-stick preview.
Check the molecule identity and the coordinate-generation method. A rendered
structure isn't proof of experimental geometry or simulation readiness.

If file generation fails, inspect the activity details. Don't treat prose about
a molecule as a successfully generated structure file.

## Prepare a reusable research reviewer

Create an agent in **AI capabilities** > **Agents** > **New agent**. Give it a
descriptive name, instructions that require evidence and explicit failure
reporting, and only the tools needed for the task.

For a local skill-authoring exercise, inspect the
[research-review package](examples/research-review/skills/review-research-source/SKILL.md).
Its layout matches the **Skills Folder** source shown by **Tools** > **Add tool**:

```text
research-review/
  skills/
    review-research-source/
      SKILL.md
```

This is an instructional sample, not a prevalidated Stable distribution.
Complete package registration, agent selection, and execution testing on your
target app version before claiming compatibility.

After making the capability available to your agent, start a new session with
**+** > **Agent**, choose the agent, and provide a readable sample source.
Check that it reports the source's question, method, findings, and limitations,
with supporting evidence. If it can't read the source, it should say so.

## Share a reproducible example

Use the [feedback guide](feedback.md) and include the app channel, version,
platform, sample inputs, expected outcome, and actual outcome. Don't include
private research data, authorization codes, or unredacted project paths.
