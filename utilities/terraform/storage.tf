# -----------------------------------------------------------------------------
# storage.tf   [MIXED: azurerm for account/CORS, azapi for the blob container]
#
# Storage account with:
#   * shared key access disabled (Entra ID only)
#   * blob public access disabled
#   * public network access restricted to the Discovery subnets + optional IPs
#   * TLS 1.2 minimum
#   * CORS for Discovery Studio + VS Code
#
# One blob container ("discoveryoutputs" by default) that Discovery writes to.
#
# Why the split:
#
#   [azurerm]  azurerm_storage_account cleanly covers the account and folds
#              blob service CORS into a nested blob_properties block. No
#              reason to hand-roll ARM JSON for this.
#
#   [azapi]    azurerm_storage_container talks to the Storage data plane and
#              needs either shared keys or an Entra principal with
#              Storage Blob Data Owner rights on the account. We explicitly
#              disable shared keys above, and requiring the Terraform
#              runner to also hold Blob Data Owner is friction for CI.
#              Talking directly to the ARM control-plane API
#              (Microsoft.Storage/storageAccounts/blobServices/containers)
#              via azapi sidesteps both problems.
#
# If your Terraform runner already has Storage Blob Data Owner (e.g. local dev
# with your own account), you can swap the azapi_resource below for a plain
# azurerm_storage_container and set `storage_use_azuread = true` on the
# azurerm provider in providers.tf.
# -----------------------------------------------------------------------------

resource "azurerm_storage_account" "outputs" {
  name                = local.storage_account_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"

  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true

  # Public network access stays Enabled but locked to "selected virtual
  # networks and IP addresses" via network_rules below. Discovery requires the
  # supercomputer / AKS / workspace / agent subnets to reach the account
  # (VNet-injected compute reaches it over the Microsoft.Storage service
  # endpoint). Fully DISABLING public access without a private endpoint leaves
  # the platform unable to reach storage and breaks investigation I/O. See:
  # https://learn.microsoft.com/azure/microsoft-discovery/concept-storage-account#networking
  public_network_access_enabled = true

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    virtual_network_subnet_ids = [
      azurerm_subnet.supercomputer_nodepool.id,
      azurerm_subnet.aks.id,
      azurerm_subnet.workspace.id,
      azurerm_subnet.private_endpoint.id,
      azurerm_subnet.agent.id,
    ]
    # Optional: client/public IPs (e.g. your workstation) so output data is
    # browsable in Discovery Studio. Azure rejects /31 and /32 CIDRs here.
    ip_rules = var.storage_allowed_ip_rules
  }

  blob_properties {
    cors_rule {
      allowed_origins = [
        "https://studio.discovery.microsoft.com",
        "https://*.vscode-cdn.net",
        "https://vscode.dev",
      ]
      allowed_methods    = ["GET", "HEAD", "DELETE", "PUT"]
      allowed_headers    = ["*"]
      exposed_headers    = ["*"]
      max_age_in_seconds = 200
    }
  }
}

# [AZAPI] Blob container created via ARM control-plane, not data plane.
# See the "Why the split" comment above.
resource "azapi_resource" "outputs_container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = var.blob_container_name
  parent_id = "${azurerm_storage_account.outputs.id}/blobServices/default"

  body = {
    properties = {}
  }

  # Container creation should wait for the account's provisioning to complete.
  depends_on = [azurerm_storage_account.outputs]
}
