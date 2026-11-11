# Bookshelf — public SCLC scenario in preparation

This is a **separate Bookshelf QuickStart Scenario**, not the Bookshelf data
used by CMS or SiPhy. Its proposed public corpus is fifteen SCLC papers.
It does not replace the fixed internal leukemia regression dataset.

The [files folder](files/README.md) holds the original selection and paper
metadata, with every filename, source URL, DOI, licence and checksum. The
fifteen exact PDFs are staged locally under `files/papers/`; their public
source locations are listed on the files page.

The completed owner QuickStart Markdown is still awaited. A previous local
proposal file was empty; this folder does not manufacture a completed guide,
an approved prompt, a successful index or a reference answer in its place.

Once the guide is ready, it will sit beside this README, and the customer
path will be: obtain the guide/papers → create a fresh project → load the
shared runner → approve corpus setup/indexing → run the guide's fixed question
→ verify citations and the expected answer. No indexing or model invocation
is triggered just by opening this folder.

The existing [bookshelf-researcher](https://github.com/microsoft/discovery/tree/88a2a1cd1664b7d609659dc86c65f7f632686715/agents/bookshelf-researcher)
is a reusable repository component, not a new scenario-specific copy.