# GNOME focus watcher: the deckd-focus Shell extension, enabled alongside
# the base user service.
#
# home-manager's programs.gnome-shell.extensions installs the extension
# package and sets the dconf enable flag; the running Shell picks it up
# after a relogin. On NixOS the dconf database also needs
# `programs.dconf.enable = true` at the system level (the NixOS GNOME
# module already sets this).
{ config, lib, pkgs, ... }:

let
  focusGnome = pkgs.callPackage ../focus-gnome.nix { };
in
{
  imports = [ ./home.nix ];

  config = lib.mkIf config.services.deckd.enable {
    programs.gnome-shell = {
      enable = true;
      extensions = [ { package = focusGnome; } ];
    };
  };
}
