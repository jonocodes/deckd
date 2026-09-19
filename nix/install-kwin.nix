{ writeShellApplication, coreutils, kdePackages }:
writeShellApplication {
  name = "deckd-install-kwin";
  runtimeInputs = [
    coreutils
    kdePackages.kpackage
    kdePackages.kconfig
    kdePackages.qttools
  ];
  text = builtins.readFile ./install-kwin.sh;
}
