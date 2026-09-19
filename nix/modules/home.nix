# deckd as a per-user session service.
#
# deckd watches the focused window and injects input, so it must run
# inside the logged-in graphical session (session D-Bus, /dev/uinput),
# not as a system service. This module owns that unit; the system-wide
# prerequisites (kernel module, udev rule, input group) live in the
# NixOS module (`nixosModules.deckd`).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.deckd;

  seedLayouts = pkgs.callPackage ../seed-layouts.nix { };

  # Quote each argument so paths with spaces survive systemd's parsing.
  execStart = lib.concatStringsSep " " (
    [ (lib.getExe cfg.package) ]
    ++ lib.concatMap (addr: [
      "--bind"
      (lib.escapeShellArg addr)
    ]) cfg.bind
    ++ [
      "--port"
      (toString cfg.port)
      "--layouts-dir"
      (lib.escapeShellArg (toString cfg.layoutsDir))
    ]
    ++ lib.optionals (cfg.passwordFile != null) [
      "--password-file"
      (lib.escapeShellArg (toString cfg.passwordFile))
    ]
    ++ cfg.extraArgs
  );
in
{
  options.services.deckd = {
    enable = lib.mkEnableOption "deckd, as a user service in the graphical session";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../deckd.nix { };
      defaultText = lib.literalExpression "the deckd flake package";
      description = "The deckd package to run.";
    };

    bind = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "0.0.0.0" ];
      description = ''
        Extra addresses to bind, each a literal IP or `iface:<name>`.
        The default is empty, which leaves the daemon's own
        localhost-only default (`127.0.0.1` and `::1`) in place. Set
        `[ "0.0.0.0" ]` to expose the surface on the LAN.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8765;
      description = "Listen port for the daemon.";
    };

    layoutsDir = lib.mkOption {
      type = lib.types.path;
      default = "${config.xdg.configHome}/deckd/layouts";
      defaultText = lib.literalExpression ''"''${config.xdg.configHome}/deckd/layouts"'';
      description = ''
        Writable directory of layout YAML. Seed defaults are copied in
        on activation (see {option}`seedLayouts`), and the GUI editor
        saves here.
      '';
    };

    seedLayouts = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Copy the package's bundled layouts into
        {option}`layoutsDir` when they are missing. Existing files are
        never overwritten, so edits always win. Disable when the
        directory is managed elsewhere (for example checked in to a
        dotfiles repo).
      '';
    };

    passwordFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      example = "/run/secrets/deckd-password";
      description = ''
        Shared password clients must present. When null, the daemon
        reads (or generates on first start) `$XDG_CONFIG_HOME/deckd/password`.
      '';
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "--verbose" ];
      description = "Extra command-line flags appended to the daemon's ExecStart.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.isLinux;
        message = "services.deckd is a Linux session service; on macOS use the launchd agent (see docs/GUIDE.md).";
      }
    ];

    systemd.user.services.deckd = {
      Unit = {
        Description = "deckd - app-aware touch control surface";
        After = [ "graphical-session.target" ];
        PartOf = [ "graphical-session.target" ];
      };

      Service = {
        ExecStart = execStart;
        Restart = "on-failure";
        RestartSec = 2;
      };

      Install.WantedBy = [ "graphical-session.target" ];
    };

    home.activation.deckdSeedLayouts = lib.mkIf cfg.seedLayouts (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        run ${lib.getExe seedLayouts} ${lib.escapeShellArg "${cfg.package}/share/deckd/layouts"} ${lib.escapeShellArg (toString cfg.layoutsDir)}
      ''
    );
  };
}
