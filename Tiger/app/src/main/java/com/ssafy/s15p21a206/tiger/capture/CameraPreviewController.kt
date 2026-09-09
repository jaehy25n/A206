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

    fun prepare(surface: Surface) {
        if (cameraDevice != null || session != null) return
        check(ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            "Camera permission is required for preview"
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
        cameraManager.openCamera(
            cameraId,
            object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    cameraDevice = device
                    val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply { addTarget(surface) }
                    device.createCaptureSession(
                        listOf(surface),
                        object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(configured: CameraCaptureSession) {
                                session = configured
                                configured.setRepeatingRequest(request.build(), null, handler)
                            }

                            override fun onConfigureFailed(configured: CameraCaptureSession) {
                                onFailure("Camera preview configuration failed")
                                release()
                            }
                        },
                        handler,
                    )
                }

                override fun onDisconnected(device: CameraDevice) {
                    onFailure("Camera preview was disconnected")
                    release()
                }

                override fun onError(
                    device: CameraDevice,
                    error: Int,
                ) {
                    onFailure("Camera preview error: $error")
                    release()
                }
            },
            handler,
        )
    }

    fun release() {
        session?.close()
        session = null
        cameraDevice?.close()
        cameraDevice = null
        thread?.quitSafely()
        thread = null
    }
}
