package com.ssafy.s15p21a206.tiger.capture

import android.content.Context
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution

/**
 * 직전에 고른 녹화 해상도를 기억한다. 다음 수집의 기본값으로 쓴다.
 *
 * 저장된 값이 더 이상 지원되지 않으면 기본값으로 되돌린다. 앱 갱신으로 후보가 줄어도
 * 고를 수 없는 해상도가 기본값으로 뜨지 않게 한다.
 */
class RecordingResolutionStore(
    context: Context,
) {
    private val preferences = context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun load(): RecordingResolution {
        val width = preferences.getInt(KEY_WIDTH, 0)
        val height = preferences.getInt(KEY_HEIGHT, 0)
        val stored = RecordingResolution(width, height)
        return if (RecordingInputValidator.supportedResolutions.contains(stored)) stored else RecordingInputValidator.DEFAULT_RESOLUTION
    }

    fun save(resolution: RecordingResolution) {
        preferences
            .edit()
            .putInt(KEY_WIDTH, resolution.width)
            .putInt(KEY_HEIGHT, resolution.height)
            .apply()
    }

    private companion object {
        const val NAME = "capture_preferences"
        const val KEY_WIDTH = "recording_resolution_width"
        const val KEY_HEIGHT = "recording_resolution_height"
    }
}
