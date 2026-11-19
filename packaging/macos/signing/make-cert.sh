#!/usr/bin/env bash
# Generate deckd's long-lived self-signed code-signing certificate (issue #194).
#
#   make-cert.sh OUT_DIR [COMMON_NAME]
#
# Run ONCE per project, not per release. TCC (the macOS privacy database)
# ties a user's Accessibility / System Events grants to the signing
# certificate's hash, so a new certificate costs every user a re-grant.
# That's why this refuses to overwrite an existing one.
#
# Writes, private to the current user:
#   OUT_DIR/deckd-codesign.p12           certificate + private key (PKCS#12)
#   OUT_DIR/deckd-codesign.p12.password  its password
#   OUT_DIR/deckd-codesign.cert.pem      the public certificate (shareable)
#
# Then prints the SHA-1 identity and the commands that store the .p12 as the
# GitHub Actions secrets release-macos.yml reads. Keep the .p12 and password
# somewhere durable (a password manager): they are the only way to cut a
# signed release by hand, and losing them means a new certificate.
#
# Needs only openssl, so it runs on Linux as well as macOS.
set -euo pipefail

OUT="${1:?usage: make-cert.sh OUT_DIR [COMMON_NAME]}"
CN="${2:-deckd self-signed code signing}"
# 20 years. A cert that expires stops new builds from signing, and its
# replacement costs every user a re-grant, so make it outlast the project.
DAYS="${DECKD_CERT_DAYS:-7300}"

P12="$OUT/deckd-codesign.p12"
if [ -e "$P12" ]; then
    echo "refusing to overwrite $P12: a new certificate makes every user re-grant" >&2
    echo "Accessibility / System Events. Delete it by hand if you really mean it." >&2
    exit 1
fi

umask 077
mkdir -p "$OUT"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/cert.cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = ext
[dn]
CN = $CN
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
subjectKeyIdentifier = hash
EOF

openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days "$DAYS" \
    -config "$tmp/cert.cnf" -keyout "$tmp/key.pem" -out "$OUT/deckd-codesign.cert.pem" 2>/dev/null

P12PW="${DECKD_CODESIGN_P12_PASSWORD:-$(openssl rand -base64 24)}"
export P12PW
# SHA1-3DES PBE + SHA-1 MAC: the newest PKCS#12 encryption macOS's
# `security import` reliably accepts. OpenSSL 3's AES-256/PBKDF2 default
# fails there with "MAC verification failed".
openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$OUT/deckd-codesign.cert.pem" \
    -name "$CN" -out "$P12" -passout env:P12PW \
    -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg sha1
printf '%s\n' "$P12PW" > "$OUT/deckd-codesign.p12.password"

sha1="$(openssl x509 -in "$OUT/deckd-codesign.cert.pem" -noout -fingerprint -sha1 | sed 's/.*=//; s/://g')"

cat <<EOF
Created a self-signed code-signing certificate, valid $DAYS days.
  identity (SHA-1): $sha1
  certificate:      $OUT/deckd-codesign.cert.pem
  PKCS#12 + key:    $P12   (password in $P12.password)

Store it for the release workflow:
  base64 < "$P12" | gh secret set DECKD_CODESIGN_P12_BASE64
  gh secret set DECKD_CODESIGN_P12_PASSWORD < "$P12.password"

To sign a build by hand on a Mac, import it once into your login keychain:
  security import "$P12" -k ~/Library/Keychains/login.keychain-db -T /usr/bin/codesign
  DECKD_CODESIGN_IDENTITY=$sha1 just build-macos-dmg
EOF
