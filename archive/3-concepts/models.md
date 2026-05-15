# Microsoft Discovery Models

Microsoft Discovery platform is an Azure-based platform designed to accelerate scientific research, science and engineering by leveraging artificial intelligence (AI), high-performance computing (HPC), and future quantum computing capabilities. The platform aims to provide a user-friendly and adaptive experience driven by a conversational AI agent, alongside a curated set of specialized AI models, agents, and tools. Powered by cloud-native and hybrid HPC solutions for inferencing and simulations, this technology targets high-value tasks with a primary focus on concrete scientific use cases.

This document offers a detailed overview of Machine Learning (ML) and AI models in Microsoft Discovery along with the core concepts.

## Models Overview

### What are Models in Microsoft Discovery?

Models in Microsoft Discovery are specialized AI and ML components that drive intelligent analysis, prediction, and reasoning within scientific and engineering workflows. They serve as foundational building blocks that power agent-driven computation, scientific data interpretation, hypothesis generation, and decision-making across the research and development lifecycle.

Customers can either leverage pre-integrated models available in the AI Foundry Catalog or onboard their own models to tailor the platform to their specific needs.

### Supported Deployment

AI Foundry catalog is a hub for discovering, evaluating, customizing, and deploying AI models at scale. It serves as a central repository for foundation models curated by Microsoft and Partner Model Providers. Microsoft Discovery currently supports only Managed Compute (MaaP) deployments.

- **Managed Compute (MaaP)** based model deployment allows users to deploy and manage their own models on dedicated compute resources within Azure ML Workspace. This approach provides greater flexibility and control over the model environment, enabling custom configurations, dependency management, and integration with enterprise data sources.

## Core Concepts

This section outlines the foundational concepts that underpin models in the Microsoft Discovery platform. Understanding these core elements is essential for effectively navigating, building, and operating within the system.

### Model Resource

A Model Resource in the Microsoft Discovery platform is a logical representation of an AI/ML model associated with Microsoft Discovery project. It is created and managed through the Azure Portal.

This resource stores essential metadata—such as the model definition and the associated Discovery workspace ID—which links to the underlying machine learning workspace used for deployment. By centralizing this information, the model resource helps standardize and streamline model deployment across the Discovery platform.

Each model resource includes references to:

1. Model Definition
2. Model Image(s)
3. Model Catalog (AI Foundry)

### Model Definition

Model Definitions in Microsoft Discovery are declarative YAML-based configuration files that describe how models should be deployed, configured, and managed within the platform. They provide a standardized structure for defining model metadata, infrastructure requirements, and deployment parameters—ensuring consistent, reproducible deployments across various environments.

These definitions form the backbone of scalable and governed model deployment in Microsoft Discovery, enabling teams to manage complex AI workloads with efficiency and consistency.

Once authored by the model publisher, a model definition becomes a required input for creating a model resource in Microsoft Discovery.

### Model Images

Model Images provide a standardized method for packaging and distributing machine learning models. Typically delivered as containerized artifacts (e.g., Docker images), they bundle the model code, dependencies, and runtime environment needed for inference or training. This containerized approach ensures consistency, portability, and reproducibility across various deployment environments.

The following type of model images are supported:

- **Container Images:** Models can be packaged as Docker container images, encapsulating all necessary code, dependencies, and runtime environments for execution. This method ensures consistent behavior across different environments and streamlines deployment, scaling, and integration within the Microsoft Discovery platform. Containerized models are especially well-suited for complex workloads with custom dependencies or scenarios that require fine-grained control over the execution environment.

- **MLFlow Models Images:** AI Foundry also supports models packaged in the MLflow format—a widely adopted open-source standard for managing the full machine learning lifecycle. MLflow models can be easily logged, versioned, and deployed, making them well-suited for conventional ML workflows. Microsoft Discovery can natively interpret MLflow artifacts, simplifying onboarding and deployment for teams already leveraging MLflow in their development pipelines.

### Model Catalog (AI Foundry)

AI Foundry Model Catalog serves as a centralized repository for scientific models, making it easy for researchers and teams to discover, evaluate, and onboard models relevant to their domain. It provides detailed metadata, versioning, and documentation for each model, enabling informed decision-making and streamlined integration into research workflows.

Researchers can browse and search the Model Catalog using filters such as scientific domain, model type, or performance metrics. Each model entry includes detailed documentation, usage instructions, and deployment options.

While several models are readily available in the catalog, organizations interested in publishing their own models and making them publically accessible should contact Microsoft for publishing support.

Example addition: ASIC design verification models can be integrated to accelerate timing analysis or power estimation workflows.
