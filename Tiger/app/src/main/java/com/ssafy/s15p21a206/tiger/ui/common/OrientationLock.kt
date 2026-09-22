package com.ssafy.s15p21a206.tiger.ui.common

import android.content.pm.ActivityInfo
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext

/**
 * 수집 화면이 보이는 동안 한쪽 가로로 고정하고, 벗어나면 원래 설정으로 되돌린다.
 *
 * Camera 파이프라인이 가로 기준이고 ARCore에 알리는 표시 회전도 고정값이라, 수집 중에 방향이
 * 바뀌면 프리뷰가 돌아간다.
 */
@Composable
@Suppress("FunctionName")
internal fun LockLandscapeWhileVisible() {
    val activity = LocalContext.current.findActivity() ?: return
    DisposableEffect(activity) {
        val previous = activity.requestedOrientation
        activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        onDispose { activity.requestedOrientation = previous }
    }
}

/**
 * 전체화면 재생의 방향 정책을 반영한다.
 *
 * 앱은 manifest에서 세로로 묶여 있으므로 기기를 눕혀도 화면이 돌지 않는다. 사용자가 회전 버튼으로
 * 가로 고정을 켤 때만 가로로 묶고, 끄면 진입 시점 설정으로 돌아간다. 화면을 벗어날 때도 같다.
 */
@Composable
@Suppress("FunctionName")
internal fun LockLandscapeWhilePlaying(landscapeLocked: Boolean) {
    val activity = LocalContext.current.findActivity() ?: return
    val entryOrientation = remember(activity) { activity.requestedOrientation }
    DisposableEffect(activity, entryOrientation) {
        onDispose { activity.requestedOrientation = entryOrientation }
    }
    LaunchedEffect(activity, landscapeLocked, entryOrientation) {
        activity.requestedOrientation =
            if (landscapeLocked) {
                ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            } else {
                entryOrientation
            }
    }
}
