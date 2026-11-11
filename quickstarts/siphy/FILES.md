# SiPhy file accounting

Inspected source archive: 351 entries, 40,992,256 bytes, SHA-256
`f06834009e5e28b0c2cb18f3b7ff5227d1cb8ee2ecbd84f41eda157f8907159c`.
Original runner: 38,469 bytes, SHA-256
`4c87f20765a007658bbbb247351c9e1790e99e06dc37093cf4c6a33e758111ff`.

| Source path inside archive | Handling |
| --- | --- |
| `ship/README.md` | Setup/criteria adapted in the guide; exact prompt extracted separately. Original digest `7f93063b305c2f9e666d40270f1ce8d5edc0a86b0c971ff7c2ea2286810deb2a`. |
| `ship/dot-github/agents/hardware-spec-dev.agent.md` | Unpublished exact agent; not copied into a scenario or replaced by a lookalike. |
| `ship/dot-github/agents/chip-rtl-design.agent.md` | Same publication/binding requirement. |
| `ship/dot-github/agents/chip-rtl-lint.agent.md` | Same publication/binding requirement. |
| `ship/dot-github/agents/chip-functional-verification.agent.md` | Same publication/binding requirement. |
| `ship/discovery_catalog/chip-rtl-design/` | Agent metadata/README and `tools/rtl-design` reviewed build context; publication required. |
| `ship/discovery_catalog/chip-rtl-lint/` | Agent metadata/README and `tools/rtl-lint`; omit caches/build artifacts from any future contribution. |
| `ship/discovery_catalog/chip-functional-verification/` | Agent metadata/README and `tools/functional-verification`; exact versions need publication. |
| `ship/dot-github/skills/report-gen/` | Required report skill, script/templates/tests; no canonical matching publication found at inspected revision. |
| `ship/dot-github/skills/discovery-add-agents/` | Owner installer copy; compare with canonical add-example-agents rather than silently substitute or duplicate. |
| `ship/knowledge/bs_data/manifest.json` | Source metadata digest `d1964f0a6f72fa84e0770da9a9dea3f7bde3b77a10e58716fd8e0554018a1c13`; sanitized per-paper identity inventory included. |
| `ship/knowledge/bs_data/*.pdf` | Forty exact identities in `data/corpus.csv`; PDFs withheld pending rights. |
| `ship/knowledge/bs_data/.curation/` | Private acquisition/OCR/failed-download evidence, not customer inputs or indexing configuration. Not published. |
| Separate Joe runner | Shared workflow concepts adapted with attribution; original CoreSPI logic retained in this scenario profile for review. |

No completed QuickStart template, independent reference result/report or final
RTL/testbench/VCD run was found in the inspected archive. Missing material stays
missing. This inventory does not authorize redistribution of the whole tar.