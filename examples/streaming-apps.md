# GMS-free streaming apps (verified on RK3326 / Android 8.1 / armeabi-v7a)

Panel has NO Google Play Services -> only GMS-free clients install.

| App | Package | Source | Notes |
|---|---|---|---|
| SmartTube | `org.smarttube.stable` | github.com/yuliskov/SmartTube | ship the **armeabi-v7a** asset |
| NewPipe | `org.schabi.newpipe` | github.com/TeamNewPipe/NewPipe | universal APK works |
| Jellyfin (libre) | `org.jellyfin.mobile` | github.com/jellyfin/jellyfin-android | **libre** build = no Google deps |
| RockVideoPlayer | `android.rk.RockVideoPlayer` | bundled by vendor | re-enable if debloated: `pm enable --user 0` |

## Install
```bash
# ALWAYS verify ABI before installing
aapt2 dump badging App.apk | grep -E '^package:|sdkVersion|native-code'
adb install -r App.apk
```

## Launch from the dashboard (WebView honours intent://)
```yaml
- type: bookmarks
  links:
    - title: SmartTube
      url: intent://browse#Intent;package=org.smarttube.stable;end
```

## Return to the kiosk after an app
```bash
adb shell input keyevent 3     # HOME
```

## Not possible
Netflix / Disney+ / Prime Video — require Widevine **L1** + device certification.
Uncertified SoCs (RK3326 etc.) are L3 at best.
