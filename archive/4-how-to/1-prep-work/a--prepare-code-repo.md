# Preparing the Code Repository

This article is intended for ISVs, or customers preparing for Bring Your Own (BYO) scenarios on Microsoft Discovery platform.

The document outlines best practices for onboarding and maintaining repositories to enable easy discovery, versioning, and maintenance of your tool, model and agent templates.

As a publisher you may wish to leverage any of the approaches below:

## Approach-1. Create a New Git Repository

Set up a new repository to store your tools and model templates for streamlined discovery and collaboration.

**Steps:**

1. **Initialize a new repository** on your preferred Git hosting service (e.g., GitHub, Azure Repos, GitLab):

    ```bash
    # Create a new directory for your project
    mkdir discovery-templates
    cd discovery-templates

    # Initialize a new git repository
    git init

    # Add a remote (replace with your repository URL)
    git remote add origin https://github.com/your-org/discovery-templates.git
    ```

2. **Add a folder named `<tool-name>`** and organize your content within it:

    ```bash
    mkdir <tool-name>
    cd <tool-name>
    mkdir tools models agents
    # Add your files to the respective directories
    ```

3. **Stage, commit, and push your changes:**

    ```bash
    git add .
    git commit -m "Initial commit: add <tool-name> with tools, models, and agents"
    git push -u origin main
    ```

4. **Share the repository link** with your team or organization as needed.

## Approach-2. Fork Microsoft Discovery repo

If you want to build upon an existing Microsoft Discovery repository (<https://github.com/microsoft/discovery>):

**Steps:**

1. **Navigate to the repository page** (<https://github.com/microsoft/discovery>).

2. **Click the "Fork" button** to create your own copy.

3. **Clone your forked repository** to your local machine:

    ```bash
    git clone https://github.com/your-username/discovery.git
    cd discovery
    ```

4. **Add your tools and models** to the appropriate directories (`tools`, `models`, `agents`) within the `<tool-name>` folder.

    ```bash
    mkdir <tool-name>
    cd <tool-name>
    mkdir tools models agents
    # Add your files to the respective directories
    ```

5. **Stage, commit, and push your changes:**

    ```bash
    git add .
    git commit -m "Add custom tools, models and agents"
    git push
    ```

6. **Maintain your fork** for adding tools, models and agents, required for your organization.

> **Note:** If you are a Microsoft internal user, you may use Approach-2 to contribute tools, models, and agents that are suitable for customer use.
