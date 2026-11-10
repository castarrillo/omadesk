### Repository URL

https://github.com/castarrillo/omadesk

### Category

Hardware

### Tags

bar, hyprland, quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

Omadesk provides an extended Hyprland display on an Android device over a USB ADB tunnel. Plugin ID: io.github.castarrillo.omadesk. Author: castarrillo.

Manual setup is required after `omarchy plugin add`: run `bash ~/.config/omarchy/plugins/io.github.castarrillo.omadesk/install.sh`. The explicit installer installs missing Arch dependencies through Omarchy, uses sudo/pkexec only for package installation, and can install official AVNC 3.3.1 on the selected USB-authorized Android device if AVNC is absent. The APK has a fixed HTTPS download URL and pinned SHA-256. USB debugging authorization must be approved on Android; it cannot be bypassed.

The v1.2.3 candidate removes host VNC TCP listeners. WayVNC, the RFB proxy and a dedicated ADB server use owner-only filesystem Unix sockets under a 0700 runtime directory; the proxy also enforces SO_PEERCRED. ADB reverse connects Android localhost to the private host socket. No fallback to host TCP is provided. See SECURITY.md for the original v1.2.2 local-account finding, remediation, same-UID/shared-ADB limitations, tests and the trusted-Android assumption. External app installation and dependency installation are not triggered by loading the widget. Maintainers must validate and review the new exact commit; this note does not claim approval of the fix.

Physical hardware testing is limited to a Huawei MRX-W09. Other panel dimensions, mode parsing, USB enrollment errors, RFB negotiation and packaging have automated tests, not universal hardware certification. Current Omarchy and WayVNC compatibility must be verified on the target host. Settings are backed up/preserved, and the explicit uninstaller preserves Android AVNC, host dependencies and user settings. preview.png is a panel screenshot supplied by the maintainer.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
