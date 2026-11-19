#!/usr/bin/env bash
# Re-sign deckd.app with the project's stable certificate (issue #194).
#
#   DECKD_CODESIGN_IDENTITY=<sha1-or-name> sign-app.sh APP
#
# With DECKD_CODESIGN_IDENTITY unset or empty, this does nothing: the bundle
# keeps PyInstaller's ad-hoc signature, so local builds and fork CI work
# without the certificate.
#
# Why re-sign here instead of passing the identity to PyInstaller's
# `codesign_identity`: given an identity, PyInstaller always adds
# `--options=runtime` and `--timestamp`. Hardened runtime turns on library
# validation, which a self-signed certificate (no Team ID) can't satisfy for
# the bundled Python dylibs, and `--timestamp` makes every build depend on
# Apple's timestamp server. Neither is needed until notarization.
set -euo pipefail

APP="${1:?usage: sign-app.sh APP}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IDENTITY="${DECKD_CODESIGN_IDENTITY:-}"

if [ -z "$IDENTITY" ]; then
    echo "DECKD_CODESIGN_IDENTITY not set: keeping the ad-hoc signature" \
        "(permission grants reset on every upgrade)."
    exit 0
fi

echo "Signing $APP with $IDENTITY"
# --deep re-signs the nested Mach-O files (Contents/Frameworks, MacOS) with
# the same certificate, as PyInstaller's own bundle signing does.
codesign --force --deep --timestamp=none --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"
"$HERE/check-dr.sh" --expect-signed "$APP"
