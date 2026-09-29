# Install Microsoft Discovery

This guide walks through installing the Microsoft Discovery app. For the conceptual tour, see the [Quick Start](quickstart.md).

The Microsoft Discovery app is a self-contained application available for Windows x64, Windows Arm64, and MacOS Arm. The installer bundles everything it needs to run; you don't have to install an SDK, an IDE, or a runtime.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| **Operating system** | Windows 11 and macOS currently supported. Linux isn't currently supported. |
| **GitHub account** | Required to download releases from this repository. |
| **GitHub Copilot subscription** | Required. Microsoft Discovery drives Copilot to power its conversational and agent capabilities. |
| **Disk space** | ~3 GB free for the install plus additional space for your bookshelves. |
| **Network access at install time** | The installer fetches signed components from Microsoft endpoints. Microsoft Discovery runs locally after install; only specific Agent Plugins call out to the internet. |

### Optional integrations

| Integration | When you'd want it |
| --- | --- |
| **`dx` CLI on PATH** | The installer adds the `dx` CLI to your user PATH automatically. Open a new terminal session if it's not picked up. |

## Step 1 — Download

1. Open the [Discovery download landing page](/README.md) on this repository.
1. Select your platform amongst the **User Installer** options (**x64**, **Arm64**, or **macOS**). Optionally, you can get one previous version from the table below the download options.

## Step 2 — Install

1. Right-click the downloaded installer for your platform.  Select **Run as administrator** to cleanly install.
1. Follow the installer prompts. Defaults are recommended.
1. Launch the application when the installer finishes. On Windows, find it in the Start menu under *Microsoft Discovery*; on Mac in the App Launcher.

## Step 3 — Verify (Optional)

1. Sign in with your **GitHub account** when prompted. Microsoft Discovery uses this to drive your GitHub Copilot subscription.
1. Open a terminal and verify the CLI is available:

   ```powershell
   dx --version
   dx doctor --workspace .
   ```

   `dx doctor` walks every dependency, model route, and provider and tells you exactly what is and isn't ready. A few yellow warnings are normal on a fresh install — for example, `dx` will report no LLM route configured until you've signed in to Copilot or pointed it at Azure OpenAI.

## Step 4 — First run

Continue with the [Quick Start](quickstart.md) to build your first Bookshelf and ask Copilot a domain question.

## Upgrading

New builds are delivered as releases on this repository. To upgrade:

1. Download the latest `Discovery-app-x.y.z-release-platform-arch.exe`.
1. Close Microsoft Discovery.
1. Run the new installer. It updates components in place; your `.discovery/` workspace state is preserved.
1. Re-open Microsoft Discovery and verify with `dx --version`.

> 💡 **Tip.** Watch the [README](/README.md).

## Uninstalling

### Windows (x64, Arm64)
1. Go to **Settings / Apps / Installed apps**.  Search for *Microsoft Discovery*. Select **Uninstall**.
1. (Optional) Remove your workspace state by deleting the `.discovery/` folder inside any project where you used Microsoft Discovery.
1. (Optional) If you used the VS Code integration, search the Extensions panel for any *Microsoft Discovery* entries and disable or remove them.

### macOS
1. Open **App Launcher** or a **Finder** instance and select **Applications**.
1. Find the **Discovery** application and select.
1. Drag to **Trash** icon on the desktop or in **Finder**.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| Installer fails with a permission error | Re-run the installer as administrator. |
| Microsoft Discovery won't sign you in | Confirm your GitHub Copilot subscription is active. |
| `dx` not found on `PATH` | Open a new terminal session (the installer adds `dx` to the user `PATH`). If still missing, sign out / sign in. |
| `dx doctor` reports an LLM route warning | Expected on first run. Sign in to Copilot in Microsoft Discovery, or run `dx workspace config llm set-azure-openai …`. Local embedding still works without this. |
| Anything else | Run `dx doctor --workspace .` and include its output when you [file a bug in Discussions](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions). |
