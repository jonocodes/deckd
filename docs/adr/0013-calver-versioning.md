# Versioning: CalVer `vYYYY.M.MICRO`, with the git tag as the only source

deckd had release mechanics (a `v*` tag runs the release workflows and
names the artifacts) but no versioning scheme, three hard-coded `0.0.1`
copies that nothing bumped (`pyproject.toml`, `deckd/__init__.py`,
`client/package.json`, plus one inside the `/diag` payload), and no way for a
running daemon to say which release it is. This ADR picks the scheme, makes
the tag the single source, and makes the version visible.

## Context

- **No compatibility promise for SemVer to encode.** The client is served by
  the daemon it talks to, so the two always ship together; there is no
  public API with independent consumers. The one user-facing format that
  could break is deck YAML, and deck changes are handled by keeping old
  fields working (the editor passes unknown fields through), not by a major
  version.
- **What users ask is "how recent is this?"** A date answers that directly.
- **Three-integer constraint.** macOS's `CFBundleShortVersionString` is three
  period-separated integers, and the DMG stamps the tag into it.
- **Tooling.** Tags become PEP 440 versions (`setuptools-scm`) and file
  names; the format has to survive both without normalisation surprises.

## Decision

### Scheme: `vYYYY.M.MICRO`

- `YYYY` and `M` are the release's UTC year and month, **not zero-padded**
  (`v2027.1.0`, not `v2027.01.0`): leading zeros are invalid in SemVer-shaped
  tooling and PEP 440 strips them, so the tag and the package version would
  disagree.
- `MICRO` counts releases within the month, starting at `0`.
  `v2026.11.0`, `v2026.11.1`, … then `v2026.12.0`.
- Release candidates take a suffix — `v2026.12.0-rc1` — and publish as a
  GitHub prerelease. An rc doesn't use up its number.

Rejected: `vYYYY.MM.DD`. It reads well, but a second release on the same day
needs a fourth component, which breaks the macOS three-integer rule and
special-cases the common "fix right after a release" path.

Rejected: SemVer `0.x`. Its value is signalling breaking changes to
independent consumers; deckd has none (see Context).

### The tag is the only source of truth

- `setuptools-scm` derives the package version from the nearest
  `v[1-9][0-9][0-9][0-9].*` tag and writes `deckd/_version.py` at install
  time (gitignored). The match skips non-release tags
  (`verify/61-touch-targets`) and the pre-CalVer `v0.0.0-*` rehearsal tags.
- On a tag: exactly the tag (`2026.11.0`). After it: `version_scheme =
  "no-guess-dev"` gives `2026.11.0.post1.dev3+g<sha>` — "after this release",
  without guessing the next name. No git (a sandboxed build without a
  pretend version): `0+unknown`.
- The hard-coded copies are gone. `client/package.json` and the root
  `package.json` have no version (both are private); the client shows the
  daemon's.
- The Nix flake has no `.git`, so it passes `0+git.<date>.g<rev>` from
  `self` via `SETUPTOOLS_SCM_PRETEND_VERSION`. The exported NixOS and
  home-manager modules default their package to the flake's own build so
  the service reports that version.
- `DECKD_VERSION` remains the override for *artifact names* (release CI sets
  it to the tag minus `v`, so file names match the tag verbatim). The
  frozen app's runtime version comes from `setuptools-scm`; release
  checkouts use full history so it sees the tag, and the Linux release job
  asserts the frozen tarball's `--version` equals the tag.

### Visible

`/health` carries `version` (readable before auth, like the rest of
`/health`, because a bug report needs it), as does `/diag`. `deckd --version`
and `deckctl --version` print it, `deckctl status` leads with it, and the
client's settings diagnostics show it.

### Cutting a release

`just release` fetches tags, refuses unless the tree is clean and `HEAD` is
`origin/main`, computes the next tag (`scripts/next_version.py`, unit-tested),
shows it with the commit, and on confirmation creates and pushes the
annotated tag. The push runs both release workflows, which publish only after
every platform's build and tests pass.

## Consequences

- No version bump commits, ever; a release is a tag.
- An editable install's version is as fresh as its last `just setup`;
  `just version` reads git live when `setuptools-scm` is installed (the dev
  extra).
- Until the first CalVer tag exists, dev builds report a placeholder
  (`0.post1.devN+unknown.g<sha>`).
- The macOS DMG's `CFBundleShortVersionString` is the tag verbatim; release
  tags fit the three-integer rule, and PR builds (`0.0.0-prN`) were already
  tolerated.
