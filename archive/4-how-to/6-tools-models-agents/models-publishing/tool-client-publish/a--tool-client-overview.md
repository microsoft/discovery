# Overview

Before a model can be used in the Microsoft Discovery Platform, a **Model Client Tool (MCT)** must first be deployed. The MCT acts as the interface between the platform and the AI model’s inferencing endpoint, enabling automated interaction and data exchange.

At its core, the Model Client Tool is an **action-based component** designed to send REST API requests to the published model’s inferencing endpoint, retrieve prediction results, and store or forward those results as needed for downstream processing. It serves as the operational bridge that allows models hosted externally—such as in Azure ML or other environments—to be seamlessly accessed within the Discovery Platform ecosystem.

Developing and deploying a Model Client Tool involves several key stages to ensure it functions correctly and integrates smoothly with the platform. The process can be summarized in four main steps:

1. **Create the Action Script**
   Develop a script that defines how the tool interacts with the model endpoint. This script should handle request formatting, authentication, API calls, and result parsing. It effectively encapsulates the model’s inference logic in a reusable and platform-compatible form. You can find a sample [here](b--tool-client-script.md).
   
   Details for creating action scirpts can be found [here](../../tools-publishing/b--writing-action-scripts.md)

2. **Generate a Dockerfile**
   Containerize the action script by creating a Dockerfile. This defines the runtime environment, dependencies, and configuration required to run the MCT consistently across compute environments. Details for generating a Docker file can be found [here](../../tools-publishing/c--generate-docker-file.md)

3. **Publish the Docker Image to Azure Container Registry (ACR)**
   Build the Docker image locally or via CI/CD pipelines and publish it to your designated Azure Container Registry. This ensures that the Discovery Platform can pull the image securely and deploy it as needed. Details for publishing image to ACR can be found [here](../../tools-publishing/d--create-validate-publish-tools-to-acr.md)

4. **Create the Tool Definition**
   Register the client tool in the platform by creating a tool definition. This definition provides the metadata—such as input/output schemas, container image path, and execution parameters—needed for Discovery to recognize and execute the MCT as part of workflows or pipelines. Sample tool definition file can be found [here](../../models-publishing/external-models/2-common/model-definition.md)
   
   More details about tool definition files can be found [here](../../tools-publishing/e--create-tool-definition.md)

Once deployed, the Model Client Tool enables seamless integration of AI model inferencing into Discovery workflows, ensuring scalable, repeatable, and governed model usage across teams and environments by being available to [agents](../../../6-tools-models-agents/c--agent-deployment.md) in Microsoft Discovery.
