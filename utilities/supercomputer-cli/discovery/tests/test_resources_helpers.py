"""Tests for resource helper functions."""

import pytest

from discovery.poll.resources import extract_resource_group, is_nodepool_of_supercomputer


class TestExtractResourceGroup:
    """Tests for extract_resource_group function."""

    def test_standard_resource_id(self):
        """Extract resource group from a standard Azure resource ID."""
        resource_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1"
        assert extract_resource_group(resource_id) == "my-rg"

    def test_lowercase_resourcegroups(self):
        """Handle lowercase 'resourcegroups' in path."""
        resource_id = "/subscriptions/sub-123/resourcegroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1"
        assert extract_resource_group(resource_id) == "my-rg"

    def test_mixed_case_resourcegroups(self):
        """Handle mixed case 'ResourceGroups' in path."""
        resource_id = "/subscriptions/sub-123/ResourceGroups/My-RG/providers/Microsoft.Discovery/supercomputers/sc-1"
        assert extract_resource_group(resource_id) == "My-RG"

    def test_nodepool_resource_id(self):
        """Extract resource group from a nodepool resource ID."""
        resource_id = (
            "/subscriptions/sub-123/resourceGroups/my-rg/providers/"
            "Microsoft.Discovery/supercomputers/sc-1/nodepools/np-1"
        )
        assert extract_resource_group(resource_id) == "my-rg"

    def test_no_resource_group(self):
        """Return empty string when no resource group in path."""
        resource_id = "/subscriptions/sub-123/providers/Microsoft.Discovery/something"
        assert extract_resource_group(resource_id) == ""

    def test_empty_string(self):
        """Handle empty string input."""
        assert extract_resource_group("") == ""

    def test_malformed_path(self):
        """Handle malformed path where resourceGroups is last element."""
        resource_id = "/subscriptions/sub-123/resourceGroups"
        assert extract_resource_group(resource_id) == ""


class TestIsNodepoolOfSupercomputer:
    """Tests for is_nodepool_of_supercomputer function."""

    def test_matching_nodepool(self):
        """Nodepool belongs to the supercomputer."""
        sc_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1"
        np_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is True

    def test_non_matching_nodepool(self):
        """Nodepool does not belong to the supercomputer."""
        sc_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1"
        np_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-2/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is False

    def test_case_insensitive_match(self):
        """Match should be case-insensitive."""
        sc_id = "/subscriptions/SUB-123/ResourceGroups/MY-RG/providers/Microsoft.Discovery/supercomputers/SC-1"
        np_id = "/subscriptions/sub-123/resourcegroups/my-rg/providers/microsoft.discovery/supercomputers/sc-1/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is True

    def test_partial_name_no_match(self):
        """Should not match if supercomputer name is a prefix of another."""
        sc_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc"
        np_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-extended/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is False

    def test_trailing_slash_on_supercomputer(self):
        """Handle supercomputer ID with trailing slash."""
        sc_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1/"
        np_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is True

    def test_different_subscription(self):
        """Nodepool in different subscription should not match."""
        sc_id = "/subscriptions/sub-123/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1"
        np_id = "/subscriptions/sub-456/resourceGroups/my-rg/providers/Microsoft.Discovery/supercomputers/sc-1/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is False

    def test_different_resource_group(self):
        """Nodepool in different resource group should not match."""
        sc_id = "/subscriptions/sub-123/resourceGroups/rg-1/providers/Microsoft.Discovery/supercomputers/sc-1"
        np_id = "/subscriptions/sub-123/resourceGroups/rg-2/providers/Microsoft.Discovery/supercomputers/sc-1/nodepools/np-1"
        assert is_nodepool_of_supercomputer(np_id, sc_id) is False
