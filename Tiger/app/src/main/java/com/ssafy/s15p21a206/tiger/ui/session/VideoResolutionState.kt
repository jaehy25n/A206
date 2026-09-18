package com.ssafy.s15p21a206.tiger.ui.session

import android.media.MediaMetadataRetriever
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** 수집 영상의 해상도를 읽는 과정과 결과다. 읽기가 실패해도 상세 화면의 나머지는 그대로 보여야 한다. */
internal sealed interface VideoResolutionState {
    data object Loading : VideoResolutionState

    data class Available(
        val width: Int,
        val height: Int,
    ) : VideoResolutionState

    data object Unavailable : VideoResolutionState
}

/**
 * 수집분의 영상 해상도를 읽는다.
 *
 * 값은 `metadata.json`이 아니라 `main_rgb.mp4`에서 직접 읽는다. Room에 컬럼을 두지 않아도
 * 과거 수집분까지 실제 값이 나온다. 파일 I/O이므로 composition이 아니라 IO dispatcher에서 읽고,
 * 읽는 동안에는 [VideoResolutionState.Loading]을 돌려준다.
 */
@Composable
internal fun rememberVideoResolution(bundlePath: String): VideoResolutionState {
    var state by remember(bundlePath) { mutableStateOf<VideoResolutionState>(VideoResolutionState.Loading) }
    LaunchedEffect(bundlePath) {
        state = withContext(Dispatchers.IO) { readVideoResolution(File(bundlePath, SessionBundle.MAIN_VIDEO_FILE)) }
    }
    return state
}

private fun readVideoResolution(videoFile: File): VideoResolutionState {
    if (!videoFile.isFile || videoFile.length() == 0L) return VideoResolutionState.Unavailable
    val retriever = MediaMetadataRetriever()
    return try {
        retriever.setDataSource(videoFile.absolutePath)
        displayResolution(
            width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull(),
            height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull(),
            rotationDegrees = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)?.toIntOrNull(),
        )
        // 손상된 파일과 지원하지 않는 컨테이너 모두 RuntimeException으로 나온다. 해상도 한 줄
        // 때문에 상세 화면 전체가 무너지면 안 되므로 여기서 멈춘다.
    } catch (_: RuntimeException) {
        VideoResolutionState.Unavailable
    } finally {
        runCatching { retriever.release() }
    }
}

/**
 * 재생기가 보여 주는 크기로 맞춘다.
 *
 * `MediaMetadataRetriever`는 회전을 반영하지 않은 저장 크기를 돌려준다. 재생기는 회전 metadata를
 * 적용해 그리므로, 90도와 270도에서는 가로세로를 바꿔야 화면에 보이는 것과 같은 값이 된다.
 * `video_rotation_degrees`가 90인 기존 수집분이 세로로 나오는 것은 이 때문이며, 회전 없이
 * 저장되는 이후 수집분은 읽은 크기가 그대로 쓰인다.
 */
internal fun displayResolution(
    width: Int?,
    height: Int?,
    rotationDegrees: Int?,
): VideoResolutionState {
    if (width == null || height == null || width <= 0 || height <= 0) return VideoResolutionState.Unavailable
    val normalized = (((rotationDegrees ?: 0) % 360) + 360) % 360
    return if (normalized == 90 || normalized == 270) {
        VideoResolutionState.Available(width = height, height = width)
    } else {
        VideoResolutionState.Available(width = width, height = height)
    }
}
