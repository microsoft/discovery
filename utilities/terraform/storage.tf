# -----------------------------------------------------------------------------
# storage.tf   [MIXED: azurerm for account/CORS, azapi for the blob container]
#
# Storage account with:
#   * shared key access disabled (Entra ID only)
#   * blob public access disabled
#   * public network access disabled; reachable via a blob private endpoint
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

  # Public network access stays DISABLED. The Discovery storageContainer binding
  # (network hardening) forces publicNetworkAccess=Disabled and clears any VNet
  # firewall rules on the account, so a "selected networks" allowlist does not
  # hold -- the only durable private path is a private endpoint (see
  # azurerm_private_endpoint.blob below). Declaring false here matches the
  # platform and avoids perpetual plan drift.
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

# -----------------------------------------------------------------------------
# Blob private endpoint + private DNS   [PROVIDER: azurerm]
#
# Discovery network hardening keeps the account's publicNetworkAccess=Disabled,
# so the VNet-injected supercomputer / workspace / agent compute reaches Blob
# storage through a private endpoint in the privateEndpointSubnet. The private
# DNS zone privatelink.blob.core.windows.net (linked to the VNet) resolves the
# account FQDN to the endpoint's private IP, and the zone group keeps the A
# record in sync if the endpoint IP changes.
#
# Note: with public access disabled, browsing output data in Discovery Studio
# requires the browser to reach the private endpoint (VNet, VPN, or ExpressRoute).
# -----------------------------------------------------------------------------
resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "link-blob-${local.storage_account_name}"
  resource_group_name   = data.azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.this.id
  registration_enabled  = false
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-blob-${local.storage_account_name}"
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.private_endpoint.id

  private_service_connection {
    name                           = "pe-blob-conn"
    private_connection_resource_id = azurerm_storage_account.outputs.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
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
