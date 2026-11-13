# Stable, Preview, and services compatibility

Shared names don't guarantee interchangeable workflows. Identify the experience
and tested version before following an example.

| Experience | Documentation | Don't assume |
| --- | --- | --- |
| Stable app | [Stable entry point](README.md) and the proposed Learn app track. | Preview engine commands, service resource definitions, or catalog entries work unchanged. |
| Preview app | [Existing Preview guides](../discovery-app/README.md). | Their local SDK, CLI, indexing, or installation behavior applies to Stable. |
| Microsoft Discovery services | [Microsoft Learn](https://learn.microsoft.com/azure/microsoft-discovery/). | Desktop projects have service governance, quotas, deployment requirements, or support terms. |

## Identify compatibility in contribution documentation

Add a short compatibility statement to your example's README:

```text
Experience: Microsoft Discovery Stable app
Tested app version: <version you actually tested>
Platform and architecture: <tested platform>
Prerequisites: <models, runtimes, tools, account access, and network needs>
Verification: <sample input and observable successful outcome>
Known limitations: <format, data, or permission constraints>
```

Don't label an example tested against 0.0.5 unless you've actually verified it on
that build. A proposed recipe or metadata entry alone isn't execution evidence.

For a shared example, list each experience separately. Record differences in
installation, authentication, agent/tool format, input data, and execution.
Use prose in the README; this proposal doesn't add catalog schema fields or
retroactively assert compatibility for existing entries.

## Keep Preview links working

The `docs/discovery-app/` path remains the Preview documentation location.
Stable content lives in `docs/stable-app/`. Don't move Preview pages or
silently rewrite their workflows as Stable instructions.

## Migration and support

No automatic Preview-to-Stable project, index, tool, or agent migration is
established by this proposal. Back up your work before changing installations.
Don't infer an SLA or enterprise support entitlement from the Stable channel name.
