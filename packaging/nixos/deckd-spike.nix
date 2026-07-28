# Spike-only NixOS module for running deckd from a source checkout.
#
# Example:
#   imports = [ /home/jono/src/deckd/packaging/nixos/deckd-spike.nix ];
#
#   services.deckd-spike = {
#     enable = true;
#     user = "jono";
#     projectDir = "/home/jono/src/deckd";
#     bind = [ "0.0.0.0" ];  # open to LAN; default is localhost-only
#   };
#
# Before starting the service, run once from the checkout:
#   just setup
#   just build-client
{ config, lib, pkgs, ... }:

let
  cfg = config.services.deckd-spike;
  # Translate the operator's ``bind`` list into one ``--bind ADDR``
  # flag per spec (issue #66). The CLI is repeatable, so a Nix
  # listOf passes through cleanly.
  bindFlags = lib.concatMapStringsSep " " (addr: "--bind ${addr}") cfg.bind;
  deckdStart = pkgs.writeShellScript "deckd-spike-start" ''
    exec ${cfg.projectDir}/.venv/bin/deckd ${bindFlags} \
      --port ${toString cfg.port} \
      --layouts ${cfg.projectDir}/layouts/default.yaml \
      --client-dist ${cfg.projectDir}/client/dist \
      --scroll-momentum-friction ${toString cfg.scrollMomentumFriction} \
      --scroll-momentum-cutoff ${toString cfg.scrollMomentumCutoff} \
      --verbose
  '';
in
{
  options.services.deckd-spike = {
    enable = lib.mkEnableOption "deckd spike daemon from a source checkout";

    user = lib.mkOption {
      type = lib.types.str;
      example = "jono";
      description = "User that owns the checkout and runs the deckd user service.";
    };

    projectDir = lib.mkOption {
      type = lib.types.path;
      example = "/home/jono/src/deckd";
      description = "Path to the deckd source checkout.";
    };

    # Issue #66: replaces the old ``lan = bool`` flag with a richer
    # list of bind addresses. Defaults to localhost only on both v4
    # and v6 so a freshly installed daemon is reachable from the
    # host but invisible on the LAN. Operators opt in to a wider
    # surface by setting ``bind = [ "0.0.0.0" ]`` (any-address) or
    # ``bind = [ "iface:wlan0" ]`` (single interface).
    bind = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "127.0.0.1" "::1" ];
      example = [ "0.0.0.0" ];
      description = ''
        Addresses to bind the daemon to. Each entry is either a
        literal IP (v4 or v6) or ``iface:<name>`` to bind every IP
        on the named interface. ``127.0.0.1`` + ``::1`` (localhost
        only) is the default; ``0.0.0.0`` opens all interfaces.
      '';
    };

    port = lib.mkOption {
      type = lib.types.int;
      default = 8765;
      description = "Listen port for the daemon (issue #66).";
    };

    scrollMomentumFriction = lib.mkOption {
      type = lib.types.float;
      default = 0.90;
      description = "Momentum decay per 60Hz frame; values below 1 decay faster.";
    };

    scrollMomentumCutoff = lib.mkOption {
      type = lib.types.int;
      default = 20;
      description = "Stop momentum below this high-resolution-wheel-units/sec velocity.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernelModules = [ "uinput" ];

    services.udev.extraRules = ''
      KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess", OPTIONS+="static_node=uinput"
    '';

    users.groups.input = {};
    users.users.${cfg.user}.extraGroups = [ "input" ];

    systemd.user.services.deckd = {
      description = "deckd spike daemon";
      wantedBy = [ "graphical-session.target" ];
      after = [ "graphical-session.target" ];

      serviceConfig = {
        WorkingDirectory = cfg.projectDir;
        ExecStart = deckdStart;
        Restart = "on-failure";
        RestartSec = 2;
      };
    };
  };
}
