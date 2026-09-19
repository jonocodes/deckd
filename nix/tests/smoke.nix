{ pkgs }:

let
  deckd = pkgs.callPackage ../deckd.nix { };
in
{
  # Boot the packaged daemon on loopback and exercise the surfaces that only
  # exist after install: the wrapper's baked-in client dist and bundled
  # layouts, plus a live aiohttp stack.
  smoke = pkgs.runCommand "deckd-smoke-test"
    {
      nativeBuildInputs = [
        pkgs.curl
        pkgs.jq
        deckd
      ];
    }
    ''
      set -euo pipefail
      export HOME="$TMPDIR"
      port=18765

      deckd --no-focus --no-auth --port "$port" &
      pid=$!
      trap 'kill "$pid" 2>/dev/null || true' EXIT

      for _ in $(seq 1 100); do
        if curl -fsS -o health.json "http://127.0.0.1:$port/health"; then
          break
        fi
        sleep 0.1
      done

      jq -e '.ok == true' health.json >/dev/null

      # The bundled client is served at /.
      curl -fsS -o index.html "http://127.0.0.1:$port/"
      grep -q '<div id="root">' index.html

      # The bundled layouts loaded, with `default` as the fallback.
      curl -fsS -o layouts.json "http://127.0.0.1:$port/layouts"
      jq -e '.ok == true and (.layouts | map(.id) | index("default") != null)' layouts.json >/dev/null

      kill "$pid"
      wait "$pid" 2>/dev/null || true
      trap - EXIT
      touch $out
    '';
}
