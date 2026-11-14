{
  description = "deckd - app-aware touch control surface";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # ADR-0013: releases are versioned by git tag (CalVer), which a flake
      # source doesn't carry. Identify a flake build by commit date + rev.
      version = "0+git.${builtins.substring 0 8 (self.lastModifiedDate or "19700101")}.g${
        self.shortRev or self.dirtyShortRev or "dirty"
      }";

      # Exported modules default `services.deckd.package` to this flake's own
      # build, so the service reports the flake's version (the module files
      # alone fall back to an unversioned callPackage). Keyed so importing
      # several of the modules defines the default once.
      flakePackage =
        { pkgs, lib, ... }:
        {
          key = "deckd#flake-package";
          services.deckd.package = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.deckd;
        };
      withFlakePackage = module: {
        imports = [
          module
          flakePackage
        ];
      };
    in
    {
      packages = forAllSystems (pkgs: rec {
        deckd = pkgs.callPackage ./nix/deckd.nix { inherit version; };
        deckd-focus-gnome = pkgs.callPackage ./nix/focus-gnome.nix { inherit version; };
        deckd-focus-kwin = pkgs.callPackage ./nix/focus-kwin.nix { inherit version; };
        default = deckd;
      });

      nixosModules = rec {
        deckd = withFlakePackage ./nix/modules/nixos.nix;
        default = deckd;
      };

      homeModules = rec {
        deckd = withFlakePackage ./nix/modules/home.nix;
        deckd-gnome = withFlakePackage ./nix/modules/home-gnome.nix;
        deckd-kde = withFlakePackage ./nix/modules/home-kde.nix;
        default = deckd;
      };

      checks = forAllSystems (
        pkgs:
        import ./nix/tests {
          inherit pkgs home-manager;
          lib = nixpkgs.lib;
        }
      );
    };
}
