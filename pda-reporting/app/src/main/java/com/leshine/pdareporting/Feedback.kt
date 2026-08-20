package com.leshine.pdareporting

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator

class Feedback(private val context: Context) {
    private val vibrator = context.getSystemService(Vibrator::class.java)

    fun success() {
        ToneGenerator(AudioManager.STREAM_NOTIFICATION, 75).apply {
            startTone(ToneGenerator.TONE_PROP_ACK, 130)
            android.os.Handler(context.mainLooper).postDelayed({ release() }, 180)
        }
        vibrate(longArrayOf(0, 55))
    }

    fun error() {
        ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80).apply {
            startTone(ToneGenerator.TONE_PROP_NACK, 220)
            android.os.Handler(context.mainLooper).postDelayed({ release() }, 260)
        }
        vibrate(longArrayOf(0, 100, 70, 100))
    }

    private fun vibrate(pattern: LongArray) {
        if (!vibrator.hasVibrator()) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
        } else {
            @Suppress("DEPRECATION") vibrator.vibrate(pattern, -1)
        }
    }
}
