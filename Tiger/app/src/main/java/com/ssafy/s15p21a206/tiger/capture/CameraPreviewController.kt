package com.ssafy.s15p21a206.tiger.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.os.Handler
import android.os.HandlerThread
import android.view.Surface
import androidx.core.content.ContextCompat

class CameraPreviewController(
    context: Context,
    private val onFailure: (String) -> Unit,
) {
    private val appContext = context.applicationContext
    private val cameraManager = appContext.getSystemService(CameraManager::class.java)
    private var thread: HandlerThread? = null
    private var cameraDevice: CameraDevice? = null
    private var session: CameraCaptureSession? = null

    // 열기는 비동기라 release 직후 다시 prepare하면 앞선 열기의 콜백이 뒤늦게 도착한다.
    // 그 콜백이 이미 닫힌 device를 건드리지 않도록 세대 번호로 구분한다.
    @Volatile private var generation = 0

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
                    val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply { addTarget(surface) }
                    runCatching {
                        device.createCaptureSession(
                            listOf(surface),
                            object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(configured: CameraCaptureSession) {
                                    if (token != generation) {
                                        runCatching { configured.close() }
                                        return
                                    }
                                    session = configured
                                    // 요청 직전에 device가 닫히는 경합이 남아 있어, 실패를 프로세스 종료로 키우지 않는다.
                                    runCatching { configured.setRepeatingRequest(request.build(), null, handler) }
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
                            },
                            handler,
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
    }
}
