# Microsoft Discovery Tools

Microsoft Discovery brings together advanced AI and high-performance computing to accelerate research and development. Its core components—tools, models, and agents—form an integrated ecosystem that supports every stage of the scientific process, including knowledge mining, hypothesis generation, execution, simulation, analysis, and design.

This documentation provides a comprehensive overview of Microsoft Discovery tools, explaining their types, required artifacts, and deployment processes within the platform's enterprise-grade R&D environment.

## Tools Overview

### What are Tools in Microsoft Discovery?

Tools in Microsoft Discovery are specialized functionalities that enable specific scientific or engineering operations, data processing, or interactions with external systems. They enhance the capabilities of AI models and agents by providing them with additional capabilities to perform complex research and development tasks that would otherwise be difficult or impossible within a standard computing environment.

Within the Microsoft Discovery platform, various scientific tools serve distinct yet complementary purposes, enabling researchers and engineers to execute a broad spectrum of R&D workflows efficiently and securely.

- **Computational tools** are fundamental in scientific research, providing the necessary algorithms and high-performance computing capabilities to solve complex mathematical problems, simulate physical phenomena or engineering systems, and analyze large scientific datasets.
- **Data Processing tools** are essential for managing and refining data collected from various research sources. They allow scientists and engineers to extract relevant information, remove noise, and preprocess data for further analysis within the Discovery platform.
- **Simulation tools** help model and simulate physical, chemical, or biological processes and complex engineered systems using the platform's Supercomputer resources. These tools are crucial for experiments that cannot be conducted in real-time due to constraints such as time, cost, or safety concerns.
- **Visualization tools** are indispensable for interpreting scientific data or engineering design data, and communicating findings effectively. These tools transform raw research data into graphical representations like charts, graphs, and 3D models, making it easier to identify patterns, trends, and anomalies.

Microsoft Discovery supports both **Open-source** and **Proprietary** tools integration. In either case, to deploy a tool to the platform, you need to package the tool in a container image and provide appropriate tool definitions (covered in subsequent sections) to deploy them on the Microsoft Discovery platform.

## Tool Types

The scientific tools in Microsoft Discovery can be classified into the following tool types:

- **Code Environment:** A code environment-based tool enables the Microsoft Discovery Copilot to generate and run code dynamically in a specified programming language compatible with the tool's container image. This approach works best for tools with comprehensive documentation covering usage patterns and syntax, allowing Copilot to create code dynamically. Both open-source and proprietary tools can use this approach if the publisher provides sufficient contextual information for the language model to generate appropriate code. Documentation should include sample code examples and instructions for submitting tasks to the tool.

- **Action-based:** This type is most appropriate when tool publishers wish to expose specific predefined functions rather than enabling dynamic code generation. It's particularly suitable for proprietary tools where publishers may prefer not to provide extensive documentation but instead include pre-built action scripts within the container image. The Microsoft Discovery Copilot is made aware of these exposed actions and can invoke them based on the research scenario at hand.

- **Combined Code Environment and Action-based:** Some tools may benefit from a hybrid approach, where certain operations use well-defined actions with scripts embedded into container images, while others use a code environment where scripts are dynamically generated through the platform's AI capabilities.

For any of the tool types mentioned above, publishers must provide a container image that packages all required dependencies and tool binaries. For action-based tools, publishers additionally need to include scripts (for pre-defined actions) within the container image.

An example of a code environment-based tool is the molToolkit sample, a comprehensive molecular analysis toolkit for cheminformatics and molecular modeling with rich Python libraries. Conversely, an example of an action-based tool is molecularGroups, which provides predefined actions for identifying functional groups and screening for hazardous compounds.

As a publisher, you may also want to integrate SaaS tools that expose OpenAPI endpoints. For such SaaS tools or models with OpenAPI endpoints, Microsoft Discovery recommends creating a client container image that leverages the User Assigned Managed Identity (UAMI) supplied during workspace creation to make secure OpenAPI calls within the platform's environment.

**Why use a client container for SaaS services or models with OpenAPI endpoints?**

Within the Microsoft Discovery platform, a client container approach offers several advantages for SaaS integration:

- Enables seamless scientific data integration, allowing for efficient handling and transformation of research data assets.
- Supports long-running scientific operations by managing complex computational tasks within the tool container, rather than relying solely on HTTP requests.
- Facilitates extensive scientific data processing that may not be practical within standard HTTP payloads, especially when orchestrated by Discovery Agents.
- Provides a unified and secure environment for integrating external tools with other services or tools in the Microsoft Discovery platform.
- Manages job batching and submission logic to the OpenAPI endpoint, improving reliability and scalability for scientific workflows.

## Tool Artifacts

### Tool Images

During the private preview, the Microsoft Discovery platform supports container-based tool images. Whether tools are provided by Microsoft, independent software vendors (ISVs), or customers through Bring Your Own (BYO) scenarios, integrating these containerized images into the enterprise-grade Microsoft Discovery environment is essential for creating streamlined scientific computing workflows.

Tool publishers must provide container images that include all necessary scientific libraries, binaries, SDKs, and dependencies for the tool to operate independently within the high-performance computing environment. This containerized approach ensures consistent performance across research workflows and eliminates dependency conflicts across different computing environments.

### Tool Definition

Tool definitions in Microsoft Discovery describe the purpose and capabilities of a scientific tool, outlining the actions it can perform—whether through predefined scripts, a code environment, or both. Each tool definition includes infrastructure specifications for all supported container images, ensuring compatibility across different computing environments within the platform. For example, a molecular dynamics tool like GROMACS may require multiple container images, some optimized for various high-performance computing (HPC) scenarios and others designed to run on standard compute resources.

For an action-based tool, the tool definition additionally specifies the research actions exposed by the tool. Each action is documented with its name, a clear description, and a JSON schema that defines the expected input parameters for scientific operations. In contrast, for a code-environment based tool, the publisher must provide details such as programming language, description, infrastructure node specifications for executing dynamically generated scripts, and sample commands that the tool accepts.

By providing comprehensive tool definitions, publishers enable the Microsoft Discovery Copilot and Agents to understand how to interact with each scientific tool, generate appropriate execution plans, and orchestrate complex scientific workflows on the Supercomputer. This ensures tools are used effectively and consistently across the Microsoft Discovery platform's R&D workflows.

These definitions, once created by the publisher, form the template that must be provided as part of the Microsoft Discovery Tool resource registration process.

## Tool Deployment

Tool deployment in the Microsoft Discovery platform involves two main architectural components: the control plane and the data plane.

- The **control plane "tool" resource** is an Azure Resource Manager (ARM) resource that you create and manage through the Azure Portal. This resource defines the scientific tool's configuration, metadata, security settings, and deployment parameters within your secure Microsoft Discovery environment.

- The **data plane "tool" resource** refers to the actual running instance of your tool's container on a Microsoft Discovery Supercomputer node. This is where the tool executes scientific workloads and processes research data as part of your end-to-end R&D workflows.

This architectural separation empowers enterprise customers to independently onboard and manage their own tool control resources on the platform, while Microsoft Discovery ensures a seamless, secure, and automated execution experience on the Supercomputer. All tool operations are orchestrated through the Microsoft Discovery Copilot interface, providing researchers with a streamlined and user-friendly workflow for complex scientific computing tasks.
