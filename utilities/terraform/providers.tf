# -----------------------------------------------------------------------------
# providers.tf
#
# We use TWO Terraform providers on purpose (see docs/adr-terraform-phase-0-plan.md):
#
#   * azurerm  -> stable, typed resources for every non-Discovery primitive
#                 (VNet, subnets, UAMI, storage account, blob CORS, role
#                 assignments).
#
#   * azapi    -> every Microsoft.Discovery/* resource, plus one storage
#                 container. There are no azurerm_discovery_* resources in
#                 the AzureRM provider today; azapi talks directly to the ARM
#                 REST API at a pinned API version.
#
# Pinning: azapi resources in this module use API version 2026-06-01 (the
# GA Discovery API). Do not downgrade to 2026-02-01-preview.
# -----------------------------------------------------------------------------

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.20"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local backend by default. Swap for azurerm remote state before you use
  # this in shared/production environments.
  # backend "azurerm" { ... }
}

provider "azurerm" {
  features {}

  # `shared_access_key_enabled = false` on our storage account means the
  # post-create data-plane readiness poll must use AAD instead of keys.
  # Requires the terraform-runner identity to hold a blob data role on the
  # storage account (or its RG/subscription). See quickstart Step 6.
  storage_use_azuread = true
}

provider "azapi" {
  # Optional but recommended: catch Discovery schema errors at plan time
  # rather than mid-apply.
  # enable_preflight = true
}
