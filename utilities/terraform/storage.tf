# -----------------------------------------------------------------------------
# storage.tf   [MIXED: azurerm for account/CORS, azapi for the blob container]
#
# Storage account with:
#   * shared key access disabled (Entra ID only)
#   * blob public access disabled
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

  # Discovery's storageContainer binding disables public network access on
  # the account. Declare `false` here so plan doesn't perpetually try to
  # re-enable it (AzureRM's default for this field is `true`).
  public_network_access_enabled = false

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
