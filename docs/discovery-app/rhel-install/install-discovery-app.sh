#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

set -euo pipefail

usage() {
  cat <<'EOF'
Install Discovery App and its command-line prerequisites on Enterprise Linux.

Usage:
  ./install-discovery-app.sh --rpm PATH [-y|--yes] [--signing-key PATH] [--setup-mode MODE]

Options:
  --rpm PATH          Discovery App Preview RHEL x64 binary RPM.
  -y, --yes           Accept the installation plan and answer yes to all
                      installer questions. Does not authenticate user accounts.
  --signing-key PATH  Public RPM signing key to import before verification.
                      Optional: omit it when the signing key is already trusted
                      by the system RPM database, which is the case for packages
                      signed with Microsoft's published key. A key supplied for a
                      production package must match Microsoft's published key.
  --setup-mode MODE   Setup choice: automatic (default), prompt, or manual.
                      Automatic configures repositories and dependencies,
                      installs Copilot, then installs the RPM.
                      Manual prints the self-managed path and makes no changes.
  -h, --help          Show this help.

The installer must run as a normal desktop user with sudo access. It requires
one confirmation before making system changes unless -y or --yes is supplied.
GitHub Copilot authentication is deferred until first use.
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

copilot_cli_works() {
  local copilot_path="$1"
  "$copilot_path" --version >/dev/null 2>&1
}

package_requirement_available() {
  local requirement="$1"
  rpm -q --whatprovides "$requirement" >/dev/null 2>&1 \
    || dnf repoquery --quiet --whatprovides "$requirement" >/dev/null 2>&1
}

confirm_installation() {
  if [[ "$ASSUME_YES" == "true" ]]; then
    echo "Installation confirmed by --yes."
    return
  fi

  [[ -r /dev/tty && -w /dev/tty ]] \
    || fail "Installation confirmation requires a terminal. Re-run with -y or --yes for unattended setup."
  printf '\nContinue with installation? [y/N] ' >/dev/tty
  local answer
  read -r answer </dev/tty
  case "$answer" in
    y|Y|yes|YES|Yes) ;;
    *) fail "Installation cancelled; no system changes were made." ;;
  esac
}

verify_rpm_signature() {
  local rpm_path="$1"
  local signature_status

  if ! signature_status="$(rpm --checksig "$rpm_path" 2>&1)"; then
    echo "$signature_status" >&2
    fail "RPM signature verification failed: $rpm_path"
  fi

  echo "$signature_status"
  if grep -Eqi 'NOKEY|NOT OK|NOTTRUSTED' <<<"$signature_status" \
     || ! grep -Eqi '(signatures?|pgp).*OK' <<<"$signature_status"; then
    fail "RPM does not have a trusted signature: $rpm_path"
  fi
}

absolute_path() {
  local path="$1"
  local directory
  directory="$(cd "$(dirname "$path")" && pwd -P)"
  printf '%s/%s\n' "$directory" "$(basename "$path")"
}

