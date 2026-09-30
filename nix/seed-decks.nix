{ writeShellApplication, coreutils }:
writeShellApplication {
  name = "deckd-seed-decks";
  runtimeInputs = [ coreutils ];
  text = builtins.readFile ./seed-decks.sh;
}
