# Bring Your Own (BYO) models to Microsoft Discovery

## Introduction and Purpose

The Microsoft Discovery platform empowers customers to integrate their own machine learning (ML) models into a secure environment for scientific investigations, research and engineering. This guide provides a step-by-step process for onboarding a custom model into Azure Machine Learning Studio and registering it with Microsoft Discovery.

By following this guide, customers can:

- Seamlessly register models deployed in Azure ML for use within Microsoft Discovery.
- Ensure their models remain private, secure, and accessible for deployment in investigative and engineering workflows.
- Leverage custom models to enhance the effectiveness and outcomes of scientific research and engineering.

## Process Overview

The high-level steps to bring your own model into the Microsoft Discovery platform service are listed below: 

1. Deploy the model in Azure ML by following the instructions [here](https://learn.microsoft.com/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2&tabs=cli)
2. Create the model client tool (action-based tool) by following the steps in this documents in this [folder.](../../../6-tools-models-agents/tools-publishing/) You can see a sample in this [folder.](../../../../6-solutions/tools-and-models/RetroChimera/)

3. Create the [agent](../agents-publishing/b--model-selection-and-prompting-guide.md) which makes use of the model by invoking the model client tool

## Conclusion

By following the steps outlined in this document, customers can integrate their machine learning models into the ***Microsoft Discovery Platform*** environment, ensuring that the models are accessible for use within the platform.

## Next steps

[Create the model client tool](../../../6-tools-models-agents/tools-publishing/)