RPM_PATH=""
SIGNING_KEY_PATH=""
SETUP_MODE="automatic"
ASSUME_YES=false
PREVIEW_MANIFEST_URL="https://raw.githubusercontent.com/microsoft/discovery/main/docs/discovery-app/releases/manifests/preview.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rpm)
      [[ $# -ge 2 ]] || fail "--rpm requires a path."
      RPM_PATH="$2"
      shift 2
      ;;
    -y|--yes)
      ASSUME_YES=true
      shift
      ;;
    --signing-key)
      [[ $# -ge 2 ]] || fail "--signing-key requires a path."
      SIGNING_KEY_PATH="$2"
      shift 2
      ;;
    --setup-mode)
      [[ $# -ge 2 ]] || fail "--setup-mode requires prompt, automatic, or manual."
      SETUP_MODE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

case "$SETUP_MODE" in
  prompt|automatic|manual) ;;
  *) fail "--setup-mode must be prompt, automatic, or manual (found: $SETUP_MODE)." ;;
esac

[[ -n "$RPM_PATH" ]] || fail "--rpm PATH is required."
[[ -f "$RPM_PATH" ]] || fail "RPM not found: $RPM_PATH"
[[ "$RPM_PATH" == *.rpm && "$RPM_PATH" != *.src.rpm ]] \
  || fail "--rpm must name one binary .rpm file."
if [[ -n "$SIGNING_KEY_PATH" ]]; then
  [[ -f "$SIGNING_KEY_PATH" ]] || fail "Signing key not found: $SIGNING_KEY_PATH"
fi

[[ ${EUID} -ne 0 ]] || fail "Run this installer as your normal desktop user, not as root."
[[ -r /etc/os-release ]] || fail "Cannot identify this Linux distribution."

# shellcheck disable=SC1091
source /etc/os-release
RHEL_MAJOR="${VERSION_ID%%.*}"
[[ "$RHEL_MAJOR" =~ ^[0-9]+$ && "$RHEL_MAJOR" -ge 9 ]] \
  || fail "Discovery App requires Enterprise Linux 9 or later (found ${PRETTY_NAME:-unknown})."
case "${ID:-}" in
  rhel|almalinux|rocky) ;;
  *) fail "Unsupported distribution: ${PRETTY_NAME:-unknown}. Use RHEL, AlmaLinux, or Rocky Linux." ;;
esac
MACHINE_ARCH="$(uname -m)"
[[ "$MACHINE_ARCH" == "x86_64" ]] \
  || fail "This installer supports Preview RHEL x64 only (found $MACHINE_ARCH)."

for command_name in curl python3 rpm sha256sum; do
  require_command "$command_name"
done

RPM_PATH="$(absolute_path "$RPM_PATH")"
# Only an explicitly supplied key is trusted. A key discovered next to the RPM
# would be supplied by the same source as the package it is meant to vouch for.
if [[ -n "$SIGNING_KEY_PATH" ]]; then
  SIGNING_KEY_PATH="$(absolute_path "$SIGNING_KEY_PATH")"
  echo "Using RPM signing key: $SIGNING_KEY_PATH"
fi

TEMP_DIRECTORY="$(mktemp -d)"
cleanup() {
  rm -rf "$TEMP_DIRECTORY"
}
trap cleanup EXIT

PREVIEW_MANIFEST_PATH="$TEMP_DIRECTORY/preview.json"
echo "Downloading Preview release manifest..."
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --max-filesize 1048576 \
  "$PREVIEW_MANIFEST_URL" \
  --output "$PREVIEW_MANIFEST_PATH" \
  || fail "Could not download the Preview release manifest."

EXPECTED_SHA256="$(python3 - "$PREVIEW_MANIFEST_PATH" <<'PY'
import json
import re
import sys

def reject_nonstandard_constant(value):
    raise ValueError(f"Non-standard JSON constant: {value}")

try:
    with open(sys.argv[1], encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file, parse_constant=reject_nonstandard_constant)
    digest = manifest["platforms"]["rhel-x64"]["sha256"]
except (KeyError, TypeError, ValueError, OSError):
    sys.exit(1)

if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
    sys.exit(1)

print(digest.lower())
PY
)" || fail "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest."
ACTUAL_SHA256="$(sha256sum "$RPM_PATH" | awk '{ print tolower($1) }')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] \
  || fail "RPM SHA-256 mismatch. Expected $EXPECTED_SHA256, got $ACTUAL_SHA256."

PACKAGE_NAME="$(rpm -qp --queryformat '%{NAME}' "$RPM_PATH" 2>/dev/null)" \
  || fail "RPM metadata could not be read: $RPM_PATH"
case "$PACKAGE_NAME" in
  discovery-app)
    COMMAND_NAME="discovery-app"
    INSTALL_PREFIX="/opt/discovery-app"
    ;;
  discovery-app-preview)
    COMMAND_NAME="discovery-app-preview"
    INSTALL_PREFIX="/opt/discovery-app-preview"
    ;;
  discovery-app-dev)
    COMMAND_NAME="discovery-app-dev"
    INSTALL_PREFIX="/opt/discovery-app-dev"
    ;;
  *)
    fail "Expected a Discovery App ring package, found: $PACKAGE_NAME"
    ;;
