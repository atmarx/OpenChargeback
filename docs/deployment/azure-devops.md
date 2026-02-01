# Deploying to Azure App Service

> **Note**: For CI (tests, linting, security scanning), see [`azure-pipelines.yml`](../../azure-pipelines.yml) in the repository root. This guide covers deployment to Azure App Service.

This guide covers deploying openchargeback to Azure App Service with:

- Infrastructure as Code using Bicep
- CI/CD via Azure DevOps Pipelines or GitHub Actions
- Azure Communication Services for email delivery
- SQLite on Azure Files for persistence

## Prerequisites

- Azure subscription with permissions to create resources
- Azure DevOps organization or GitHub repository
- Custom domain for email sending (ACS requirement)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Azure App Service (B1)                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           openchargeback Container (Port 8000)        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ Azure Files │      │  Key Vault  │      │     ACS     │
│  (SQLite)   │      │  (Secrets)  │      │   (Email)   │
└─────────────┘      └─────────────┘      └─────────────┘
```

## Azure Resources

| Resource | Purpose | SKU/Tier | Est. Cost |
|----------|---------|----------|-----------|
| Resource Group | Container for all resources | - | - |
| App Service Plan | Hosting plan | B1 (Basic) | ~$13/month |
| App Service | The web application | - | (included) |
| Azure Container Registry | Store Docker images | Basic | ~$5/month |
| Storage Account | Azure Files for SQLite + outputs | Standard LRS | ~$1/month |
| Azure Communication Services | Email sending | Pay-as-you-go | ~$0.25/1000 emails |
| Key Vault | Secrets management | Standard | ~$0.03/10K ops |

**Estimated total: ~$20/month** for a low-traffic internal application.

## Bicep Infrastructure

### Recommended Structure

```
infra/
├── main.bicep              # Orchestrates modules
├── main.bicepparam         # Environment parameters
└── modules/
    ├── app-service.bicep
    ├── container-registry.bicep
    ├── storage.bicep
    ├── communication-services.bicep
    └── keyvault.bicep
```

### Main Bicep Template

```bicep
targetScope = 'resourceGroup'

@description('Environment name')
param environmentName string = 'prod'

@description('Location for all resources')
param location string = resourceGroup().location

@description('Container image tag')
param imageTag string = 'latest'

var appName = 'openchargeback-${environmentName}'

// Container Registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: replace('${appName}acr', '-', '')
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// Storage Account for Azure Files
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: replace('${appName}st', '-', '')
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'

  resource fileServices 'fileServices' = {
    name: 'default'

    resource dataShare 'shares' = {
      name: 'openchargeback-data'
    }
  }
}

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: '${appName}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: tenant().tenantId
    accessPolicies: [
      {
        tenantId: tenant().tenantId
        objectId: appService.identity.principalId
        permissions: { secrets: ['get'] }
      }
    ]
  }
}

// App Service Plan
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${appName}-plan'
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  properties: {
    reserved: true  // Required for Linux
  }
}

// App Service
resource appService 'Microsoft.Web/sites@2023-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'DOCKER|${acr.properties.loginServer}/openchargeback:${imageTag}'
      alwaysOn: true
      httpLoggingEnabled: true
      appSettings: [
        { name: 'DOCKER_REGISTRY_SERVER_URL', value: 'https://${acr.properties.loginServer}' }
        { name: 'DOCKER_REGISTRY_SERVER_USERNAME', value: acr.listCredentials().username }
        { name: 'DOCKER_REGISTRY_SERVER_PASSWORD', value: acr.listCredentials().passwords[0].value }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'DATABASE_PATH', value: '/data/billing.db' }
        { name: 'WEB_SECRET_KEY', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=web-secret-key)' }
        { name: 'ACS_CONNECTION_STRING', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=acs-connection-string)' }
      ]
      azureStorageAccounts: {
        data: {
          type: 'AzureFiles'
          accountName: storage.name
          shareName: 'openchargeback-data'
          mountPath: '/data'
          accessKey: storage.listKeys().keys[0].value
        }
      }
    }
    httpsOnly: true
  }
}

output appUrl string = 'https://${appService.properties.defaultHostName}'
output acrLoginServer string = acr.properties.loginServer
```

### Key Configuration Points

**Azure Files Mount**:
- Mount path: `/data` (contains SQLite database and output files)
- Persists across container restarts and deployments

**Environment Variables**:
| Variable | Purpose |
|----------|---------|
| `WEBSITES_PORT` | Tell App Service the container listens on 8000 |
| `DATABASE_PATH` | SQLite file location on mounted share |
| `WEB_SECRET_KEY` | Session encryption (from Key Vault) |
| `ACS_CONNECTION_STRING` | Email service (from Key Vault) |

## Code Changes for Azure Communication Services

### Configuration Addition

Add to `config.yaml`:

```yaml
email_provider: acs  # Options: "smtp" or "acs"

azure_communication_services:
  connection_string: ${ACS_CONNECTION_STRING}
  sender_address: noreply@your-domain.com
```

### New Dependency

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing deps
    "azure-communication-email>=1.0.0",
]
```

### ACS Email Provider

Create `src/openchargeback/delivery/acs.py`:

