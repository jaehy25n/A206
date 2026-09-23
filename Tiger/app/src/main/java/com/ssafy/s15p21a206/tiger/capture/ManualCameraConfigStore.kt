package com.ssafy.s15p21a206.tiger.capture

import android.content.Context

/**
 * 직전에 맞춘 촬영 조건을 기억한다.
 *
 * calibration 촬영과 dataset 수집은 며칠에 걸쳐 여러 번 돌아가고, 그 사이 값이 같아야 한다는 것이
 * 이 기능의 목적이다. 앱을 다시 켤 때마다 초점을 처음부터 다시 맞춰야 한다면 그 목적을 스스로
 * 깨뜨린다.
 *
 * 저장된 값이 기기 범위를 벗어나면 불러오는 쪽에서 [ManualCameraCapabilities.coerce]로 좁힌다.
 */
class ManualCameraConfigStore(
    context: Context,
) {
    private val preferences = context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** 저장된 값이 없으면 null. 호출부가 기기 기본값을 쓴다. */
    fun load(): ManualCameraConfig? {
        if (!preferences.contains(KEY_ISO)) return null
        return ManualCameraConfig(
            focusDistanceDiopter = preferences.getFloat(KEY_FOCUS, 0f),
            iso = preferences.getInt(KEY_ISO, 0),
            exposureTimeNs = preferences.getLong(KEY_EXPOSURE, ManualCameraConfig.TARGET_FRAME_DURATION_NS),
            frameDurationNs = preferences.getLong(KEY_FRAME_DURATION, ManualCameraConfig.TARGET_FRAME_DURATION_NS),
            whiteBalance = loadWhiteBalance(),
        )
    }

    fun save(config: ManualCameraConfig) {
        preferences
            .edit()
            .putFloat(KEY_FOCUS, config.focusDistanceDiopter)
            .putInt(KEY_ISO, config.iso)
            .putLong(KEY_EXPOSURE, config.exposureTimeNs)
            .putLong(KEY_FRAME_DURATION, config.frameDurationNs)
            .apply()
        saveWhiteBalance(config.whiteBalance)
    }

    private fun loadWhiteBalance(): FixedWhiteBalance? {
        val transform = preferences.getString(KEY_WB_TRANSFORM, null)?.split(',')?.mapNotNull(String::toIntOrNull)
        if (transform == null || transform.size != FixedWhiteBalance.TRANSFORM_SIZE) return null
        return FixedWhiteBalance(
            redGain = preferences.getFloat(KEY_WB_RED, 1f),
            greenEvenGain = preferences.getFloat(KEY_WB_GREEN_EVEN, 1f),
            greenOddGain = preferences.getFloat(KEY_WB_GREEN_ODD, 1f),
            blueGain = preferences.getFloat(KEY_WB_BLUE, 1f),
            transform = transform,
        )
    }

    private fun saveWhiteBalance(whiteBalance: FixedWhiteBalance?) {
        val editor = preferences.edit()
        if (whiteBalance == null) {
            editor.remove(KEY_WB_TRANSFORM).apply()
            return
        }
        editor
            .putFloat(KEY_WB_RED, whiteBalance.redGain)
            .putFloat(KEY_WB_GREEN_EVEN, whiteBalance.greenEvenGain)
            .putFloat(KEY_WB_GREEN_ODD, whiteBalance.greenOddGain)
            .putFloat(KEY_WB_BLUE, whiteBalance.blueGain)
            .putString(KEY_WB_TRANSFORM, whiteBalance.transform.joinToString(","))
            .apply()
    }

    private companion object {
        const val NAME = "capture_preferences"
        const val KEY_FOCUS = "manual_focus_diopter"
        const val KEY_ISO = "manual_iso"
        const val KEY_EXPOSURE = "manual_exposure_ns"
        const val KEY_FRAME_DURATION = "manual_frame_duration_ns"
        const val KEY_WB_RED = "manual_wb_red"
        const val KEY_WB_GREEN_EVEN = "manual_wb_green_even"
        const val KEY_WB_GREEN_ODD = "manual_wb_green_odd"
        const val KEY_WB_BLUE = "manual_wb_blue"
        const val KEY_WB_TRANSFORM = "manual_wb_transform"
    }
}
