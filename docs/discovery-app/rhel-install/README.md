# Install Microsoft Discovery on RHEL

Use [`install-discovery-app.sh`](install-discovery-app.sh) to install the
Microsoft Discovery app from a Preview RHEL x64 RPM.

## Requirements

- RHEL, AlmaLinux, or Rocky Linux 9 or later on `x86_64`.
- A graphical desktop session.
- A normal user account with `sudo` access.
- The current Preview RHEL x64 Discovery App RPM.
- An active GitHub Copilot subscription with Copilot CLI enabled by the
  organization or enterprise administrator.

Run Microsoft Discovery and GitHub Copilot as your normal desktop user, never
with `sudo`.

## Install

Download the current Preview RHEL x64 RPM and preserve its published filename,
then download the installer:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/microsoft/discovery/main/docs/discovery-app/rhel-install/install-discovery-app.sh \
  --output install-discovery-app.sh
chmod +x install-discovery-app.sh
```

Review the script, then run:

```bash
./install-discovery-app.sh --rpm ./discovery-app-preview-VERSION-RELEASE.x86_64.rpm
```

`--rpm PATH` is the only required argument. You do not need to provide a
checksum. The installer downloads the current Preview release manifest from:

```text
https://raw.githubusercontent.com/microsoft/discovery/main/docs/discovery-app/releases/manifests/preview.json
```

It extracts `platforms.rhel-x64.sha256`, computes the SHA-256 of the supplied
RPM, and stops before making system changes if the values do not match.

Release manifests may optionally include `platforms.rhel-x64`. This entry
requires a lowercase 64-character SHA-256 and an HTTPS `installerUrl`, or the
exact `PLACEHOLDER_PENDING_PUBLISH` value while the download URL is pending.
The placeholder is permitted only for RHEL and is not a download URL; continue
to supply the RPM locally with `--rpm`. The macOS and Windows entries remain
required and retain their fixed HTTPS download URLs.

The installer also validates the RPM package name, architecture, and trusted
signature before installation.

## Optional arguments

| Argument | Purpose |
| --- | --- |
| `-y`, `--yes` | Accept the installation plan noninteractively. |
| `--signing-key PATH` | Import an explicitly approved alternate RPM signing key. Not required for official Microsoft-signed RPMs. |
| `--setup-mode automatic` | Configure dependencies and install the RPM. This is the default. |
| `--setup-mode prompt` | Ask whether to use automatic or manual setup. |
| `--setup-mode manual` | Make no system changes and print the manual setup location. |

Official Discovery App RPMs are signed by Microsoft. For a standard
installation, do not pass `--signing-key`; the installer retrieves and imports
Microsoft's published signing key automatically.

For example:

```bash
./install-discovery-app.sh \
  --yes \
  --rpm ./discovery-app-preview-VERSION-RELEASE.x86_64.rpm
```

The installer:

1. Retrieves the expected RHEL x64 SHA-256 from the Preview release manifest.
2. Validates the supplied RPM checksum, package metadata, architecture, and
   trusted signature.
3. Configures required Microsoft repositories when needed.
4. Installs ASP.NET Core Runtime, Visual Studio Code, and GitHub Copilot CLI
   when they are not already available.
5. Installs the RPM and verifies the installed application.

## Configure and launch

Authentication is deferred until first use. Configure GitHub Copilot as your
normal desktop user:

```bash
discovery-app-preview --configure-copilot
```

Launch Microsoft Discovery:

```bash
discovery-app-preview --mode science
```

## Troubleshooting

| Problem | Resolution |
| --- | --- |
| Preview manifest cannot be downloaded | Confirm the manifest has been published to the repository `main` branch and that GitHub is reachable over HTTPS. |
| RPM SHA-256 mismatch | Download the current Preview RHEL x64 RPM again. Older RPMs intentionally fail after the manifest advances. |
| Unsupported architecture or distribution | Use RHEL, AlmaLinux, or Rocky Linux 9 or later on `x86_64`. |
| RPM signature reports `NOKEY` | Obtain the approved public key through the trusted release channel and pass it with `--signing-key`. |
| `sudo` is unavailable | Ask an administrator to perform the system package installation. |
| GitHub Copilot CLI is unavailable | Confirm outbound HTTPS access to `gh.io` and that Copilot CLI is enabled for the account. |

Do not use `--nogpgcheck` or install an RPM whose checksum or trusted signature
cannot be verified.

For product questions and feedback, use the
[Microsoft Discovery community forum](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions).
