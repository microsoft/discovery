# Microsoft Discovery Platform - Resource Limits Guide

## Overview

This guide provides comprehensive information about resource limits in the Microsoft Discovery platform for PrivatePreview customers. **Understanding these Microsoft Discovery platform limits is essential for proper capacity planning and optimal performance of your Discovery workloads.**

## Table of Contents

- [Microsoft Discovery Platform Resource Limits](#microsoft-discovery-platform-resource-limits)
- [Performance Considerations](#performance-considerations)
  - [Best Practices](#best-practices)
  - [Capacity Planning](#capacity-planning)
- [Additional Resources](#additional-resources)

## Microsoft Discovery Platform Resource Limits
The table below summarizes the capacity and performance limits for PrivatePreview customers in the Microsoft Discovery platform. You can monitor your resource usage in the Microsoft Discovery Studio portal. While resource quantity limits are not enforced during PrivatePreview, it is recommended to stay within the designed capacities to maintain optimal performance.

| Resource | Capacity | Notes |
|----------|----------|-------|
| **Projects per workspace** | 5 | Maximum projects per workspace |
| **Investigations per project** | 20 | Maximum investigations per project |
| **Investigation versions per investigation** | 200 | Version history limit |
| **Users per project** | 1500 | There is restriction on Microsoft Entra and directory service, more information is availble here [directory service limits and restrictions](https://learn.microsoft.com/en-us/entra/identity/users/directory-service-limits-restrictions) |
| **Chat length per project** | 1GB | Shared storage across all chats in project |
| **Users per workspace** | 100 | Maximum concurrent workspace users |
| **Parallel queries per workspace** | 5 | Per-workspace parallel query limit |
| **Maximum number of Knowledge Bases per project** | 100 | Knowledge base limit per project |
| **Active Cogloop instances** | 10 | Maximum concurrent active Cogloop instances that the cognition service can process at a time. Quota is per Cogloop instance, and tasks within a refinement are queued |

> **Note:** The limits listed in the table above may be updated after scale testing and validation of both quota and infrastructure limits.

## Performance Considerations

### Best Practices

1. **Monitor Resource Usage**: Track actual resource consumption across workspaces and projects through the Microsoft Discovery Studio portal
2. **Plan for Peak Load**: Consider maximum concurrent user scenarios and parallel query limits when designing your workloads
3. **Optimize Project Structure**: Organize projects efficiently within workspace limits to maximize resource utilization
4. **Manage Investigation Lifecycle**: Utilize version control effectively and archive completed investigations when appropriate
5. **Balance User Distribution**: Distribute users evenly across workspaces to avoid hitting concurrent user limits
6. **Manage Cogloop Instances**: Be aware that only 10 active Cogloop instances can be processed concurrently. Tasks within each refinement are queued, so plan your task-driven work accordingly

### Capacity Planning

When planning your Microsoft Discovery deployment, consider the following factors:

- **Workspace Organization**: Plan workspace distribution based on team structure and project requirements
- **Project Allocation**: Structure projects within the 5-project limit per workspace for optimal organization
- **Investigation Management**: Plan investigation workflows considering the 20-investigation limit per project
- **Storage Planning**: Monitor chat storage usage across projects (1GB shared limit per project)
- **File Upload Strategy**: Organize file uploads efficiently within the 25-file limit per investigation
- **User Access**: Plan user distribution considering the 100-user limit per workspace
- **Parallel Processing**: Design query strategies within the 5 parallel query limit per workspace

## Additional Resources

- [Azure OpenAI Quota Configuration Guide](../4-how-to/2-onboarding-experience/b--quota-reservations.md)
- [Microsoft Discovery Studio User Guide](../4-how-to/)
