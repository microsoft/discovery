# -----------------------------------------------------------------------------
# examples/01-prereqs -- providers
#
# Stage 1 substrate for the "module -> full" test. Creates every non-Discovery
# prerequisite (VNet, subnets, identities, storage, role assignments) plus the
# RG-level Microsoft.Discovery/storageContainers binding, then exports their IDs
# for the per-resource control-plane roots (02, 03) and the e2e completion root
# (04) to consume via terraform_remote_state.
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
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
}

provider "azapi" {}
