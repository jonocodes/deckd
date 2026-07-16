# Spike-only NixOS module for running deckd from a source checkout.
#
# Example:
#   imports = [ /home/jono/src/deckd/packaging/nixos/deckd-spike.nix ];
#
#   services.deckd-spike = {
#     enable = true;
#     user = "jono";
#     projectDir = "/home/jono/src/deckd";
#     lan = true;
#   };
#
# Before starting the service, run once from the checkout:
#   just setup
#   just build-client
{ config, lib, pkgs, ... }:

let
  cfg = config.services.deckd-spike;
  hostFlag = if cfg.lan then "--host 0.0.0.0" else "";
  deckdStart = pkgs.writeShellScript "deckd-spike-start" ''
    exec ${cfg.projectDir}/.venv/bin/deckd ${hostFlag} \
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

    lan = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Bind the daemon to 0.0.0.0 for phone/tablet testing.";
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
