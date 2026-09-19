# System-level prerequisites for running deckd on NixOS.
#
# The daemon itself is a per-user session service: it needs the user's
# session D-Bus (MPRIS, the focus extension) and /dev/uinput inside the
# graphical session, so its unit is owned by the home-manager module
# (`homeModules.deckd`). This module installs only what must exist
# system-wide: the uinput kernel module, the udev rule, the `input`
# group, and optionally the firewall hole.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.deckd;
in
{
  options.services.deckd = {
    enable = lib.mkEnableOption "deckd system prerequisites (uinput, udev rule, input group)";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../deckd.nix { };
      defaultText = lib.literalExpression "the deckd flake package";
      description = ''
        deckd package whose udev rule is installed. The home-manager
        module's `services.deckd.package` should point at the same
        package (it does by default).
      '';
    };

    users = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "alice" ];
      description = ''
        Users to add to the `input` group. The udev rule also tags
        `/dev/uinput` with `uaccess`, which covers the active session
        user, so this is only needed where uaccess doesn't apply (for
        example a remote or headless session).
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8765;
      description = ''
        Port the daemon listens on; used by {option}`openFirewall`.
        Keep in sync with `services.deckd.port` in the home-manager
        module.
      '';
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Open the daemon port in the firewall. Only needed when the
        daemon is bound beyond localhost.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernelModules = [ "uinput" ];

    services.udev.packages = [ cfg.package ];

    users.groups.input = { };
    users.users = lib.genAttrs cfg.users (name: { extraGroups = [ "input" ]; });

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
  };
}
