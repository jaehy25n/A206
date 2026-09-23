package com.ssafy.s15p21a206.tiger.capture

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.util.Log
import com.google.ar.core.Session
import java.util.EnumSet

/**
 * 수동 설정의 범위를 정할 카메라를 찾고 그 능력을 읽는다.
 *
 * 기준이 되는 카메라는 프리뷰가 여는 것이 아니라 **ARCore가 녹화에 쓰는 것**이어야 한다. 논리
 * 카메라가 여럿인 기기에서는 ISO·노출 범위가 카메라마다 다르고, 프리뷰 카메라의 범위로 고른 값이
 * 녹화 카메라에서는 범위 밖이면 조용히 다른 값으로 찍힌다. 그 어긋남은 영상만 봐서는 보이지 않는다.
 *
 * ARCore에게 물으려면 Session을 한 번 만들어야 한다. 카메라를 열지는 않으므로 프리뷰와 겹치지
 * 않지만 수백 ms가 걸리므로 배경 스레드에서 부른다. 실패하면 후면 카메라로 물러난다. 기능 하나
 * 때문에 수집 화면이 열리지 않게 하지는 않는다.
 */
class ManualCameraProfile(
    context: Context,
    private val cameraManager: CameraManager,
) {
    private val appContext = context.applicationContext

    @Volatile private var cached: ManualCameraCapabilities? = null

    /** 한 번 읽으면 기억한다. 읽을 카메라를 찾지 못하면 null이다. */
    fun read(): ManualCameraCapabilities? {
        cached?.let { return it }
        val cameraId = recordingCameraId() ?: return null
        return runCatching { cameraManager.readManualCameraCapabilities(cameraId) }
            .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not read the manual camera capabilities of $cameraId", it) }
            .getOrNull()
            ?.also {
                cached = it
                Log.i(CAPTURE_LOG_TAG, "Manual camera capabilities: $it")
            }
    }

    /**
     * ARCore가 녹화에 쓸 카메라의 id. 물어보지 못하면 첫 후면 카메라로 물러난다.
     *
     * 물러난 사실을 로그에 남긴다. 두 값이 다른 기기에서 범위가 어긋난 원인을 나중에 찾으려면
     * 어느 쪽을 읽었는지 알아야 한다.
     */
    private fun recordingCameraId(): String? {
        val fromArCore =
            runCatching {
                val session = Session(appContext, EnumSet.of(Session.Feature.SHARED_CAMERA))
                try {
                    session.cameraConfig.cameraId
                } finally {
                    session.close()
                }
            }.onFailure { Log.w(CAPTURE_LOG_TAG, "Could not ask ARCore which camera it records with", it) }
                .getOrNull()
        if (fromArCore != null) return fromArCore
        val fallback = firstBackCameraId()
        Log.w(CAPTURE_LOG_TAG, "Falling back to the first rear camera ($fallback) for manual camera ranges")
        return fallback
    }

    private fun firstBackCameraId(): String? =
        runCatching {
            cameraManager.cameraIdList.firstOrNull { id ->
                cameraManager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK
            }
        }.getOrNull()
}