esac
PACKAGE_RELEASE="$(rpm -qp --queryformat '%{RELEASE}' "$RPM_PATH" 2>/dev/null)" \
  || fail "RPM release metadata could not be read: $RPM_PATH"
PACKAGE_ARCH="$(rpm -qp --queryformat '%{ARCH}' "$RPM_PATH" 2>/dev/null)" \
  || fail "RPM architecture could not be read: $RPM_PATH"
[[ "$PACKAGE_ARCH" == "$MACHINE_ARCH" ]] \
  || fail "RPM architecture $PACKAGE_ARCH does not match this machine ($MACHINE_ARCH)."

if [[ "$SETUP_MODE" == "prompt" && "$ASSUME_YES" == "true" ]]; then
  SETUP_MODE="automatic"
elif [[ "$SETUP_MODE" == "prompt" ]]; then
  [[ -r /dev/tty && -w /dev/tty ]] \
    || fail "Setup-mode selection requires a terminal. Use --setup-mode manual, or rerun with -y or --yes."
  cat >/dev/tty <<'EOF'

Choose how to set up Discovery App:
  1. Automatic: add Microsoft repositories and keys, install dependencies and
  GitHub Copilot CLI, then install the Discovery App RPM. Authentication happens
  on first use.
  2. Manual: make no changes and show where to follow the commands yourself.
EOF
  printf 'Select 1 or 2: ' >/dev/tty
  read -r SETUP_SELECTION </dev/tty
  case "$SETUP_SELECTION" in
    1) SETUP_MODE="automatic" ;;
    2) SETUP_MODE="manual" ;;
    *) fail "Setup mode was not selected; no system changes were made." ;;
  esac
fi

if [[ "$SETUP_MODE" == "manual" ]]; then
  README_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/README.md"
  cat <<EOF

Manual setup selected. No system changes were made.

Follow the "Manual installation" section in:
  $README_PATH

The manual path covers repository keys, dependency installation, GitHub
Copilot CLI installation, RPM signature verification, and RPM install.
EOF
  exit 0
fi

for command_name in curl dnf sudo; do
  require_command "$command_name"
done

MICROSOFT_REPOSITORY_NEEDED=true
if package_requirement_available "aspnetcore-runtime-10.0"; then
  MICROSOFT_REPOSITORY_NEEDED=false
fi

VSCODE_REPOSITORY_NEEDED=true
if package_requirement_available "code >= 1.120.0"; then
  VSCODE_REPOSITORY_NEEDED=false
fi

COPILOT_PATH="$(command -v copilot 2>/dev/null || true)"
COPILOT_INSTALL_NEEDED=true
if [[ -n "$COPILOT_PATH" ]] && copilot_cli_works "$COPILOT_PATH"; then
  COPILOT_INSTALL_NEEDED=false
fi

cat <<EOF

Discovery App installation plan

System: ${PRETTY_NAME:-unknown}
RPM:    $RPM_PATH

This installer will make these system-wide changes with sudo:
  1. Import Microsoft's RPM signing key.
  2. Add Microsoft's .NET repository only if ASP.NET Core Runtime 10 is not
     already installed or available from a configured repository.
  3. Add Microsoft's Visual Studio Code repository only if VS Code 1.120.0 or
     later is not already installed or available.
  4. Install GitHub Copilot CLI only if a working copilot executable is not
     already available.
  5. Import the Discovery App signing key when --signing-key is supplied.
  6. Install the verified Discovery App RPM and its declared dependencies.

Authentication is deferred until first use. The installer does not open a
browser or access a system keychain.
EOF

confirm_installation

sudo -v

MICROSOFT_KEY="$TEMP_DIRECTORY/microsoft.asc"
MICROSOFT_REPO_RPM="$TEMP_DIRECTORY/packages-microsoft-prod.rpm"
VSCODE_REPO="$TEMP_DIRECTORY/vscode.repo"
COPILOT_INSTALLER="$TEMP_DIRECTORY/copilot-install.sh"

