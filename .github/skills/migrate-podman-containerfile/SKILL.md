---
name: migrate-podman-containerfile
description: 'Migrate a Podman Containerfile to the canonical Dockerfile required by the Discovery catalog. Use when a PR fails POL-022, a tool contains Containerfile or Dockerfile.in, or a contributor asks to convert Podman build files for Docker. Creates the Dockerfile directly only when the migration is mechanically safe and refuses ambiguous preprocessing or multi-file builds.'
argument-hint: '<path-to-Containerfile>'
allowed-tools: shell
---

# Migrate Podman Containerfile

Convert one Podman-oriented build file into the canonical `Dockerfile` expected
by Discovery catalog tools. Ordinary Containerfiles use Dockerfile syntax, so a
plain file is normally a rename. Podman's `.in` preprocessing and multi-file
build behavior are not safe filename-only conversions.

## Input

Accept exactly one repository-relative source path under `agents/` or
`starter-kits/`. Prefer a path supplied after the slash command:

```text
/migrate-podman-containerfile agents/example/tools/example/Containerfile
```

If no path is supplied, enumerate changed files in those roots and compare
basenames case-insensitively. Include `Containerfile`, names beginning with
`Containerfile.`, ending with `.Containerfile`, or containing `.Containerfile.`;
also include the corresponding `Dockerfile` variants when they end in `.in`.
Continue only when exactly one candidate exists; otherwise list the candidates
and stop without changing files.

## Safety gates

Before writing anything:

1. Resolve the repository root with `git rev-parse --show-toplevel` and ensure
   the source remains inside `agents/` or `starter-kits/`.
2. Set the destination to `Dockerfile` in the source directory.
3. Stop if the destination already exists. Never overwrite or merge it
   automatically.
4. Stop if the source name ends in `.in`, contains C-preprocessor directives
   such as `#include`, `#define`, or `#if`, or depends on included fragments.
5. Search the containing catalog item for references to the source name,
   repeated `podman build -f/--file` options, generated Containerfiles, or
   Podman-specific build/runtime flags. A single literal `-f Containerfile`
   reference is mechanical; variables, generated paths, multiple build files,
   or unclear semantics are not.
6. Inspect Dockerfile instructions. Standard instructions are `ADD`, `ARG`,
   `CMD`, `COPY`, `ENTRYPOINT`, `ENV`, `EXPOSE`, `FROM`, `HEALTHCHECK`, `LABEL`,
   `MAINTAINER`, `ONBUILD`, `RUN`, `SHELL`, `STOPSIGNAL`, `USER`, `VOLUME`, and
   `WORKDIR`. Stop on unknown instructions or a non-Docker syntax frontend.

When a safety gate fails, make no changes. Explain the exact blocker and point
to `docs/authoring-guides/podman-to-docker-migration.md`, including the manual
steps relevant to that blocker. Do not produce a best-effort Dockerfile.

## Safe migration

When every safety gate passes:

1. Rename the source to the adjacent canonical destination with
   `git mv <source> <directory>/Dockerfile`.
2. Update only exact, literal references to the old filename within the same
   catalog item. Replace them with `Dockerfile`. If a reference requires shell
   evaluation or changes build semantics, undo no user work; stop and report
   that manual migration is required.
3. Preserve file bytes, line endings, instruction order, comments, and parser
   directives. Do not opportunistically rewrite package commands or base
   images.
4. Confirm no Podman build filename remains in the migrated tool directory and
   inspect `git diff -- <catalog-item>`.
5. If Docker with Buildx is available, run a syntax-only check:

   ```console
   docker buildx build --check --file Dockerfile .
   ```

   Run it from the tool directory. Do not run a full image build unless the
   user explicitly asks. If Docker/Buildx is unavailable, report the check as
   not run rather than treating that as success.
6. Run the repository's focused POL-022 test or PR validator when available.

## Result

Report:

- source and destination paths;
- whether the conversion was a byte-preserving rename;
- any exact references updated;
- Docker syntax-check command and result, or why it was not run;
- remaining manual validation, if any.

Success requires a tracked `Dockerfile` and no obsolete Containerfile in the
migrated tool directory.
