# macOS Release Process

The macOS release is a native Apple Silicon application bundle distributed in a DMG. It uses the
same SQLite database and Supabase synchronization protocol as the Windows release. Local data lives
under `~/Library/Application Support/ICUPatientTracker`, and remembered refresh tokens are stored in
the user's macOS login Keychain.

## Compatibility

- macOS 13 or newer
- Apple Silicon (`arm64`) for the automated build
- A separately built Intel (`x86_64`) DMG is required for Intel Macs

The Windows ZIP cannot run on macOS, and the macOS DMG cannot run on Windows.
The in-app shortcuts continue to work, but the Windows-only system-wide shortcuts are not registered
on macOS. The menu-bar tray icon remains the supported way to reopen a hidden resident window.

## Local Mac build

Install Xcode Command Line Tools and Python 3.12 or newer, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
bash scripts/build_macos.sh
```

The script runs linting, type checking, the test suite, a packaged smoke test, DMG creation, and a
SHA-256 checksum. The output is `dist/icu-patient-tracker-<version>-macos-<architecture>.dmg`.

## Automated unsigned build

Push the repository to GitHub and run **Build macOS release** from the Actions tab. Download the
artifact after the workflow succeeds. This is useful for internal testing but is not suitable for
frictionless distribution because Gatekeeper may block an unsigned app.

## Combined GitHub release

After both operating-system builds are production-ready, push a version tag matching the version in
`pyproject.toml`, for example `v0.1.0`. The **Publish desktop release** workflow builds Windows and
Apple Silicon packages independently, requires both build and smoke-test jobs to pass, and then
publishes both installers and their checksums on one GitHub Release. Private-repository releases are
available only to GitHub users who have been granted access to the repository.

Without an Apple Developer Program membership, the release workflow publishes an unsigned Mac test
build and gives recipients explicit Gatekeeper instructions. Once membership is available, add
these encrypted repository secrets before pushing a later release tag:

- `MACOS_CERTIFICATE_P12`: base64-encoded Developer ID Application certificate export
- `MACOS_CERTIFICATE_PASSWORD`: password used when exporting that `.p12`
- `MACOS_SIGNING_IDENTITY`: exact Developer ID Application identity
- `APPLE_ID`: Apple Developer account email
- `APPLE_TEAM_ID`: Apple Developer team identifier
- `APPLE_APP_PASSWORD`: app-specific password used by Apple's notary service

The certificate and Apple credentials are imported into an ephemeral build Keychain and are never
written to the repository or included in either application package.

## Signing and notarization

Public distribution requires an Apple Developer ID Application certificate. Import that certificate
into the Mac's login Keychain, then set its exact identity before building:

```bash
export MACOS_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
bash scripts/build_macos.sh
```

For notarization, first create a `notarytool` Keychain profile using Apple's credentials, then set:

```bash
export MACOS_NOTARY_PROFILE="icu-patient-tracker-notary"
bash scripts/build_macos.sh
```

The script submits the DMG, waits for Apple's result, and staples the accepted ticket. Do not send a
clinical production release until the signed DMG has also been opened, launched, synchronized, and
backed up on a clean Mac matching the recipient hardware.
