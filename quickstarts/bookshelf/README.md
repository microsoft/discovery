# Bookshelf — public SCLC scenario in preparation

This is a **separate Bookshelf QuickStart Scenario**, not the Bookshelf data
used by CMS or SiPhy. Its proposed public corpus is fifteen SCLC papers.
It does not replace the fixed internal leukemia regression dataset.

The `files/` folder holds the original selection and paper
metadata, with every filename, source URL, DOI, licence and checksum. The
fifteen exact PDFs are staged locally under `files/papers/`; their public
source locations are listed under [Supporting files](#supporting-files) below.

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

## Supporting files

The original [manifest.json](files/manifest.json) and
[selection_sclc.json](files/selection_sclc.json) are included unchanged. Together
they identify fifteen exact paper versions, **19,134,519 PDF bytes**. The
manifest contains full titles, DOIs, source URLs, licence records and SHA-256 values.

The exact PDFs are staged locally in `files/papers/`. For public acquisition,
the recorded source downloads are below; preserve the expected filename and
verify its checksum. These links are source records, not a claim that fresh
network retrieval or Discovery indexing was tested in this change.

| Filename | Source download |
| --- | --- |
| PMC10378571.1.pdf | [Canadian consensus](https://pmc-oa-opendata.s3.amazonaws.com/PMC10378571.1/PMC10378571.1.pdf) |
| PMC9174785.1.pdf | [First-line review](https://pmc-oa-opendata.s3.amazonaws.com/PMC9174785.1/PMC9174785.1.pdf) |
| PMC9776593.1.pdf | [Meta-analysis](https://pmc-oa-opendata.s3.amazonaws.com/PMC9776593.1/PMC9776593.1.pdf) |
| PMC9469650.1.pdf | [Lurbinectedin review](https://pmc-oa-opendata.s3.amazonaws.com/PMC9469650.1/PMC9469650.1.pdf) |
| PMC10290806.1.pdf | [DLL3 therapies](https://pmc-oa-opendata.s3.amazonaws.com/PMC10290806.1/PMC10290806.1.pdf) |
| PMC10218846.1.pdf | [Targeted therapies](https://pmc-oa-opendata.s3.amazonaws.com/PMC10218846.1/PMC10218846.1.pdf) |
| PMC11137956.1.pdf | [CASPIAN biomarkers](https://pmc-oa-opendata.s3.amazonaws.com/PMC11137956.1/PMC11137956.1.pdf) |
| PMC8134304.1.pdf | [CASPIAN Japan](https://pmc-oa-opendata.s3.amazonaws.com/PMC8134304.1/PMC8134304.1.pdf) |
| PMC9520052.1.pdf | [Real-world eligibility](https://pmc-oa-opendata.s3.amazonaws.com/PMC9520052.1/PMC9520052.1.pdf) |
| PMC10864288.1.pdf | [Bridging study](https://pmc-oa-opendata.s3.amazonaws.com/PMC10864288.1/PMC10864288.1.pdf) |
| PMC11635664.1.pdf | [LURBICLIN](https://pmc-oa-opendata.s3.amazonaws.com/PMC11635664.1/PMC11635664.1.pdf) |
| PMC7884704.1.pdf | [Belotecan versus topotecan](https://pmc-oa-opendata.s3.amazonaws.com/PMC7884704.1/PMC7884704.1.pdf) |
| PMC7341887.1.pdf | [NABSTER](https://pmc-oa-opendata.s3.amazonaws.com/PMC7341887.1/PMC7341887.1.pdf) |
| PMC13710598.1.pdf | [DeLLphi-304 Japan](https://pmc-oa-opendata.s3.amazonaws.com/PMC13710598.1/PMC13710598.1.pdf) |
| PMC12459094.1.pdf | [Tarlatamab comparison](https://pmc-oa-opendata.s3.amazonaws.com/PMC12459094.1/PMC12459094.1.pdf) |

Recorded article licences are CC BY 4.0; retain attribution/notices and verify
third-party exclusions and current terms before bundling for redistribution.
This is source data, not a prebuilt Bookshelf or proof of scientific acceptance.