```python
from azure.communication.email import EmailClient
import base64
from pathlib import Path

def send_email_acs(config, to_email: str, subject: str, html_body: str,
                   attachments: list[Path] | None = None):
    """Send email via Azure Communication Services."""
    client = EmailClient.from_connection_string(config.connection_string)

    message = {
        "senderAddress": config.sender_address,
        "recipients": {"to": [{"address": to_email}]},
        "content": {
            "subject": subject,
            "html": html_body,
        },
    }

    if attachments:
        message["attachments"] = [
            {
                "name": path.name,
                "contentType": "application/pdf",
                "contentInBase64": base64.b64encode(path.read_bytes()).decode(),
            }
            for path in attachments
        ]

    poller = client.begin_send(message)
    return poller.result()
```

## CI/CD Pipelines

### Option A: Azure DevOps Pipelines

#### Combined Pipeline (`azure-pipelines.yml`)

```yaml
trigger:
  branches:
    include:
      - main

pool:
  vmImage: 'ubuntu-latest'

variables:
  resourceGroup: 'openchargeback-rg'
  acrName: 'focusbillingprodacr'
  appName: 'openchargeback-prod'

stages:
  - stage: Build
    jobs:
      - job: BuildAndPush
        steps:
          - task: AzureCLI@2
            displayName: 'Build and push to ACR'
            inputs:
              azureSubscription: 'Azure-ServiceConnection'
              scriptType: 'bash'
              scriptLocation: 'inlineScript'
              inlineScript: |
                az acr build \
                  --registry $(acrName) \
                  --image openchargeback:$(Build.SourceVersion) \
                  --image openchargeback:latest \
                  --file docker/Dockerfile \
                  .

  - stage: Deploy
    dependsOn: Build
    jobs:
      - job: DeployApp
        steps:
          - task: AzureCLI@2
            displayName: 'Deploy Bicep'
            inputs:
              azureSubscription: 'Azure-ServiceConnection'
              scriptType: 'bash'
              scriptLocation: 'inlineScript'
              inlineScript: |
                az deployment group create \
                  --resource-group $(resourceGroup) \
                  --template-file infra/main.bicep \
                  --parameters imageTag=$(Build.SourceVersion)

          - task: AzureWebAppContainer@1
            displayName: 'Restart App Service'
            inputs:
              azureSubscription: 'Azure-ServiceConnection'
              appName: $(appName)
```

**Service Connection**: Create an Azure Resource Manager service connection with Workload Identity Federation.

### Option B: GitHub Actions

#### Workflow (`.github/workflows/deploy.yml`)

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]

env:
  RESOURCE_GROUP: openchargeback-rg
  ACR_NAME: focusbillingprodacr
  APP_NAME: openchargeback-prod

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Build and push to ACR
        run: |
          az acr build \
            --registry ${{ env.ACR_NAME }} \
            --image openchargeback:${{ github.sha }} \
            --image openchargeback:latest \
            --file docker/Dockerfile \
            .

      - name: Deploy Bicep
        uses: azure/arm-deploy@v2
        with:
          resourceGroupName: ${{ env.RESOURCE_GROUP }}
          template: ./infra/main.bicep
          parameters: imageTag=${{ github.sha }}

      - name: Restart App Service
        run: az webapp restart --name ${{ env.APP_NAME }} --resource-group ${{ env.RESOURCE_GROUP }}
```

#### GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Target subscription |

## Secrets Management

### Key Vault Secrets to Create

| Secret Name | How to Generate |
|-------------|-----------------|
| `web-secret-key` | `openssl rand -base64 32` |
| `acs-connection-string` | Copy from ACS resource in Azure Portal |

Create secrets via CLI:

```bash
az keyvault secret set --vault-name openchargeback-prod-kv \
  --name web-secret-key --value "$(openssl rand -base64 32)"

az keyvault secret set --vault-name openchargeback-prod-kv \
  --name acs-connection-string --value "<your-connection-string>"
```

## Azure Communication Services Setup

1. Create an ACS resource in the Azure Portal
2. Navigate to **Email** > **Domains**
3. Add your custom domain and verify via DNS:
   - TXT record for domain ownership
   - SPF, DKIM, DMARC records
4. Create a sender address (e.g., `noreply@billing.example.edu`)
5. Copy the connection string to Key Vault

**Note**: Domain verification can take up to 48 hours.

## Custom Domain (Optional)

1. In Azure Portal, go to your App Service > **Custom domains**
2. Add your domain
3. Verify ownership via DNS TXT record
4. Add CNAME pointing to `<app-name>.azurewebsites.net`
5. Enable managed certificate (free SSL)

## Initial Setup Steps

1. **Create Resource Group**:
   ```bash
   az group create --name openchargeback-rg --location eastus
   ```

2. **Deploy Infrastructure**:
   ```bash
   az deployment group create \
     --resource-group openchargeback-rg \
     --template-file infra/main.bicep
   ```

3. **Add Secrets to Key Vault** (see Secrets Management above)

4. **Create First Admin User**: SSH into the container or use the CLI to create the initial user, or pre-populate via config.yaml.

5. **Configure CI/CD**: Set up your Azure DevOps or GitHub Actions pipeline with the appropriate service connections.

## Monitoring

View logs in Azure Portal under **App Service** > **Log stream**, or query via CLI:

```bash
az webapp log tail --name openchargeback-prod --resource-group openchargeback-rg
```

Enable Application Insights for advanced monitoring (optional, adds ~$2-5/month).

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Bicep Infrastructure | 2-3 hours |
| ACS Email Provider | 2-4 hours |
| CI/CD Pipeline | 1-2 hours |
| Secrets & Config | 1 hour |
| Domain/Email Setup | 2-4 hours (DNS wait) |
| **Total** | **8-14 hours** |
