#!/usr/bin/env bash
# Import deckd's code-signing certificate into a throwaway keychain (issue #194).
#
#   DECKD_CODESIGN_P12_BASE64=… DECKD_CODESIGN_P12_PASSWORD=… import-cert.sh
#
# For CI (release-macos.yml): decodes the .p12 from the secret, imports it
# into a fresh keychain, and puts that keychain on the user search list
# (codesign only finds identities there). Then:
#   - appends DECKD_CODESIGN_IDENTITY=<sha1> to $GITHUB_ENV, which sign-app.sh
#     reads;
#   - writes signed=true|false to $GITHUB_OUTPUT.
#
# Without the secret (forks, PRs from forks) it exits 0 with signed=false and
# the build stays ad-hoc.
#
# DECKD_SIGNING_KEYCHAIN overrides the keychain path (default:
# $RUNNER_TEMP/deckd-signing.keychain-db). `security delete-keychain <path>`
# removes it again, search-list entry included; CI runners are discarded.
set -euo pipefail

emit() {  # emit FILE_VAR LINE: append to a GitHub file if it's set
    local target="${!1:-}"
    [ -n "$target" ] && printf '%s\n' "$2" >> "$target"
    return 0
}

if [ -z "${DECKD_CODESIGN_P12_BASE64:-}" ]; then
    msg="No code-signing certificate (DECKD_CODESIGN_P12_BASE64 unset): building ad-hoc; permission grants won't survive upgrades."
    if [ "${GITHUB_ACTIONS:-}" = true ]; then echo "::warning::$msg"; else echo "$msg"; fi
    emit GITHUB_OUTPUT "signed=false"
    exit 0
fi
: "${DECKD_CODESIGN_P12_PASSWORD:?DECKD_CODESIGN_P12_PASSWORD must accompany the certificate}"

KC="${DECKD_SIGNING_KEYCHAIN:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/deckd-signing.keychain-db}"
KCPW="$(openssl rand -hex 16)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

printf '%s' "$DECKD_CODESIGN_P12_BASE64" | base64 -d > "$work/cert.p12"

security create-keychain -p "$KCPW" "$KC"
# No auto-lock timeout during a long build.
security set-keychain-settings "$KC"
security unlock-keychain -p "$KCPW" "$KC"
security import "$work/cert.p12" -k "$KC" -f pkcs12 \
    -P "$DECKD_CODESIGN_P12_PASSWORD" -T /usr/bin/codesign
# Let codesign use the key without a GUI "allow access" prompt.
security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPW" "$KC" >/dev/null

# Prepend to the search list, keeping what's there.
existing=()
while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"; line="${line#\"}"; line="${line%\"}"
    [ -n "$line" ] && existing+=("$line")
done < <(security list-keychains -d user)
security list-keychains -d user -s "$KC" "${existing[@]}"

# A self-signed cert shows as CSSMERR_TP_NOT_TRUSTED here; codesign signs
# with it anyway, and TCC only compares the requirement, not trust.
identity="$(security find-identity -p codesigning "$KC" | awk '$1 ~ /^[0-9]+\)$/ { print $2; exit }')"
if [ -z "$identity" ]; then
    echo "no code-signing identity found in the imported certificate" >&2
    exit 1
fi

echo "Imported code-signing identity $identity into $KC"
emit GITHUB_ENV "DECKD_CODESIGN_IDENTITY=$identity"
emit GITHUB_OUTPUT "signed=true"
