# punpun Thai input

The keyboard the punpun Agent types captions with on Android phones (Thai, emoji, hashtags). It is
installed by the Agent on request ("ติดตั้งคีย์บอร์ดพิมพ์ไทย" in the Agent's settings window) and is
never made the phone's keyboard: the Agent switches to it only while it types a caption and switches
back to the owner's keyboard right after.

## Origin and licence

A modified version of **ADBKeyBoard** by senzhk, https://github.com/senzhk/ADBKeyBoard (commit
`8dd0b6924e45ac5565f77f13cf8e8eaf47dbb1b0`), licensed under the GNU General Public License version 2.
This keyboard is under the same licence: see `LICENSE`. It is a separate program from the punpun Agent,
which talks to it only through `adb shell am broadcast`.

Changes by punpun (2026-10-11):
- own package (`app.punpun.keyboard`), name and icon;
- only the two broadcasts the Agent uses: `ADB_INPUT_B64` (type UTF-8 text given as Base64 in `msg`)
  and `ADB_CLEAR_TEXT`; the others were removed;
- the receiver accepts broadcasts only from senders holding `android.permission.DUMP` (the adb shell
  and the system), so other apps on the phone cannot type through it;
- registered as an exported receiver as Android 14+ requires, and built for current Android
  (target SDK 36, minimum 24): Google Play Protect blocks ADBKeyBoard as built for an older Android.

## Build

`python build_keyboard.py` in the punpun repository (`tools/build_keyboard.py`, also in the source zip)
builds it with the Android SDK (build-tools 34.0.0, platform android-34) and a JDK 11+, without Gradle:
aapt2, javac, d8, zipalign, apksigner. The release APK is signed with punpun's key.

## Use

    adb shell ime enable app.punpun.keyboard/.PunpunIME
    adb shell ime set app.punpun.keyboard/.PunpunIME
    adb shell am broadcast -a ADB_INPUT_B64 --es msg <base64 of the UTF-8 text>
    adb shell ime set <the previous keyboard>
