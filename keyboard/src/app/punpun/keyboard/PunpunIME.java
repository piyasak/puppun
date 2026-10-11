/*
 * punpun Thai input: types text sent over adb, for the punpun Agent.
 *
 * Based on ADBKeyBoard by senzhk (https://github.com/senzhk/ADBKeyBoard, commit 8dd0b69),
 * GPL-2.0. Changes by punpun (2026-10-11): own package and name; only the two broadcasts the
 * Agent uses (ADB_INPUT_B64, ADB_CLEAR_TEXT); the receiver accepts broadcasts only from senders
 * holding android.permission.DUMP (the adb shell and the system, never another app) and is
 * registered as exported, as Android 14+ requires; built for current Android versions.
 *
 * This program is free software; you can redistribute it and/or modify it under the terms of the
 * GNU General Public License version 2 as published by the Free Software Foundation. It is
 * distributed WITHOUT ANY WARRANTY; see the LICENSE file.
 */
package app.punpun.keyboard;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.inputmethodservice.InputMethodService;
import android.os.Build;
import android.util.Base64;
import android.view.View;
import android.view.inputmethod.ExtractedText;
import android.view.inputmethod.ExtractedTextRequest;
import android.view.inputmethod.InputConnection;

import java.nio.charset.StandardCharsets;

public class PunpunIME extends InputMethodService {
    static final String TYPE_B64 = "ADB_INPUT_B64";
    static final String CLEAR = "ADB_CLEAR_TEXT";
    static final String SENDER_PERMISSION = "android.permission.DUMP";  // shell and system only

    private BroadcastReceiver receiver;

    @Override
    public void onCreate() {
        super.onCreate();
        IntentFilter filter = new IntentFilter(TYPE_B64);
        filter.addAction(CLEAR);
        receiver = new Receiver();
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(receiver, filter, SENDER_PERMISSION, null, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(receiver, filter, SENDER_PERMISSION, null);
        }
    }

    @Override
    public View onCreateInputView() {
        return getLayoutInflater().inflate(R.layout.view, null);
    }

    @Override
    public void onDestroy() {
        if (receiver != null) {
            unregisterReceiver(receiver);
            receiver = null;
        }
        super.onDestroy();
    }

    class Receiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            InputConnection ic = getCurrentInputConnection();
            if (ic == null || intent.getAction() == null) {
                return;
            }
            if (intent.getAction().equals(TYPE_B64)) {
                String data = intent.getStringExtra("msg");
                if (data == null) {
                    return;
                }
                byte[] bytes;
                try {
                    bytes = Base64.decode(data, Base64.DEFAULT);
                } catch (IllegalArgumentException e) {
                    return;  // not Base64: type nothing
                }
                ic.commitText(new String(bytes, StandardCharsets.UTF_8), 1);
            } else if (intent.getAction().equals(CLEAR)) {
                ExtractedText all = ic.getExtractedText(new ExtractedTextRequest(), 0);
                if (all == null || all.text == null) {
                    return;
                }
                CharSequence before = ic.getTextBeforeCursor(all.text.length(), 0);
                CharSequence after = ic.getTextAfterCursor(all.text.length(), 0);
                ic.deleteSurroundingText(before == null ? 0 : before.length(), after == null ? 0 : after.length());
            }
        }
    }
}
