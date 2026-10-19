# Mac installation and quick start

## Before you download

This release supports **Apple Silicon (M1 or later)** and **macOS 13 or newer**.
Choose Apple menu > About This Mac: an Apple chip is supported; an Intel processor needs
a separate Intel build, which this release does not provide.

## Install and open the app

1. Open the project's [GitHub Releases](https://github.com/magicjoe7s/Patient_Tracker_Application/releases).
   Open the release you intend to install, including its prerelease label and security notice.
2. Under **Assets**, download both `icu-patient-tracker-<version>-macos-arm64.dmg`
   and `SHA256SUMS-macos-arm64.txt` from that **same release**.
   Do not choose the Windows ZIP, Source code, or an Actions artifact ZIP.
3. Verify the download. Open **Terminal**, enter `cd ~/Downloads`, then run:
   ```bash
   shasum -a 256 -c SHA256SUMS-macos-arm64.txt
   ```
   The DMG must report **OK**. Keep both downloads in that directory with their original names.
   If you saved them elsewhere, change to that folder instead. A missing-file error means
   the folder or filename is wrong; a checksum mismatch means download both files again.
4. Double-click the DMG in Finder. Drag **ICU Patient Tracker.app** onto **Applications**.
   When updating, exit the old app from its menu-bar icon first, then replace the application.
   Replacing the application does not delete the separate patient database.
5. Eject the mounted **ICU Patient Tracker** disk. In Finder, open **Applications** and
   double-click **ICU Patient Tracker**.
6. If macOS says the developer cannot be verified or Apple cannot check the app for
   malicious software, dismiss that alert. For an unsigned build you have verified and
   chosen to trust, open **Apple menu > System Settings > Privacy & Security**.
7. Scroll to **Security**, find the message naming **ICU Patient Tracker**, and click
   **Open Anyway**. Authenticate with your password or Touch ID if requested.
8. Confirm **Open** in the next dialog. Once accepted, open the app normally from Applications.

The security exception is for this app. Do not disable Gatekeeper system-wide.
**Open Anyway** normally appears for about an hour after the blocked attempt; try opening
the installed app again if the message has disappeared. On a managed Mac, an administrator
may restrict this option. Follow [Apple's official guidance](https://support.apple.com/en-ie/102445).

A checksum confirms that your download matches the release asset. It does not replace Apple's
Developer ID verification or notarization. The release notes state the actual signing status.

## Other errors

- **Wrong architecture / unsupported macOS:** Check About This Mac against the requirements above.
  The Windows ZIP cannot run on a Mac, and this Apple Silicon DMG does not support Intel Macs.
- **Checksum mismatch, DMG will not mount, or download incomplete:** Delete that downloaded
  installer and its checksum file, then download both again from the same official release.
  Do not use Open Anyway to resolve a checksum mismatch.
- **“App is damaged” / “Move to Trash”:** This differs from an unidentified-developer warning.
  Verify the checksum, copy a fresh app to Applications, and retry. If it persists, retain the
  exact message and report your macOS version and Mac chip in a GitHub issue. Do not remove
  quarantine attributes or bypass a malware warning as a routine installation step.
- **App closes after opening:** Report the exact behavior, release version, macOS version,
  and chip. Logs are in `~/Library/Application Support/ICUPatientTracker/logs`.
  Remove patient-identifying information before sharing logs.

## Quick start for this Mac update

- **Patient sidebar:** Drag its divider left or right. It starts at 190 pixels and can shrink
  to 150 pixels. Long names are shortened visually; hover for the full name. Use the arrow
  control to collapse or restore it. The last width is remembered.
- **Charting:** The lower-left box has **Dx** and **Devices/Lines** tabs. Dx opens first.
  Edit diagnostic results here or in the full **Diagnostics** tab; they share the same text,
  autosave, recovery, and SOAP mapping. Double-click for the larger diagnostic editor.
- **Devices:** Check a device and press Enter through each prompt to leave size, location,
  or placement date unknown. A selected jugular/saphenous device retains that implied location.
  Enter a known date as **YYYY-MM-DD**. Cancel aborts adding the device. Unknown dates remain
  unknown in saved records and SOAP notes.
- **SOAP:** The daytime ICU resident starts as `#INPUT#`. Enter your preferred name in
  **Settings** to use it in new notes. Existing saved notes are preserved.
- **Reopen:** Closing the main window hides the resident app. Use its menu-bar icon to reopen
  it and **Exit** in that menu to quit.
- **Protect your records:** Create a backup before updating. Local data remains in
  `~/Library/Application Support/ICUPatientTracker`, outside the application bundle.

## Mac and Windows synchronization

Update **both** Mac and Windows to **0.1.5 or newer compatible releases** before enabling sync
with these records. Windows receives data compatibility support; its chart layout and device
entry requirements stay unchanged. Version 0.1.5 can read released version-1 patient snapshots
and writes version 4, which supports unknown placement dates. Versions 2 and 3 were used by
separate development features and are not reinterpreted by this release.

The server must accept version 4 before updated clients sync. Administrators should apply the
optional-device snapshot migration described in [Supabase setup](SupabaseSetup.md).
Never resolve a version error by clearing the database or forcing a local/server overwrite.
If a client reports an unsupported format, install a compatible client for that data first.
