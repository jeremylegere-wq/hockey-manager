# Releasing

## Versioning

* **Authoritative version:** `VERSION` in `hs/ui/settings.py` (shown in Help > About and sent with bug reports).
  `BUILD` in the same file labels each build sent to testers; it is not part of a release tag.
* **Scheme:** `MAJOR.MINOR`, with a third number only for a fix to a release already out (`0.61`, then `0.62`, then
  `0.62.1`). Each feature release raises MINOR, which matches the `vNN` labels used in `docs/`. Stay below 1.0 until
  saves are meant to stay compatible between releases.
* **Tag:** `v` + `VERSION`, exactly (`VERSION = "0.62"` is tag `v0.62`). The release workflow refuses any other tag.
* **Notes:** `CHANGELOG.md`. The release body is the section whose heading is `## [VERSION] - YYYY-MM-DD`.

## Checks

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every pull request. Run the same locally from the
repository root; there is nothing to install.

```bash
python3 scripts/release_check.py            # repository checks, Python 3.9 syntax, changelog present
python3 -m unittest discover -s tests       # the test suite (several minutes)
python3 -m unittest tests.test_v61 -v       # one file while you work
```

`release_check.py` also fails if a save (`*.db`), a world or a pack other than the example is tracked, so data derived from
third parties cannot be published by accident.

## Making a release

1. Make sure `main` is green on GitHub and your clone is up to date (`git checkout main && git pull`).
2. Set `VERSION` in `hs/ui/settings.py` (and `BUILD` if you use it).
3. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y] - YYYY-MM-DD` and add an empty `## [Unreleased]` above it.
4. Check: `python3 scripts/release_check.py --tag vX.Y` and the test suite.
5. Commit (`git commit -am "Release X.Y"`) and push to `main`; wait for CI.
6. Tag that commit and push the tag:
   ```bash
   git tag -a vX.Y -m "Hockey Manager X.Y"
   git push origin vX.Y
   ```
7. The **Release** workflow (`.github/workflows/release.yml`) runs the checks and the tests on Python 3.9 and 3.13, builds
   the source archive from the tag with `git archive`, and creates a **draft** GitHub Release with the changelog section as its
   notes. Open Releases, check the notes and the files, then **Publish release**.

Attached to each release: `hockey-manager-X.Y.zip` and `.tar.gz` (the tagged source, byte-for-byte reproducible with
`git archive`) and `SHA256SUMS`. Nothing is published to PyPI or anywhere else; the game has no packaged install.

To rehearse without a tag: Actions > Release > **Run workflow**. It runs the same checks and builds the archives as a
downloadable workflow artifact, and creates no release.

If a release is wrong: delete the draft, fix `main`, delete the tag locally and on GitHub
(`git tag -d vX.Y && git push origin :refs/tags/vX.Y`), and tag again. Once published, prefer a new fix release.

## Permissions

Workflows get a read-only token. Only the final release job has `contents: write`, and it runs only for a tag pushed by
someone with write access to the repository. No secrets, personal access tokens or third-party actions are used (only
`actions/checkout` and `actions/setup-python`; Dependabot proposes updates to them monthly).
