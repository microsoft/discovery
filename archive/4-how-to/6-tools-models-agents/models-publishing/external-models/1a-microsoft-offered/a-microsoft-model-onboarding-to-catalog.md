# Publish an Internal Microsoft Model to Azure ML Catalog

## **Step-by-Step Guide Using the SDK**

This document will walk you through the steps to set up and use the model onboarding SDK to effectively publish a model to the Azure Machine Learning (ML) Calatog.

### **1**. Create a Registry

 [Create a registry](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-registries?view=azureml-api-2&tabs=studio#create-a-registry) in your tenant where you will upload the model weights you want to share with Microsoft for operations like baselining, validations and eventually Prod Deployment. Make sure you add the SkipAutoDeleteTill (YYYY-MM-DD) and owner tags.  
    **Registry must have a primary or additional region as `EastUS`**

### **2**. Provide Publisher Details

 Below is sample detail of a publisher. Change each of the fields corresponding to new Publisher details and share it with you Microsoft onboarding contact in an email for onboarding. Microsoft DRI will create the publisher details in the background and respond back when Publisher will be onboarded.

```json
{        
    "PublisherName": "<your publisher name>",
    "DisplayName": "<your display name>",
    "Description": "<your description>",
    "Website": "<Not mandatory>",
    "Publisherid": "<Not mandatory>",
    "Sellerid": "<Not mandatory>",
    "AuthorisedSecurityGroups": {
        "<your sg name@msft>": "<oid of the sg>"
        }
}
```

### **3**. Install the Azure ML Extension for CLI

Once the onboarding is successful, install the az ml extension for CLI using latest whl file. 
[Use the latest whl file from here.](https://microsoftapc.sharepoint.com/:u:/t/MaaSIDCDevs/EWqwbEp84w1OvtOWC2jLpeQBA6yDOl-754YOGPS3p1-O-w?e=zPmBl4)

- Azure CLI (ignore if already installed) -> [Install the Azure CLI for Windows | Microsoft Learn](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?tabs=azure-cli)
- Remove existing extension `az extension remove -n ml`
- Download ML extension wheel file from the above link:

> Note:  az upgrade will replace this version as 0.x version is used so upgrade will pickup new version. For installing again please use this process remove and add extension again

- Install ml extension private preview `az extension add -s "Path to wheel file`"

check CLI running with `az ml modelpublisher show --help`

- if you get a Marshmallow dependency error then run this fix otherwise skip.
  - Run this python script to fix the marshmallow error [install-marshmellow.py](https://microsoftapc.sharepoint.com/:u:/t/MaaSIDCDevs/ETHvNAhvZbRPjl1YQ_tBt3gBn_b7vuTA7oKeMynOsgmh9g?e=dkzOwc)
   `python path/to/install-marshmellow.py`

- Ensure that you are logged in for next step `az login`

### **4**. View Publisher Details

To view the Publisher Details in CLI use the following command:

```azurecli
az ml modelpublisher show -p { } 
    
    Arguments
        --publisher -p [Required] : Name of the publisher
```

### **5**. Update Publisher Details

 To update the Publisher Details in CLI, use the following command:

```azurecli
az ml modelpublisher update -p { } -n { } -d {} -w { }
    
    Arguments
        --publisher -p [Required] : Name of the publisher
        --description -d          : Description of the publisher
        --name -n                 : Display name of publisher
        --website -w              : Website of the publisher
```

### **6**. Share Registry Details

Run the below command to share the source registry details with Microsoft

```azurecli
az ml modelpublisher registry set -p {} -f sample-registry.yaml
    
    Arguments
        --publisher -p [Required] : Name of the publisher
```

sample-registry.yaml

```yml
name: "<registryname>"
location: "eastus"             
subscriptionId: "4f26493f-21d2-4726-92ea-1ddd550b1d27"
```

Meanwhile, the Microsoft DRI will create the destination reg in the background and setup registry syndication. Check the status of registry setup via Publisher Details in Step 4.

### **7**. Onboard Model Details

Run the below CLI command to onboard Model Details to Self Serve

```azurecli
az ml modelpublisher model create -p {} -m {} -f sample-model.yaml
    
    Arguments
        --publisher -p [Required] : Name of the publisher
        --model     -m [Required] : Model name
```

sample-model.yaml

```yml
displayName: "VerboGenie"
description: "VerboGenie, the most powerful language model for its size to date."
taskType: "ChatCompletion"
```

### **8**. Update Model Details

Run the below CLI command to Update Model Details

```azurecli
az ml modelpublisher model update -p {} -m {} -f sample-update-model.yaml
    
    Arguments
        --publisher -p [Required] : Name of the publisher
        --model     -m [Required] : Model name
```

  sample-update-model.yaml

```yml
displayName: "VerboGenie"
description: "VerboGenie, the most powerful language model for its size to date."
```

### **9**. Upload the Model

[Upload the model in the registry](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-models?view=azureml-api-2&tabs=cli) you created in Step 1 along with the description.

### **10**. Create Release Candidate

Run the following command to provide the model asset reference of the model you just uploaded

```azurecli
az ml modelpublisher release-candidate create -p {} -m {} -f sample-model-version.yaml
    
    Arguments
        --publisher -p [Required] : Name of the publisher
        --model     -m [Required] : Model name
```
  
  Depending on the deployment type, create a YAML file with the appropriate content.  

 a. For deployment type "**MaaS**"

```yml
modelAssetReference: "azureml://registries/<registryname>/models/<ModelName>/versions/<version>"
deploymentTemplateReference: "azureml://registries/<registryname>/deploymenttemplates/<deploymenttemplatesName>/versions/<version>"
environmentReference: "<Not mandatory>"
isStreaming: "false"
```

b. For deployment type "**MaaP**"
  
```yaml
modelAssetReference: "azureml://registries/Phi-test/models/phi-4-reasoning-maap/versions/1"  
isStreaming: "false"  
deploymentType: "MaaP"  
sku: "Standard_NC24ads_A100_v4"  
inferencePayload: "{ \"input_data\": { \"input_string\": [\"Sample input string for testing.\"] } }"  
inferenceResponse: "{0: \"Sample response text for the input string.\"}"
```

**Note:** For Deployment Type MaaS please make sure DestinationRegistry is created and for deployment type MaaP make sure the NonIppDestinationRegistry is created for publisher.

### **11**. View Release Candidate Details

To view the release-candidate details of a model for a specific version, use the below command:

```azurecli
az ml modelpublisher release-candidate show -p {} -m {} -v {}
```

### **12**. List All Release Candidates

To view the list of all release-candidates' details, use the below command:

```azurecli
az ml modelpublisher release-candidate list -p {} -m {} -s {} --page {}
```

### **13**. Download Validation Results

Downloads validation results for the specified release candidate for a given validation id:

```azurecli
az ml modelpublisher release-candidate download-validation-result -p {} -m {} -v {} -vid {}
    
    Arguments:
    --publisher -p [Required] : Name of the publisher
    --model     -m [Required] : Model name
    --validation-id -vid [Required] : Id of the validation run.
    --version -v         [Required] : Version of the model.
```

Example -

```json
"validationResult": [
    {
      "createdTime": "2025-04-17T08:39:50Z",
      "id": "cd305034-3fb9-4d7b-8e51-cd27266fb81c",
      "message": "Validation run data captured successfully",
      "runId": "e4c823ae-e144-4a85-a33f-3b48a9b86e51",
      "sku": "Standard_NC24ads_A100_v4",
      "status": "Completed",
      "type": "API_VALIDATION",
      "updatedTime": "2025-04-17T09:22:55Z",
      "validationResultUrl": "https://selfservevalidation.blob.core.windows.net/azureml-validation-results/Fabrikam3/VerboGenie-embed-4/5/cd305034-3fb9-4d7b-8e51-cd27266fb81c/Commonbench-2025-04-17-09-21-00-753/api_validations/api_validation_result.csv"
    },
```

```azurecli
 az ml modelpublisher release-candidate download-validation-result -p Fabrikam3 -m VerboGenie-embed-4  --version 5 -vid cd305034-3fb9-4d7b-8e51-cd27266fb81c
```

### **14**. Troubleshooting Failed Validations

If your validation fails, the response will show a "**Failed**" status with an error message. 
For example:

```json
"validationResult": [
    {
        "createdTime": "2025-04-17T08:39:50Z",
        "id": "cd305034-3fb9-4d7b-8e51-cd27266fb81c",
        "message": "Deployment failed due to asset-related issue. Please check deployment failure logs",
        "sku": "Standard_NC24ads_A100_v4",
        "status": "Failed",
        "type": "API_VALIDATION",
        "updatedTime": "2025-04-17T09:22:55Z",
    }
]
```

When validation fails due to deployment issues, you can download the deployment logs to investigate the root cause:

```azurecli
az ml modelpublisher release-candidate download-deployment-logs -p {} -m {} -v {} -vid {}

    Arguments:
    --publisher -p       [Required] : Name of the publisher.
    --model     -m       [Required] : Model name.
    --validation-id -vid [Required] : Id of the validation run.
    --version -v         [Required] : Release candidate version.
```

Example command to download deployment logs:

```azurecli
az ml modelpublisher release-candidate download-deployment-logs -p Fabrikam3 -m VerboGenie-embed-4  --version 5 -vid cd305034-3fb9-4d7b-8e51-cd27266fb81c
```

This command will download the deployment logs locally, allowing you to examine the detailed error messages and identify what caused the validation failure.

### **15**. Promote to Production

Promote a specific release candidate of the model to production:

```azurecli
az ml modelpublisher release-candidate promote-to-prod -p {} -m {} -v {}

    Arguments:
    --publisher -p [Required] : Name of the publisher
    --model     -m [Required] : Model name
    --version -v   [Required] : Version of the model.
```

## Next Steps

[Onboard Model to Microsoft Discovery](b-microsoft-model-onboarding-to-discovery.md)
