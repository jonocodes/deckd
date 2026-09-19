# KDE Plasma focus watcher: installs and enables the deckd-focus KWin
# script alongside the base user service.
#
# The install runs as an activation step (kpackagetool6 writes into
# ~/.local/share/kwin/scripts) and is idempotent, so it re-runs on every
# home-manager switch. The running KWin instance is hot-started by the
# script when a Plasma session is available.
{ config, lib, pkgs, ... }:

let
  focusKwin = pkgs.callPackage ../focus-kwin.nix { };
  installKwin = pkgs.callPackage ../install-kwin.nix { };
in
{
  imports = [ ./home.nix ];

  config = lib.mkIf config.services.deckd.enable {
    home.activation.deckdKwin = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run ${lib.getExe installKwin} ${lib.escapeShellArg "${focusKwin}/share/kwin/scripts/deckd-focus"}
    '';
  };
}
