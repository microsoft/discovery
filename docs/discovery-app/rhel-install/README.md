# Install Microsoft Discovery on RHEL

This directory provides the
[`install-discovery-app.sh`](install-discovery-app.sh) command-line installer
for installing the Microsoft Discovery app from an RPM on supported Enterprise
Linux systems.

## Supported systems

- Red Hat Enterprise Linux 9 or later.
- AlmaLinux 9 or later.
- Rocky Linux 9 or later.
- An `x86_64` system with the current Preview Discovery App RPM.
- A graphical desktop session.
- A normal user account with `sudo` access.
- An active GitHub Copilot subscription with Copilot CLI enabled by the
  organization or enterprise administrator.

Run Microsoft Discovery and GitHub Copilot as your normal desktop user, never
with `sudo`.

## Download the release files

Download the current Preview RHEL x64 RPM from the Microsoft Discovery Preview
release and preserve its published filename:

```text
discovery-app-preview-VERSION-RELEASE.x86_64.rpm
```

The installer downloads the current Preview release manifest over HTTPS and
validates the RPM against `platforms.rhel-x64.sha256`. Do not use an adjacent
checksum sidecar or a package from a different release ring.

Download the installation script:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/microsoft/discovery/main/docs/discovery-app/rhel-install/install-discovery-app.sh \
  --output install-discovery-app.sh
chmod +x install-discovery-app.sh
```

Review downloaded scripts before running them.

## Install from the command line

Run the installer as your normal desktop user:

```bash
./install-discovery-app.sh \
  --rpm ./discovery-app-VERSION-RELEASE.x86_64.rpm
```

Replace the example filename with the RPM you downloaded. The RPM architecture
must match the machine architecture reported by `uname -m`.

The default automatic setup shows an installation plan and asks for confirmation
before making system changes. To accept the plan noninteractively, pass `--yes`
or `-y`:

```bash
./install-discovery-app.sh \
  --yes \
  --rpm ./discovery-app-VERSION-RELEASE.x86_64.rpm
```

The installer:

1. Downloads the current Preview release manifest over HTTPS and validates the
   RPM against its `rhel-x64` SHA-256 digest.
2. Confirms that the RPM contains a supported Discovery App package and matches
   the machine architecture.
3. Imports Microsoft's public package-signing key.
4. Adds Microsoft's .NET and Visual Studio Code repositories only when their
   required packages are not already installed or available.
5. Installs GitHub Copilot CLI only when a working `copilot` executable is not
   already available.
6. Requires a trusted RPM signature before installation.
7. Installs the RPM and verifies the installed files.

For an RPM signed by a key other than Microsoft's published package key, obtain
the public key through the same trusted release channel and pass it explicitly:

```bash
./install-discovery-app.sh \
  --rpm ./discovery-app-VERSION-RELEASE.x86_64.rpm \
  --signing-key ./RPM-GPG-KEY-DiscoveryApp-Release.asc
```

The installer never trusts a key solely because it is stored beside the RPM.

## Configure GitHub Copilot

Authentication is deferred until first use. After installation, configure
GitHub Copilot from a terminal as your normal desktop user:

```bash
discovery-app --configure-copilot
```

Preview and development packages use ring-specific commands:

```bash
discovery-app-preview --configure-copilot
discovery-app-dev --configure-copilot
```

Launch Microsoft Discovery with:

```bash
discovery-app --mode science
```

## Manual installation

Use these steps when the standalone installer cannot be used.

### 1. Verify the RPM checksum

```bash
RPM_PATH=./discovery-app-preview-VERSION-RELEASE.x86_64.rpm
MANIFEST_URL=https://raw.githubusercontent.com/microsoft/discovery/main/docs/discovery-app/releases/manifests/preview.json
tmp_dir="$(mktemp -d)"

curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  "$MANIFEST_URL" --output "$tmp_dir/preview.json"
EXPECTED_SHA256="$(python3 - "$tmp_dir/preview.json" <<'PY'
import json
import re
import sys

def reject_nonstandard_constant(value):
    raise ValueError(f"Non-standard JSON constant: {value}")

with open(sys.argv[1], encoding="utf-8") as manifest_file:
    digest = json.load(
        manifest_file,
        parse_constant=reject_nonstandard_constant,
    )["platforms"]["rhel-x64"]["sha256"]
