{
  lib,
  # 3.12 rather than the 3.11 floor: nixos-unstable's python311 package
  # set has packages (sphinx-hook among aiohttp's test deps) that no
  # longer support 3.11. CI still tests the declared 3.11 floor.
  python312,
  buildNpmPackage,
  makeWrapper,
  glib,
  xdotool,
  version ? "0.0.1",
}:

let
  # The Vite/React client, built once and served by the daemon at /.
  client = buildNpmPackage {
    pname = "deckd-client";
    inherit version;

    src = lib.fileset.toSource {
      root = ../client;
      fileset = lib.fileset.unions [
        ../client/index.html
        ../client/gallery.html
        ../client/screenshots.html
        ../client/package.json
        ../client/package-lock.json
        ../client/tsconfig.json
        ../client/vite.config.ts
        ../client/.env.production
        ../client/src
        ../client/public
      ];
    };

    npmDepsHash = "sha256-/UG8KBaM6gUAzHHGKGTMPqHgYunmc8JzRfkrNhJtfF4=";
    npmBuildScript = "build";

    installPhase = ''
      runHook preInstall
      mkdir -p $out/share/deckd/client
      cp -r dist/. $out/share/deckd/client/
      runHook postInstall
    '';
  };

  python = python312;
in
python.pkgs.buildPythonApplication {
  pname = "deckd";
  inherit version;

  pyproject = true;
  src = lib.fileset.toSource {
    root = ./..;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../LICENSE
      ../daemon
    ];
  };

  build-system = [ python.pkgs.setuptools ];

  dependencies = with python.pkgs; [
    aiohttp
    pyyaml
    ruamel-yaml
    pydantic
    watchfiles
    psutil
    dbus-fast
    evdev
  ];

  nativeBuildInputs = [ makeWrapper ];

  postInstall = ''
    mkdir -p $out/share/deckd $out/lib/udev/rules.d
    cp -r ${../layouts} $out/share/deckd/layouts
    cp -r ${client}/share/deckd/client $out/share/deckd/client
    install -m 0644 ${../packaging/udev/70-deckd-uinput.rules} \
      $out/lib/udev/rules.d/70-deckd-uinput.rules

    # `nix run` out of the box: serve the bundled client and layouts.
    # Operators override either with later flags (last one wins), and the
    # modules pass a writable --layouts-dir for live editing.
    wrapProgram $out/bin/deckd \
      --prefix PATH : ${lib.makeBinPath [ glib xdotool ]} \
      --add-flags "--client-dist $out/share/deckd/client" \
      --add-flags "--layouts-dir $out/share/deckd/layouts"
  '';

  pythonImportsCheck = [ "deckd" ];

  meta = {
    description = "App-aware touch control surface daemon";
    homepage = "https://github.com/jonocodes/deckd";
    license = lib.licenses.gpl3Plus;
    mainProgram = "deckd";
    platforms = lib.platforms.linux;
  };
}
