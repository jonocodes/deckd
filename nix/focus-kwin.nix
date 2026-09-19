{
  lib,
  stdenv,
  version ? "0.0.1",
}:
stdenv.mkDerivation {
  pname = "deckd-focus-kwin";
  inherit version;

  src = ../packaging/kwin-script/deckd-focus;
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/share/kwin/scripts
    cp -r $src $out/share/kwin/scripts/deckd-focus
    runHook postInstall
  '';

  meta = {
    description = "KWin script bridging focused-window events to deckd (KDE Plasma Wayland)";
    homepage = "https://github.com/jonocodes/deckd";
    license = lib.licenses.gpl3Plus;
    platforms = lib.platforms.linux;
  };
}