if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
    raise ValueError("Invalid rhel-x64 SHA-256 digest")
print(digest.lower())
PY
)"
ACTUAL_SHA256="$(sha256sum "$RPM_PATH" | awk '{ print tolower($1) }')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]]
rpm -qp --queryformat '%{NAME} %{VERSION}-%{RELEASE} %{ARCH}\n' "$RPM_PATH"
```

Stop if the manifest cannot be downloaded or parsed, the digest does not
match, the machine is not `x86_64`, or the package name is not
`discovery-app-preview`.

### 2. Import Microsoft's package key

```bash
curl --fail --silent --show-error --location \
  https://packages.microsoft.com/keys/microsoft.asc \
  --output "$tmp_dir/microsoft.asc"
sudo rpm --import "$tmp_dir/microsoft.asc"
```

For packages signed by another approved key, inspect its fingerprint and import
it only after obtaining it through a trusted release channel:

```bash
gpg --show-keys --with-fingerprint ./RPM-GPG-KEY-DiscoveryApp-Release.asc
sudo rpm --import ./RPM-GPG-KEY-DiscoveryApp-Release.asc
```

### 3. Configure dependency repositories

Add Microsoft's product repository for ASP.NET Core Runtime 10:

```bash
source /etc/os-release
RHEL_MAJOR="${VERSION_ID%%.*}"

curl --fail --silent --show-error --location \
  "https://packages.microsoft.com/config/rhel/${RHEL_MAJOR}/packages-microsoft-prod.rpm" \
  --output "$tmp_dir/packages-microsoft-prod.rpm"

rpm --checksig "$tmp_dir/packages-microsoft-prod.rpm"
sudo dnf install -y "$tmp_dir/packages-microsoft-prod.rpm"
```

Add the Visual Studio Code repository:

```bash
cat >"$tmp_dir/vscode.repo" <<'EOF'
[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
autorefresh=1
type=rpm-md
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
EOF

sudo install -o root -g root -m 0644 \
  "$tmp_dir/vscode.repo" /etc/yum.repos.d/vscode.repo
sudo dnf makecache
```

### 4. Install GitHub Copilot CLI

If `copilot --version` does not report a working installation:

```bash
curl --fail --silent --show-error --location \
  https://gh.io/copilot-install \
  --output "$tmp_dir/copilot-install.sh"

sudo env PREFIX=/usr/local PATH=/usr/local/bin:/usr/bin:/bin \
  bash "$tmp_dir/copilot-install.sh" </dev/null

copilot --version
```

### 5. Verify and install the RPM

```bash
rpm --checksig "$RPM_PATH"
sudo dnf install -y "$RPM_PATH"

PACKAGE_NAME="$(rpm -qp --queryformat '%{NAME}' "$RPM_PATH")"
case "$PACKAGE_NAME" in
  discovery-app) COMMAND_NAME="discovery-app" ;;
  discovery-app-preview) COMMAND_NAME="discovery-app-preview" ;;
  discovery-app-dev) COMMAND_NAME="discovery-app-dev" ;;
  *) echo "Unexpected package name: $PACKAGE_NAME" >&2; exit 1 ;;
esac

rpm -V "$PACKAGE_NAME"
"$COMMAND_NAME" --version
"$COMMAND_NAME" --check-integrity
```

Do not use `--nogpgcheck` or install an RPM whose checksum or trusted signature
cannot be verified.

Remove the temporary directory when finished:

```bash
rm -rf "$tmp_dir"
```

## Troubleshooting

| Problem | Resolution |
| --- | --- |
| Preview manifest validation fails | Download the current Preview RHEL x64 RPM again. Old Preview RPMs intentionally fail after the manifest advances. |
| Unsupported architecture | This installer supports Preview RHEL x64 only. |
| RPM signature reports `NOKEY` | Import Microsoft's published key or provide the approved release key with `--signing-key`. |
| `sudo` is unavailable | Ask an administrator to perform the system package installation. |
| GitHub Copilot CLI is unavailable | Confirm outbound HTTPS access to `gh.io` and that Copilot CLI is enabled for the account. |
| `discovery-app` is not found after installation | Verify the installed package name. Preview and development packages use `discovery-app-preview` and `discovery-app-dev`. |

For product questions and feedback, use the
[Microsoft Discovery community forum](https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions).