echo "Downloading and validating Microsoft repository configuration..."
curl --fail --silent --show-error --location \
  https://packages.microsoft.com/keys/microsoft.asc \
  --output "$MICROSOFT_KEY"
if [[ -n "$SIGNING_KEY_PATH" && "$PACKAGE_RELEASE" != *".devkeys"* ]]; then
  EXPECTED_PRODUCTION_KEY_SHA256="$(sha256sum "$MICROSOFT_KEY" | awk '{ print tolower($1) }')"
  ACTUAL_PRODUCTION_KEY_SHA256="$(sha256sum "$SIGNING_KEY_PATH" | awk '{ print tolower($1) }')"
  [[ "$ACTUAL_PRODUCTION_KEY_SHA256" == "$EXPECTED_PRODUCTION_KEY_SHA256" ]] \
    || fail "Production RPM signing key does not match Microsoft's published signing key."
fi
sudo rpm --import "$MICROSOFT_KEY"

REPOSITORY_ADDED=false
if [[ "$MICROSOFT_REPOSITORY_NEEDED" == "true" ]]; then
  echo "Adding Microsoft package repository for ASP.NET Core Runtime 10..."
  curl --fail --silent --show-error --location \
    "https://packages.microsoft.com/config/rhel/${RHEL_MAJOR}/packages-microsoft-prod.rpm" \
    --output "$MICROSOFT_REPO_RPM"
  verify_rpm_signature "$MICROSOFT_REPO_RPM"
  sudo dnf install -y "$MICROSOFT_REPO_RPM"
  REPOSITORY_ADDED=true
else
  echo "ASP.NET Core Runtime 10 is installed or available; skipping Microsoft product repository installation."
fi

if [[ "$VSCODE_REPOSITORY_NEEDED" == "true" ]]; then
  echo "Adding the Visual Studio Code repository..."
  cat >"$VSCODE_REPO" <<'EOF'
[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
autorefresh=1
type=rpm-md
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
EOF
  sudo install -o root -g root -m 0644 "$VSCODE_REPO" /etc/yum.repos.d/vscode.repo
  REPOSITORY_ADDED=true
else
  echo "VS Code 1.120.0 or later is installed or available; skipping Visual Studio Code repository installation."
fi

if [[ "$REPOSITORY_ADDED" == "true" ]]; then
  sudo dnf makecache
fi

if [[ "$COPILOT_INSTALL_NEEDED" == "true" ]]; then
  echo "Installing GitHub Copilot CLI..."
  curl --fail --silent --show-error --location \
    https://gh.io/copilot-install \
    --output "$COPILOT_INSTALLER"
  # The upstream installer prompts to append /usr/local/bin to root's profile
  # when sudo resets PATH. Supply the final prefix and PATH explicitly and close
  # stdin so installation is deterministic and never touches /root/.bash_profile.
  sudo env PREFIX=/usr/local PATH=/usr/local/bin:/usr/bin:/bin \
    bash "$COPILOT_INSTALLER" </dev/null
  COPILOT_PATH="/usr/local/bin/copilot"
  copilot_cli_works "$COPILOT_PATH" \
    || fail "GitHub Copilot CLI was installed at $COPILOT_PATH but failed to start."
else
  echo "Found GitHub Copilot CLI at ${COPILOT_PATH}. Skipping Copilot CLI installation."
fi

if [[ -n "$SIGNING_KEY_PATH" ]]; then
  sudo rpm --import "$SIGNING_KEY_PATH"
fi

verify_rpm_signature "$RPM_PATH"

sudo dnf install -y "$RPM_PATH"

rpm -V "$PACKAGE_NAME"
"$COMMAND_NAME" --version
"$COMMAND_NAME" --check-integrity

cat <<EOF

Discovery App installation completed.
Launch it with:

  ${COMMAND_NAME} --mode science

GitHub Copilot authentication remains deferred until first use.
Before using Copilot, configure it from a terminal:

  ${COMMAND_NAME} --configure-copilot
EOF