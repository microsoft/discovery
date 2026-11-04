# Contributing

Thanks for helping improve Microsoft Discovery! You can contribute catalog
agents, starter kits, utilities, and documentation here. The Discovery app's
source code is not in this repository.

## Choose your contribution

| Change | Where to work | Get started |
| --- | --- | --- |
| Add or update an agent | `agents/<agent-name>/` | [Agent authoring guide](docs/authoring-guides/agent-authoring-guide.md) |
| Add or update a starter kit | `starter-kits/<kit-name>/` | [Starter-kit authoring guide](docs/authoring-guides/starter-kit-authoring-guide.md) |
| Add or fix a utility | `utilities/<utility-name>/` | Follow the utility's README and include focused tests and validation evidence. |
| Fix documentation | The relevant Markdown file or [docs/](docs/) | Make a focused change and check its links. |

Utility source code, tests, dependency manifests, lock files, and ignore files
are open to outside contributors as well as Microsoft members. The root
`.gitignore` may also be updated for contribution-related build artifacts.
Neither Microsoft membership nor repository write access is required for these
contributions; correctness checks, CLA, and normal CODEOWNER review still apply.
Engineering reviewers own utilities, except Discovery Toolbox releases, which
retain maintainer ownership and release-specific validation.

For product bugs, questions, or ideas, use
[Discussions](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions).
For changes to protected schemas, workflows, validator policy, or other trusted
repository configuration, propose an idea there so a Microsoft maintainer can
land the agreed change. A visible Microsoft `MEMBER`/`OWNER` association or
repository write/maintain/admin access permits broader author scope, but private
organization membership may not be visible to Actions. An absent association is
not proof that someone is outside Microsoft, and does not block ordinary
utility contributions.

## Quick start

1. **Fork this repository** on GitHub. Clone your fork and create a branch,
   replacing `YOUR-USERNAME` with your GitHub username:

   ```console
   git clone https://github.com/YOUR-USERNAME/discovery.git
   cd discovery
   git switch -c my-contribution
   ```

2. **Make changes.** Follow the
   [agent authoring guide](docs/authoring-guides/agent-authoring-guide.md) or
   [starter-kit authoring guide](docs/authoring-guides/starter-kit-authoring-guide.md)
   for required files, naming, and examples.
3. **Check your work** using the checklist below. If you include tool code,
   test it in your own isolated environment or CI before submission. Tools
   developed with Podman must use the canonical `Dockerfile`; follow the
   [Podman-to-Docker migration guide](docs/authoring-guides/podman-to-docker-migration.md)
   if your source uses `Containerfile` or `.in` preprocessing.
4. **Commit and push your branch**, then open a pull request against `main`.
   Complete the [PR template](.github/pull_request_template.md) and explain what
   changed and how you tested it. You can change your PR status to draft so that you get
   the benefit of the checks, without triggering a review.
5. **Respond to feedback.** Check the PR's status checks and run logs, address
   findings, and push follow-up commits to the same branch.

## Before opening your PR

- [ ] Follow the relevant authoring guide and include the required documentation.
- [ ] Check examples, Markdown links, and images.
- [ ] Remove secrets, customer data, unfinished placeholders, and editor/build artifacts.
- [ ] Do not hand-edit [.auto-registry/](.auto-registry/); generated registry updates are handled separately.

## What happens next?

Some fork runs need maintainer authorization. Resolve merge conflicts and
address check failures or review comments. A maintainer reviews and merges
your PR once the required checks and approvals are satisfied.

For the PR lifecycle, automated checks, diagnostic feedback, and test model, see
[Pull request workflow and checks](.github/workflows/README.md#pull-request-validation-and-feedback).
You do not need to configure these workflows to contribute catalog content.

## Contributor License Agreement

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit <https://cla.opensource.microsoft.com>.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (status check, comment, etc.). Simply follow the instructions provided by the bot. You will only need to do this once across all repos using our CLA.

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information, see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact <opencode@microsoft.com> with any additional questions or comments.

## Reporting security issues

Please do **not** file public GitHub issues or Discussions for security reports.
See [SECURITY.md](SECURITY.md) for the coordinated-disclosure process and contact address.
