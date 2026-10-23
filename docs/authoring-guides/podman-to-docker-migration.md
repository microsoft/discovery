# Migrate a Podman Containerfile to Docker

Discovery catalog tools require a file named exactly `Dockerfile` in each tool
directory. Podman accepts both `Containerfile` and `Dockerfile`, so a tool first
developed with Podman may use a filename that Discovery's Docker-based build
path does not recognize.

Podman's documentation states that a Containerfile uses Dockerfile syntax
internally. For an ordinary, single Containerfile, migration is therefore
usually a rename rather than a rewrite. Podman also supports `.in` files that
it preprocesses with the C preprocessor; those files require a manual render
and review before they can become Dockerfiles.

## Use the migration skill

This repository includes the
[`migrate-podman-containerfile` skill](../../.github/skills/migrate-podman-containerfile/SKILL.md).
From Copilot Chat or Copilot CLI, run:

```text
/migrate-podman-containerfile agents/<agent>/tools/<tool>/Containerfile
```

The skill creates the adjacent `Dockerfile` directly when it can prove the
change is mechanical. It refuses to write a best-effort result when the source
uses preprocessing, multiple build files, generated paths, or unclear
Podman-specific behavior.

## Choose the migration path

| Source or build behavior | Migration |
| --- | --- |
| One plain `Containerfile` with standard Dockerfile instructions | Rename it to `Dockerfile`. |
| A suffixed file such as `Containerfile.cpu` used as the tool's primary build file | Rename the primary file to `Dockerfile`; update exact `-f`/`--file` references. |
| `Containerfile.in`, `Dockerfile.in`, or C-preprocessor directives | Render the file with the project's declared preprocessing inputs, inspect the output, and commit only the rendered `Dockerfile`. |
| Multiple `-f`/`--file` inputs, generated Containerfiles, or included fragments | Consolidate the final build instructions into one reviewed `Dockerfile`; do not concatenate files blindly. |
| Podman-only CLI or runtime assumptions | Map each option or behavior to an explicit Docker/BuildKit equivalent and test the resulting image. |

Starter kits currently reference catalog agents and do not ship tools of their
own. The PR policy still guards both `agents/` and `starter-kits/` so a
Containerfile cannot bypass the canonical catalog structure in either tree.

## Plain Containerfile

Before renaming, inspect the build context's ignore files. Podman prefers
`.containerignore`, whereas Docker uses `.dockerignore` or a Dockerfile-specific
ignore file. Ensure Docker's effective ignore file preserves the exclusions used
by Podman; do not blindly overwrite an existing ignore file when they differ.

For a standard file, preserve its contents and history:

```console
git mv agents/<agent>/tools/<tool>/Containerfile agents/<agent>/tools/<tool>/Dockerfile
```

Search the containing agent for exact filename references and update them:

```console
git grep -n Containerfile -- agents/<agent>
```

Do not change package installation, base images, entrypoints, or other build
semantics merely because the file is being renamed. Existing catalog policies
will validate the renamed Dockerfile's base images and source contents.

## Preprocessed `.in` files

Podman preprocesses Containerfiles ending in `.in` with `cpp`. Docker does not
perform that preprocessing when it reads a Dockerfile. A file containing
directives such as `#include`, `#define`, `#if`, or `#ifdef` is therefore not a
safe rename.

To migrate:

1. Find the script or documented command that supplies include paths, macros,
   and generated fragments. Do not guess missing values.
2. Run that established preprocessing step in an isolated development
   environment.
3. Save the single rendered result as `Dockerfile`.
4. Inspect the complete rendered file. Confirm that no preprocessor directives,
   unresolved macros, or generated host-specific paths remain.
5. Remove the `.in` source and fragments from the catalog contribution unless
   they are needed as ordinary source for another documented purpose.
6. Validate the rendered Dockerfile as described below.

If the preprocessing contract is absent or ambiguous, redesign the build so
one explicit Dockerfile expresses the final instructions. Do not commit a
guessed rendering.

## Review Podman command assumptions

Filename compatibility does not prove that surrounding scripts are portable.
Review scripts and documentation for:

- more than one `-f` or `--file` argument;
- Podman-generated or remotely supplied Containerfiles;
- Podman-only build flags or storage/namespace behavior;
- host mounts, devices, secrets, or networking assumptions;
- commands that invoke `podman` at container runtime rather than only during
  image construction.

Use Docker Buildx equivalents where they exist. When no equivalent exists,
move the behavior into explicit, reviewable Dockerfile instructions or a
documented build input. Keep credentials and host-specific values out of the
Dockerfile and repository.

## Validate

From the tool directory, run Docker's build check when Buildx is available:

```console
docker buildx build --check --file Dockerfile .
```

This checks Dockerfile semantics without completing an image build. Then run
the tool's real image build and tests in your own isolated CI or development
environment; Discovery's privileged PR workflow deliberately does not execute
contributor-controlled Dockerfiles.

Before opening or updating the PR:

```console
python -m pytest .github/tests/rules/test_pol_022.py -q
git diff --check
```

The PR's **Validate PR** check reports `POL-022` when it finds a Podman
Containerfile name or `.in` preprocessing convention. Existing structural and
source policies may report additional findings until the canonical
`Dockerfile` is present and the obsolete file is removed.

## References

- [Podman build documentation](https://docs.podman.io/en/latest/markdown/podman-build.1.html)
  describes Containerfile/Dockerfile naming, shared syntax, and `.in`
  preprocessing.
- [Dockerfile overview](https://docs.docker.com/build/concepts/dockerfile/)
  documents `Dockerfile` as the default and recommended primary filename.
- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
  defines Docker-compatible instructions and parser directives.
