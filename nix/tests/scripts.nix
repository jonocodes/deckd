{ pkgs }:

let
  # ---------------------------------------------------------------------
  # seed-layouts: copies bundled defaults into a writable layouts dir
  # without ever clobbering a file the user may have edited.
  # ---------------------------------------------------------------------
  seedLayouts = pkgs.callPackage ../seed-layouts.nix { };

  seedFixture = pkgs.runCommand "deckd-seed-fixture" { } ''
    mkdir -p $out/src/nested
    echo 'default: {}' > $out/src/default.yaml
    echo 'firefox: {}' > $out/src/firefox.yaml
    echo 'not a layout' > $out/src/README.md
    echo 'nested: {}' > $out/src/nested/ignored.yaml
  '';

  seedTest = pkgs.runCommand "deckd-seed-layouts-test" {
    nativeBuildInputs = [ seedLayouts ];
  } ''
    set -euo pipefail
    cp -r ${seedFixture}/src src
    mkdir dest

    # First run copies every top-level YAML, ignoring other files/dirs.
    deckd-seed-layouts src dest
    test -f dest/default.yaml
    test -f dest/firefox.yaml
    test ! -e dest/README.md
    test ! -e dest/ignored.yaml

    # A user-edited file is never overwritten.
    echo 'edited: true' > dest/firefox.yaml
    deckd-seed-layouts src dest
    grep -q 'edited: true' dest/firefox.yaml

    # Re-running changes nothing (idempotent).
    before="$(find dest -type f -print0 | sort -z | xargs -0 sha256sum)"
    deckd-seed-layouts src dest
    after="$(find dest -type f -print0 | sort -z | xargs -0 sha256sum)"
    test "$before" = "$after"

    # A missing source directory is a no-op, not a failure.
    deckd-seed-layouts missing-dir dest

    touch $out
  '';

  # ---------------------------------------------------------------------
  # install-kwin: installs/upgrades the KWin script and enables it,
  # mirroring the `just install-focus-kwin` recipe.
  # ---------------------------------------------------------------------
  stub = name: text: pkgs.writeShellScriptBin name text;

  fakeKde = {
    # First -i succeeds; a second -i would fail (as a real first-run
    # install does), forcing the upgrade path.
    kpackage = stub "kpackagetool6" ''
      echo "kpackagetool6 $*" >> "$DECKD_TEST_LOG"
      case "$*" in
        *" -i "*)
          if [ -e "$DECKD_TEST_INSTALLED" ]; then exit 1; fi
          touch "$DECKD_TEST_INSTALLED"
          ;;
      esac
    '';
    kconfig = stub "kwriteconfig6" ''echo "kwriteconfig6 $*" >> "$DECKD_TEST_LOG"'';
    qttools = stub "qdbus" ''echo "qdbus $*" >> "$DECKD_TEST_LOG"'';
  };

  installKwin = pkgs.callPackage ../install-kwin.nix { kdePackages = fakeKde; };
  focusKwin = pkgs.callPackage ../focus-kwin.nix { };
  scriptPath = "${focusKwin}/share/kwin/scripts/deckd-focus";

  kwinTest = pkgs.runCommand "deckd-install-kwin-test" {
    nativeBuildInputs = [ installKwin ];
  } ''
    set -euo pipefail
    export HOME="$PWD/home"
    export DECKD_TEST_LOG="$PWD/log"
    export DECKD_TEST_INSTALLED="$PWD/installed"
    mkdir -p "$HOME"
    : > "$DECKD_TEST_LOG"

    # First activation: install, persist the enable flag, hot-start.
    deckd-install-kwin ${scriptPath}
    grep -q -- "kpackagetool6 --type=KWin/Script -i ${scriptPath}" "$DECKD_TEST_LOG"
    ! grep -q -- "kpackagetool6 --type=KWin/Script -u" "$DECKD_TEST_LOG"
    grep -q -- "kwriteconfig6 --file kwinrc --group Plugins --key deckd-focusEnabled true" "$DECKD_TEST_LOG"
    grep -q -- "unloadScript deckd-focus" "$DECKD_TEST_LOG"
    grep -q -- "loadScript $HOME/.local/share/kwin/scripts/deckd-focus/contents/code/main.js deckd-focus" "$DECKD_TEST_LOG"

    # Re-activation: -i now fails, so the upgrade path is taken.
    : > "$DECKD_TEST_LOG"
    deckd-install-kwin ${scriptPath}
    grep -q -- "kpackagetool6 --type=KWin/Script -u ${scriptPath}" "$DECKD_TEST_LOG"

    touch $out
  '';

in
{
  seed-layouts = seedTest;
  install-kwin = kwinTest;
}
