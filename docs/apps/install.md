# Install Microsoft Discovery

This guide walks through installing, verifying, upgrading, and removing the Microsoft Discovery app. For the conceptual tour, see the [Quick Start](quickstart.md).

The Microsoft Discovery app is a **self-contained Windows application**. The installer bundles everything it needs to run; you don't have to install an SDK, an IDE, or a runtime.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| **Operating system** | Windows (Windows 11 recommended). macOS and Linux are not currently supported. |
| **GitHub account** | Required to download releases from this repository. |
| **GitHub Copilot subscription** | Required. Microsoft Discovery drives Copilot to power its conversational and agent capabilities. |
| **Disk space** | ~3 GB free for the install plus headroom for your bookshelves. |
| **Network access at install time** | The installer fetches signed components from Microsoft endpoints. Microsoft Discovery runs locally after install; only specific Agent Plugins call out to the internet. |

### Optional integrations

| Integration | When you'd want it |
| --- | --- |
| **Visual Studio Code** | Microsoft Discovery ships a VS Code integration (sidebar tree, Copilot Chat tools, agent plugin host). It's optional — the app runs as a standalone Windows app without it. Install the [latest stable VS Code](https://code.visualstudio.com/) if you want this surface. |
| **`dx` CLI on PATH** | The installer adds the `dx` CLI to your user PATH automatically. Open a new terminal session if it's not picked up. |

## Step 1 — Download

1. Open the [latest release](https://github.com/microsoft/discovery/releases/latest) on this repository.
2. Under **Assets**, download `DiscoveryExpressSetup-x.y.z.exe` (the version number changes per release).
3. Verify the SHA-256 digest shown next to the asset matches the file you downloaded:

   ```powershell
   Get-FileHash .\DiscoveryExpressSetup-x.y.z.exe -Algorithm SHA256
   ```

## Step 2 — Install

1. Right-click the downloaded `.exe` → **Run as administrator** (recommended so the `dx` CLI and VS Code components register cleanly for all users).
2. Follow the installer prompts. Defaults are recommended.
3. Microsoft Discovery launches when the installer finishes — or find it in the Start menu under *Microsoft Discovery*.

## Step 3 — Verify

1. **Open Microsoft Discovery** from the Start menu (or wait for it to launch after install).
2. Sign in with your **GitHub account** when prompted. Microsoft Discovery uses this to drive your GitHub Copilot subscription.
3. Open a terminal and verify the CLI is available:

   ```powershell
   dx --version
   dx doctor --workspace .
   ```

   `dx doctor` walks every dependency, model route, and provider and tells you exactly what is and isn't ready. A few yellow warnings are normal on a fresh install — for example, `dx` will report no LLM route configured until you've signed in to Copilot or pointed it at Azure OpenAI.

4. **(Optional) If you installed VS Code:** open it and confirm the **Microsoft Discovery** icon appears in the Activity Bar (the vertical strip on the left). Sign in to GitHub Copilot in VS Code if you haven't already.

## Step 4 — First run

Continue with the [Quick Start](quickstart.md) to build your first Bookshelf and ask Copilot a domain question.

## Upgrading

New builds are delivered as releases on this repository. To upgrade:

1. Download the latest `DiscoveryExpressSetup-x.y.z.exe`.
2. Close Microsoft Discovery (and VS Code, if you use the integration).
3. Run the new installer. It updates components in place; your `.discovery/` workspace state is preserved.
4. Re-open Microsoft Discovery and verify with `dx --version`.

> 💡 **Tip.** Watch [Releases](https://github.com/microsoft/discovery/releases) (top-right of the repo → **Watch → Custom → Releases**) to be notified when a new build is published.

## Uninstalling

1. **Settings → Apps → Installed apps** → search for *Microsoft Discovery* → **Uninstall**.
2. (Optional) Remove your workspace state by deleting the `.discovery/` folder inside any project where you used Microsoft Discovery.
3. (Optional) If you used the VS Code integration, search the Extensions panel for any *Microsoft Discovery* entries and disable or remove them.

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| Installer fails with a permission error | Re-run the installer as administrator. |
| Microsoft Discovery won't sign you in | Confirm your GitHub Copilot subscription is active. |
| `dx` not found on `PATH` | Open a new terminal session (the installer adds `dx` to the user `PATH`). If still missing, sign out / sign in. |
| `dx doctor` reports an LLM route warning | Expected on first run. Sign in to Copilot in Microsoft Discovery, or run `dx workspace config llm set-azure-openai …`. Local embedding still works without this. |
| (VS Code only) No Microsoft Discovery icon in the Activity Bar | Restart VS Code. If still missing, re-run the installer. |
| Anything else | Run `dx doctor --workspace .` and include its output when you [file a bug in Discussions](https://github.com/microsoft/discovery/discussions/categories/bugs). |
