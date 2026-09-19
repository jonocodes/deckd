# RETIRED - superseded by the deckd flake.
#
# The spike ran the daemon from a source checkout with a hand-built
# .venv. The flake now packages deckd properly and splits the old job in
# two modules:
#
#   nixosModules.deckd   system prerequisites: uinput module, udev rule,
#                        `input` group, optional firewall port.
#   homeModules.deckd    the user service itself, plus layouts seeding and
#                        the password file. Desktop glue lives next to it:
#                        homeModules.deckd-gnome, homeModules.deckd-kde.
#
# See docs/GUIDE.md ("Nix flake, NixOS, and home-manager") for the
# import snippet, and flake.nix for the package outputs.
{ ... }:
throw ''
  deckd-spike.nix is retired. Import the flake modules instead:

    nixosModules.deckd      # system prerequisites
    homeModules.deckd       # user service (add -gnome or -kde for the focus watcher)

  See docs/GUIDE.md "Nix flake, NixOS, and home-manager".
''
