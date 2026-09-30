#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
INSTALLER_SOURCE="$SCRIPT_DIRECTORY/install-discovery-app.sh"
TEST_DIRECTORY="$(mktemp -d)"
FAKE_BIN="$TEST_DIRECTORY/bin"
INSTALLER="$TEST_DIRECTORY/install-discovery-app.sh"
RPM_PATH="$TEST_DIRECTORY/discovery-app-preview-test.x86_64.rpm"
INSTALL_MARKER="$TEST_DIRECTORY/dnf-install-called"
COMMAND_LOG="$TEST_DIRECTORY/commands.log"
EXPECTED_SHA256="$(printf 'a%.0s' {1..64})"

cleanup() {
  rm -rf "$TEST_DIRECTORY"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local expected="$1"
  local actual="$2"
  [[ "$actual" == *"$expected"* ]] || fail "Expected '$expected' in '$actual'."
}

assert_not_exists() {
  [[ ! -e "$1" ]] || fail "Unexpected path exists: $1"
}

assert_not_contains() {
  local unexpected="$1"
  local actual="$2"
  [[ "$actual" != *"$unexpected"* ]] \
    || fail "Unexpected '$unexpected' in '$actual'."
}

assert_precedes() {
  local first="$1"
  local second="$2"
  local actual="$3"
  [[ "$actual" == *"$first"*"$second"* ]] \
    || fail "Expected '$first' before '$second' in '$actual'."
}

create_fake_commands() {
  mkdir -p "$FAKE_BIN"

  cat >"$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
max_filesize=""
output=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-filesize) max_filesize="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    *) url="$1"; shift ;;
  esac
done
if [[ "$url" == *"/preview.json" ]]; then
  [[ "${CURL_FAIL_MANIFEST:-false}" != "true" ]] || exit 22
  [[ "$max_filesize" == "1048576" ]] || exit 1
  printf '%s' "$MANIFEST_CONTENT" >"$output"
else
  printf 'key' >"$output"
fi
EOF

  cat >"$FAKE_BIN/dnf" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "install" ]]; then
  {
    printf 'dnf install application-rpm %s\n' "$(basename "${!#}")"
  } >>"$COMMAND_LOG"
  : >"$INSTALL_MARKER"
fi
EOF

  cat >"$FAKE_BIN/rpm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  --checksig)
    echo "rpm --checksig $(basename "$2")" >>"$COMMAND_LOG"
    if [[ "${RPM_SIGNATURE_FAIL:-false}" == "true" ]]; then
      echo "$2: NOKEY"
      exit 0
    fi
    echo "$2: digests signatures OK"
    ;;
  -qp)
    case "$3" in
      '%{NAME}') printf 'discovery-app-preview' ;;
      '%{RELEASE}') printf '1' ;;
      '%{ARCH}') printf 'x86_64' ;;
      *) exit 1 ;;
    esac
    ;;
  -q|-V|--import) ;;
  *) exit 1 ;;
esac
EOF

  cat >"$FAKE_BIN/sha256sum" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s  %s\n' "$LOCAL_SHA256" "$1"
EOF

  cat >"$FAKE_BIN/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" != "-v" ]] || exit 0
exec "$@"
EOF

  cat >"$FAKE_BIN/uname" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${TEST_MACHINE_ARCH:-x86_64}"
EOF

  cat >"$FAKE_BIN/copilot" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

  cat >"$FAKE_BIN/discovery-app-preview" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

  chmod +x "$FAKE_BIN"/*
}

run_installer() {
  local manifest_content="$1"
  local local_sha256="$2"
  local curl_failure="${3:-false}"
  local signature_failure="${4:-false}"
  local output

  : >"$COMMAND_LOG"
  rm -f "$INSTALL_MARKER"
  output="$(
    PATH="$FAKE_BIN:$PATH" \
    COMMAND_LOG="$COMMAND_LOG" \
    INSTALL_MARKER="$INSTALL_MARKER" \
    MANIFEST_CONTENT="$manifest_content" \
    LOCAL_SHA256="$local_sha256" \
    CURL_FAIL_MANIFEST="$curl_failure" \
    RPM_SIGNATURE_FAIL="$signature_failure" \
    bash "$INSTALLER" --rpm "$RPM_PATH" --yes 2>&1
  )" || {
    printf '%s' "$output"
    return 1
  }
  printf '%s' "$output"
}

expect_failure() {
  local expected_error="$1"
  shift
  local output
  if output="$(run_installer "$@")"; then
    fail "Installer unexpectedly succeeded."
  fi
  assert_contains "$expected_error" "$output"
}

mkdir -p "$FAKE_BIN"
create_fake_commands
printf 'rpm payload' >"$RPM_PATH"
printf 'ID=rhel\nVERSION_ID=9\nPRETTY_NAME="Test RHEL"\n' >"$TEST_DIRECTORY/os-release"
sed "s|/etc/os-release|$TEST_DIRECTORY/os-release|" "$INSTALLER_SOURCE" >"$INSTALLER"
chmod +x "$INSTALLER"

valid_manifest="{\"platforms\":{\"rhel-x64\":{\"sha256\":\"$EXPECTED_SHA256\"}}}"

run_installer "$valid_manifest" "$EXPECTED_SHA256" >/dev/null
[[ -f "$INSTALL_MARKER" ]] || fail "Expected installation after successful validation."
assert_precedes \
  "rpm --checksig $(basename "$RPM_PATH")" \
  "dnf install application-rpm $(basename "$RPM_PATH")" \
  "$(cat "$COMMAND_LOG")"

expect_failure "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest." \
  '{"platforms":{}}' "$EXPECTED_SHA256"
expect_failure "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest." \
  '{"platforms":{"rhel-x64":{}}}' "$EXPECTED_SHA256"
expect_failure "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest." \
  '{"platforms":' "$EXPECTED_SHA256"
expect_failure "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest." \
  '{"platforms":{"rhel-x64":{"sha256":"not-a-digest"}}}' "$EXPECTED_SHA256"
expect_failure "Preview release manifest does not contain a valid rhel-x64 SHA-256 digest." \
  '{"platforms":{"rhel-x64":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}' "$EXPECTED_SHA256"
expect_failure "RPM SHA-256 mismatch." "$valid_manifest" "$(printf 'b%.0s' {1..64})"
expect_failure "Could not download the Preview release manifest." "$valid_manifest" "$EXPECTED_SHA256" true

expect_failure "RPM does not have a trusted signature:" "$valid_manifest" "$EXPECTED_SHA256" false true
assert_contains "rpm --checksig" "$(cat "$COMMAND_LOG")"
assert_not_contains "dnf install application-rpm" "$(cat "$COMMAND_LOG")"
assert_not_exists "$INSTALL_MARKER"

echo "PASS: Preview RHEL x64 manifest validation tests"
