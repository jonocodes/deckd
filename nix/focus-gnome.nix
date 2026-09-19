{
  lib,
  stdenv,
  version ? "0.0.1",
}:
stdenv.mkDerivation {
  pname = "deckd-focus-gnome";
  inherit version;

  # Ship the packaging/gnome-shell tree and pick the extension out of it;
  # the UUID directory name (`deckd-focus@local`) stays owned by the
  # extension itself, and `passthru.extensionUuid` mirrors it for
  # home-manager's programs.gnome-shell.extensions.
  src = ../packaging/gnome-shell;
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/share/gnome-shell/extensions
    cp -r $src/deckd-focus@local $out/share/gnome-shell/extensions/deckd-focus@local
    runHook postInstall
  '';

  passthru.extensionUuid = "deckd-focus@local";

  meta = {
    description = "GNOME Shell extension bridging focused-window events to deckd";
    homepage = "https://github.com/jonocodes/deckd";
    license = lib.licenses.gpl3Plus;
    platforms = lib.platforms.linux;
  };
}
