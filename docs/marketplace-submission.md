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

Both VNC endpoints listen only on loopback (5909/5910); image and input travel through adb reverse, not Wi-Fi. Host-local processes can access these unauthenticated ports. The plugin does not enable wireless ADB or modify firmware. It maintains its headless output geometry while connected, including recovery from compositor reloads. External app installation and dependency installation are not triggered by loading the widget.

Physical hardware testing is limited to a Huawei MRX-W09. Other panel dimensions, mode parsing, USB enrollment errors, RFB negotiation and packaging have automated tests, not universal hardware certification. Current Omarchy and WayVNC compatibility must be verified on the target host. Settings are backed up/preserved, and the explicit uninstaller preserves Android AVNC, host dependencies and user settings. preview.png is a panel screenshot supplied by the maintainer.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
