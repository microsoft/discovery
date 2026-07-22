# 1. Network isolation posture for the Discovery workspace

- Status: Accepted
- Date: 2026-07-21
- Deciders: Discovery utilities maintainers

## Context

A `Microsoft.Discovery/workspaces` resource can be created with two network
knobs that must stay consistent:

- The `NetworkIsolation` tag on the workspace.
- The three subnet IDs in the workspace properties: `agentSubnetId`,
  `privateEndpointSubnetId`, and `workspaceSubnetId`.

When `NetworkIsolation` is `true` and the subnet IDs are supplied, the Discovery
resource provider VNet-injects the managed Container Apps environment and creates
private endpoints (Cosmos, Search, and others) in the private endpoint subnet.
This is a coherent, fully private topology.

Setting `NetworkIsolation` to `false` while still passing the subnet IDs produces
a broken hybrid. The provider honors the subnets enough to disable Cosmos public
access, but because isolation is off it never creates the Cosmos private endpoint
and never VNet-injects the Container Apps environment. The managed `cogloop`
backend then cannot reach Cosmos (403 from the account firewall), its readiness
probe stays at 503, the default agent upsert fails with `InternalServerError`,
and the deployment fails on the project resource.

The same broken backend also blocks teardown: project delete-validation calls the
unhealthy backend and fails, the workspace refuses to delete while the project
exists, and a resource-group delete times out and rolls back. This was observed
as a reproducible incident in `uksouth` (see the repository incident notes for
correlation IDs and diagnosis).

This Terraform utility always provisions the delegated subnets and the private
endpoint subnet, so the isolated topology is clearly the intended design.

## Decision

The module defaults to the fully isolated posture and treats it as the supported
configuration:

- The `network_isolation` variable defaults to `true`.
- The workspace always sets the `NetworkIsolation` tag from that variable and
  always passes `agentSubnetId`, `privateEndpointSubnetId`, and
  `workspaceSubnetId`.
- The broken hybrid (`network_isolation = false` while passing subnet IDs) is
  documented as unsupported. Operators who genuinely want a public preview
  workspace must both set `network_isolation = false` and remove the three subnet
  IDs from the workspace resource, so Cosmos stays public and the Container Apps
  environment is not VNet-injected — a consistent public path.

## Consequences

Positive:

- The managed backend is reachable on first apply; the default agent upserts
  successfully and the project provisions.
- Private endpoints and VNet injection match the provider's expectations, so
  teardown validation passes and the resource group deletes cleanly.
- The Terraform posture matches `../../bicep/uami.bicep`, keeping the two
  utilities behaviorally equivalent.

Negative / trade-offs:

- The module requires a VNet, delegated subnets, and a private endpoint subnet;
  it cannot deploy a subnet-free workspace as-is.
- A public-preview deployment is not a single-flag change: it requires also
  removing the subnet IDs, which is intentionally left as a manual edit to avoid
  reintroducing the hybrid by accident.

## Alternatives considered

- Public preview posture (`network_isolation = false`, no subnet IDs). Valid and
  consistent, but it drops private networking entirely and does not match the
  delegated-subnet topology this module builds. Not the default.
- Broken hybrid (`network_isolation = false` with subnet IDs). Rejected: it is
  the exact configuration that caused the incident described above.

## Related decisions

- Four-identity least-privilege model (`identity.tf` / `roles.tf`), ported from
  `../../bicep/uami.bicep`.
- AzAPI API version pin (`2026-02-01-preview`) for `Microsoft.Discovery/*`
  resources, retained until the AzAPI provider ships schemas for the GA
  `2026-06-01` version.
