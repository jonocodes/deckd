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
    in
    {
      packages = forAllSystems (pkgs: rec {
        deckd = pkgs.callPackage ./nix/deckd.nix { };
        deckd-focus-gnome = pkgs.callPackage ./nix/focus-gnome.nix { };
        deckd-focus-kwin = pkgs.callPackage ./nix/focus-kwin.nix { };
        default = deckd;
      });

      nixosModules = rec {
        deckd = ./nix/modules/nixos.nix;
        default = deckd;
      };

      homeModules = rec {
        deckd = ./nix/modules/home.nix;
        deckd-gnome = ./nix/modules/home-gnome.nix;
        deckd-kde = ./nix/modules/home-kde.nix;
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
