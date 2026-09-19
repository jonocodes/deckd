{ writeShellApplication, coreutils }:
writeShellApplication {
  name = "deckd-seed-layouts";
  runtimeInputs = [ coreutils ];
  text = builtins.readFile ./seed-layouts.sh;
}
