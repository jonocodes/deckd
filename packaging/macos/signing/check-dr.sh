#!/usr/bin/env bash
# Check that deckd.app's designated requirement survives upgrades (issue #194).
#
#   check-dr.sh [--expect-signed] APP
#
# TCC records each grant against the app's designated requirement (DR):
#   - ad-hoc signed:  `cdhash H"…"`, which changes with every build, so a
#                     grant stops applying after an upgrade;
#   - certificate:    `identifier "com.deckd.daemon" and certificate leaf …`,
#                     which stays the same while the certificate does.
#
# Exit 0 for a certificate DR naming com.deckd.daemon. An ad-hoc (cdhash) DR
# is only noted, unless --expect-signed is given, when it fails. Anything else
# fails. Used by sign-app.sh after signing and by test/test-app.sh on the
# installed DMG.
set -euo pipefail

EXPECT_SIGNED=0
if [ "${1:-}" = --expect-signed ]; then EXPECT_SIGNED=1; shift; fi
APP="${1:?usage: check-dr.sh [--expect-signed] APP}"
BUNDLE_ID=com.deckd.daemon

# `codesign -d -r-` prints the DR on stderr, as `# designated => …` when it is
# implicit (ad-hoc) and `designated => …` otherwise.
dr="$(codesign -d -r- "$APP" 2>&1 | sed -n 's/^#\{0,1\} *designated => //p' | head -1)"

if [ -z "$dr" ]; then
    echo "  FAIL no designated requirement on $APP"
    exit 1
fi
echo "  designated requirement: $dr"

case "$dr" in
    *cdhash*)
        if [ "$EXPECT_SIGNED" = 1 ]; then
            echo "  FAIL ad-hoc (cdhash) requirement: permission grants won't survive an upgrade"
            exit 1
        fi
        echo "  note: ad-hoc signed (cdhash); permission grants reset on every upgrade"
        exit 0
        ;;
esac

if [[ "$dr" == *"identifier \"$BUNDLE_ID\""* && "$dr" == *"certificate leaf"* ]]; then
    echo "  ok   stable requirement: names $BUNDLE_ID and the certificate leaf"
    exit 0
fi
echo "  FAIL unexpected requirement (want identifier \"$BUNDLE_ID\" and a certificate leaf)"
exit 1
