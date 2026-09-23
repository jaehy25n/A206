package com.ssafy.s15p21a206.tiger.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Surface
import androidx.core.content.ContextCompat
import java.util.concurrent.Executor

class CameraPreviewController(
    context: Context,
    private val onFailure: (String) -> Unit,
) {
    private val appContext = context.applicationContext
    private val cameraManager = appContext.getSystemService(CameraManager::class.java)
    private var thread: HandlerThread? = null
    private var cameraDevice: CameraDevice? = null
    private var session: CameraCaptureSession? = null

    /** 지금 그리고 있는 Surface와 그 콜백을 나르는 핸들러. 설정을 다시 걸 때 필요하다. */
    private var activeSurface: Surface? = null
    private var handler: Handler? = null

    /** 프리뷰에 걸어 둔 촬영 조건. null이면 기기 자동이다. */
    @Volatile private var manual: ManualCameraConfig? = null

    /**
     * AWB AUTO가 지금 수렴시킨 화이트 밸런스.
     *
     * 매 프레임 갱신하되 화면으로 밀지 않는다. 사용자가 "WB 고정"을 누른 순간의 값만 뜻이 있고,
     * 프레임마다 상태를 올리면 수집 화면이 초당 서른 번 다시 그려진다.
     */
    @Volatile var convergedWhiteBalance: FixedWhiteBalance? = null
        private set

    // 열기는 비동기라 release 직후 다시 prepare하면 앞선 열기의 콜백이 뒤늦게 도착한다.
    // 그 콜백이 이미 닫힌 device를 건드리지 않도록 세대 번호로 구분한다.
    @Volatile private var generation = 0

    /**
     * 프리뷰가 쓸 촬영 조건을 바꾼다.
     *
     * 사용자가 슬라이더를 움직이는 동안 계속 불린다. 프리뷰가 아직 열리지 않았으면 값만 들어 두고,
     * 다음 [prepare]가 그 값으로 연다. 초점을 화면으로 보고 고르는 것이 이 기능의 전부이므로,
     * 값이 바뀌면 곧바로 반복 요청을 다시 건다.
     */
    fun apply(config: ManualCameraConfig?) {
        manual = config
        val device = cameraDevice ?: return
        val active = session ?: return
        val surface = activeSurface ?: return
        val target = handler ?: return
        runCatching { active.setRepeatingRequest(buildRequest(device, surface, config), previewCallback, target) }
            .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not apply the manual camera settings to the preview", it) }
    }

    private fun buildRequest(
        device: CameraDevice,
        surface: Surface,
        config: ManualCameraConfig?,
    ) = device
        .createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
        .apply {
            addTarget(surface)
            applyManualCamera(config)
        }.build()

    /** 수렴한 화이트 밸런스를 주워 둔다. 이미 고정했으면 읽을 것이 없다. */
    private val previewCallback =
        object : CameraCaptureSession.CaptureCallback() {
            override fun onCaptureCompleted(
                cameraSession: CameraCaptureSession,
                request: CaptureRequest,
                result: TotalCaptureResult,
            ) {
                if (manual?.whiteBalance != null) return
                result.readConvergedWhiteBalance()?.let { convergedWhiteBalance = it }
            }
        }

    fun prepare(surface: Surface) {
        if (cameraDevice != null || session != null) return
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            onFailure("Camera permission is required for preview")
            return
        }
        val cameraId =
            cameraManager.cameraIdList.firstOrNull { id ->
                cameraManager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK
            } ?: run {
                onFailure("Rear camera is unavailable")
                return
            }
        val previewThread = HandlerThread("TigerPreview")
        thread = previewThread
        previewThread.start()
        val handler = Handler(previewThread.looper)
        this.handler = handler
        activeSurface = surface
        val token = ++generation
        cameraManager.openCamera(
            cameraId,
            object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    if (token != generation) {
                        device.close()
                        return
                    }
                    cameraDevice = device
                    // 프리뷰에 걸어 둔 조건 그대로 연다. 세션을 다시 여는 경로에서도 값이 유지된다.
                    val request = buildRequest(device, surface, manual)
                    runCatching {
                        val stateCallback =
                            object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(configured: CameraCaptureSession) {
                                    if (token != generation) {
                                        runCatching { configured.close() }
                                        return
                                    }
                                    session = configured
                                    // 요청 직전에 device가 닫히는 경합이 남아 있어, 실패를 프로세스 종료로 키우지 않는다.
                                    runCatching { configured.setRepeatingRequest(request, previewCallback, handler) }
                                        .onFailure {
                                            onFailure("Camera preview could not be started")
                                            release()
                                        }
                                }

                                override fun onConfigureFailed(configured: CameraCaptureSession) {
                                    if (token != generation) return
                                    onFailure("Camera preview configuration failed")
                                    release()
                                }
                            }
                        device.createCaptureSession(
                            SessionConfiguration(
                                SessionConfiguration.SESSION_REGULAR,
                                listOf(OutputConfiguration(surface)),
                                Executor(handler::post),
                                stateCallback,
                            ),
                        )
                    }.onFailure {
                        onFailure("Camera preview could not be prepared")
                        release()
                    }
                }

                override fun onDisconnected(device: CameraDevice) {
                    device.close()
                    if (token != generation) return
                    onFailure("Camera preview was disconnected")
                    release()
                }

                override fun onError(
                    device: CameraDevice,
                    error: Int,
                ) {
                    device.close()
                    if (token != generation) return
                    onFailure("Camera preview error: $error")
                    release()
                }
            },
            handler,
        )
    }

    fun release() {
        // 진행 중인 열기의 콜백을 무효로 만든다.
        generation++
        runCatching { session?.close() }
        session = null
        runCatching { cameraDevice?.close() }
        cameraDevice = null
        thread?.quitSafely()
        thread = null
        activeSurface = null
        handler = null
        // 고른 촬영 조건([manual])은 남긴다. 세션만 닫혔을 뿐 사용자가 맞춘 값은 그대로다.
        // 수렴값은 세션마다 다시 잡히므로 비운다.
        convergedWhiteBalance = null
    }
}
