{ pkgs, home-manager, lib }:

let
  focusGnome = pkgs.callPackage ../focus-gnome.nix { };

  # ---------------------------------------------------------------------
  # NixOS module: system prerequisites only (the daemon itself is a user
  # service owned by the home-manager module).
  # ---------------------------------------------------------------------
  nixos = lib.nixosSystem {
    modules = [
      ../modules/nixos.nix
      {
        nixpkgs.hostPlatform = pkgs.stdenv.hostPlatform.system;
        system.stateVersion = "25.05";
        services.deckd = {
          enable = true;
          users = [ "alice" ];
          openFirewall = true;
        };
      }
    ];
  };

  nixosProbe = pkgs.writeText "nixos-probe.json" (builtins.toJSON {
    kernelModules = nixos.config.boot.kernelModules;
    udevPackages = map toString nixos.config.services.udev.packages;
    aliceGroups = nixos.config.users.users.alice.extraGroups;
    firewallPorts = nixos.config.networking.firewall.allowedTCPPorts;
  });

  nixosTest = pkgs.runCommand "deckd-nixos-module-test" {
    nativeBuildInputs = [ pkgs.jq ];
  } ''
    set -euo pipefail
    probe=${nixosProbe}
    jq -e '.kernelModules | index("uinput")' "$probe" >/dev/null
    jq -e '[.udevPackages[] | select(contains("deckd"))] | length == 1' "$probe" >/dev/null
    jq -e '.aliceGroups | index("input")' "$probe" >/dev/null
    jq -e '.firewallPorts | index(8765)' "$probe" >/dev/null
    touch $out
  '';

  # ---------------------------------------------------------------------
  # home-manager base module: owns the user service, layouts, password.
  # ---------------------------------------------------------------------
  homeBase = {
    home.username = "alice";
    home.homeDirectory = "/home/alice";
    home.stateVersion = "25.05";
  };

  home = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      ../modules/home.nix
      homeBase
      {
        services.deckd = {
          enable = true;
          bind = [
            "0.0.0.0"
            "iface:wlan0"
          ];
          port = 9000;
          layoutsDir = "/home/alice/my-layouts";
          passwordFile = "/run/secrets/deckd-password";
          extraArgs = [ "--verbose" ];
        };
      }
    ];
  };

  homeProbe = pkgs.writeText "home-probe.json" (builtins.toJSON {
    execStart = home.config.systemd.user.services.deckd.Service.ExecStart;
    after = home.config.systemd.user.services.deckd.Unit.After;
    partOf = home.config.systemd.user.services.deckd.Unit.PartOf;
    wantedBy = home.config.systemd.user.services.deckd.Install.WantedBy;
    restart = home.config.systemd.user.services.deckd.Service.Restart;
    activation = home.config.home.activation.deckdSeedLayouts;
  });

  homeTest = pkgs.runCommand "deckd-home-module-test" {
    nativeBuildInputs = [ pkgs.jq ];
  } ''
    set -euo pipefail
    probe=${homeProbe}
    jq -e '.execStart[0] | ([scan("--bind")] | length) == 2' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("0.0.0.0")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("iface:wlan0")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("--port 9000")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("--layouts-dir")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("/home/alice/my-layouts")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("--password-file")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("/run/secrets/deckd-password")' "$probe" >/dev/null
    jq -e '.execStart[0] | contains("--verbose")' "$probe" >/dev/null
    jq -e '.after | index("graphical-session.target")' "$probe" >/dev/null
    jq -e '.partOf | index("graphical-session.target")' "$probe" >/dev/null
    jq -e '.wantedBy | index("graphical-session.target")' "$probe" >/dev/null
    jq -e '.restart == "on-failure"' "$probe" >/dev/null
    jq -e '.activation.data | contains("deckd-seed-layouts")' "$probe" >/dev/null
    touch $out
  '';

  # =====================================================================
  # GNOME: base module plus the Shell extension, enabled via dconf.
  # =====================================================================
  homeGnome = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      ../modules/home-gnome.nix
      homeBase
      { services.deckd.enable = true; }
    ];
  };

  gnomeProbe = pkgs.writeText "gnome-probe.json" (builtins.toJSON {
    ids = map (e: e.id) homeGnome.config.programs.gnome-shell.extensions;
    enabled = homeGnome.config.dconf.settings."org/gnome/shell"."enabled-extensions";
    extensionUuid = focusGnome.extensionUuid;
  });

  gnomeTest = pkgs.runCommand "deckd-gnome-module-test" {
    nativeBuildInputs = [ pkgs.jq ];
  } ''
    set -euo pipefail
    probe=${gnomeProbe}
    jq -e '.extensionUuid == "deckd-focus@local"' "$probe" >/dev/null
    jq -e '.ids | index("deckd-focus@local")' "$probe" >/dev/null
    jq -e '.enabled | index("deckd-focus@local")' "$probe" >/dev/null

    # Realise the extension bundle (not just its metadata) so a broken
    # installPhase fails CI.
    test -f ${focusGnome}/share/gnome-shell/extensions/deckd-focus@local/extension.js
    touch $out
  '';

  # =====================================================================
  # KDE: base module plus the KWin script install activation.
  # =====================================================================
  homeKde = home-manager.lib.homeManagerConfiguration {
    inherit pkgs;
    modules = [
      ../modules/home-kde.nix
      homeBase
      { services.deckd.enable = true; }
    ];
  };

  kdeProbe = pkgs.writeText "kde-probe.json" (builtins.toJSON {
    activation = homeKde.config.home.activation.deckdKwin;
  });

  kdeTest = pkgs.runCommand "deckd-kde-module-test" {
    nativeBuildInputs = [ pkgs.jq ];
  } ''
    set -euo pipefail
    probe=${kdeProbe}
    jq -e '.activation.data | contains("deckd-install-kwin")' "$probe" >/dev/null
    jq -e '.activation.data | contains("deckd-focus")' "$probe" >/dev/null
    touch $out
  '';

in
{
  nixos-module = nixosTest;
  home-module = homeTest;
  gnome-module = gnomeTest;
  kde-module = kdeTest;
}
