# Microsoft Discovery Stable app

The Stable app provides a desktop research experience with local projects,
sessions, agents, bookshelves, tools, and inline results. It is separate from the
[Preview app](../discovery-app/README.md).

> **Documentation proposal for target version 0.0.5.** The navigation and
> community examples in this folder are being prepared for release. They aren't
> an availability announcement or an enterprise support commitment.

## Download

| Platform | Stable installer destination |
| --- | --- |
| Windows x64 | [Download](https://aka.ms/discovery/download/stable/x64/current) |
| macOS | [Download](https://aka.ms/discovery/download/stable/osx/current) |
| RHEL | [Download](https://aka.ms/discovery/download/stable/rhel/current) |

Verify the package's channel, version, architecture, and publisher before
installing. The designated links don't establish support for other architectures.
Don't substitute a Preview installer if Stable isn't available.

Back up existing work before upgrading. Preview-to-Stable migration and
side-by-side installation behavior require release confirmation.

## Documentation map

[Microsoft Learn](https://learn.microsoft.com/azure/microsoft-discovery/) is the
canonical home for product instructions. The companion Stable app articles are
being proposed there and aren't published yet. Final app deep links must be
added when those articles are published; don't substitute service procedures.

| Product guide topic | Community companion |
| --- | --- |
| Overview; comparison with Preview and services | [Compatibility](compatibility.md). |
| Download, installation, sign-in, and first session | Download destinations above; first-session orientation below. |
| Projects, sessions, Bookshelf, agents, and tools | [Scenario recipes](scenarios.md). |
| Index documents and understand limitations | [Ground an answer in a bookshelf](scenarios.md#ground-an-answer-in-a-bookshelf). |
| Create agents and tools | [Reusable research reviewer](scenarios.md#prepare-a-reusable-research-reviewer). |
| Start sessions and work with files | [Compare a source with a collection](scenarios.md#compare-a-source-with-a-collection). |
| Visualize molecules inline | [Visualize caffeine](scenarios.md#visualize-caffeine). |
| Troubleshooting and support | [Feedback guide](feedback.md). |

## First-session orientation

In the Windows walkthrough, setup is followed by GitHub sign-in and browser
device authorization. In the app, use the project selector and **New project**
to choose a local folder, then **New session** to choose a model and send a prompt.
You don't need to create a custom agent or index a collection before the first
conversation.

The sidebar separates **Project data**, **AI capabilities**, and **Sessions**.
Under **AI capabilities**, use **Agents**, **Bookshelves**, and **Tools** for
reusable capabilities rather than treating every attachment as indexed knowledge.

## Know the boundaries

- A local project doesn't mean model processing is offline. The demonstrated
  Bookshelf flow sends document chunks and query text to GitHub through the
  Copilot account for embeddings, and uses the selected model for answers.
- Current product guidance reports that **180 MB of data can be indexed**.
  This is a known working collection size, not a confirmed maximum or per-file limit.
- Embedded OCR isn't provided for interpreting tables or images in PDFs.
  Prepare and verify readable text when the visual content matters.
- Attaching a file doesn't index it, and seeing its filename doesn't prove the
  agent can read its contents.
- The demonstrated inline molecular preview uses an `.xyz` file. Don't infer a
  complete viewer format matrix from that example.
- Full format lists, numeric limits, hardware requirements, and macOS/RHEL
  installation procedures remain release-review items.

## Community content and support

Check [compatibility](compatibility.md) before using agents, skills, or tools from
the catalog. Don't copy Preview engine commands or service deployment definitions
into Stable without testing.

For questions and bugs, use the [feedback guide](feedback.md). The repository's
current community support route is the Microsoft Discovery Discussions forum;
this proposal doesn't change that route.
