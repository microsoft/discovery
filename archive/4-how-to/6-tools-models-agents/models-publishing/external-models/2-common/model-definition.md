**Sample Model definition YAML file**

```json
{
    "name": "model1",
    "version": 1,
    "description": "Description of Model.",
   "infra": [
     {
       "infraType": "maap",
       "image": {
      "modelId": "azureml://registries/azureml/models/model1/versions/1"
       },
       "compute": {
        "instanceType": "Standard_NC40ads_H100_v5",
        "poolType": "static",
        "poolSize": 1
       }
     }
   ]
}