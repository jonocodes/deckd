{ pkgs, home-manager, lib }:
(import ./scripts.nix { inherit pkgs; })
// (import ./modules.nix {
  inherit pkgs home-manager lib;
})
// (import ./smoke.nix { inherit pkgs; })
