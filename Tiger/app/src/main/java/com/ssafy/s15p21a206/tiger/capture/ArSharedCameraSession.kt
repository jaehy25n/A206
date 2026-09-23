package com.ssafy.s15p21a206.tiger.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.ar.core.Session
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/**
 * ARCore와 카메라를 함께 쓰는 capture session의 수명을 든다.
 *
 * 카메라 열기는 비동기 콜백으로 진행되지만 이 클래스는 [open]이 돌아온 시점에 스트림이 흐르고
 * 있음을 보장한다. 호출부가 열림을 기다리는 코드를 따로 갖지 않게 하려는 것이다.
 *
 * 닫기는 [closeSession]과 [closeThread] 둘로 나뉜다. 사이에 ARCore Session을 닫아야 하기 때문이며,
 * 그 이유는 각 함수의 설명에 적었다.
 */
class ArSharedCameraSession(
    context: Context,
    private val onFrameTimestamp: (Long) -> Unit,
) {
    private val appContext = context.applicationContext
    private val cameraManager = appContext.getSystemService(CameraManager::class.java)
    private var thread: HandlerThread? = null
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null

    /** capture session이 완전히 닫혔음을 알린다. ARCore Session을 닫기 전에 기다린다. */
    @Volatile private var closedLatch: CountDownLatch? = null

    /**
     * 카메라를 열어 recorder에 프레임을 흘려보낸다.
     *
     * [onStreaming]은 스트림이 실제로 돌기 시작한 시점에 카메라 스레드에서 한 번 불린다. 여기서
     * 난 예외는 [open]이 그대로 올린다. 즉 호출부는 열기 실패와 시작 실패를 같은 자리에서 받는다.
     */
    fun open(
        arSession: Session,
        recorder: MediaRecorder,
        onStreaming: () -> Unit,
    ) {
        check(ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            "Camera permission is required for ARCore capture"
        }
        val sharedCamera = arSession.sharedCamera
        val cameraId = arSession.cameraConfig.cameraId
        val captureSessionClosed = CountDownLatch(1).also { closedLatch = it }
        val handler =
            Handler(
                HandlerThread("TigerCamera")
                    .also {
                        thread = it
                        it.start()
                    }.looper,
            )
        val ready = CountDownLatch(1)
        var failure: Throwable? = null
        val captureCallback =
            object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureCompleted(
                    cameraSession: CameraCaptureSession,
                    request: CaptureRequest,
                    result: TotalCaptureResult,
                ) {
                    val timestampNs = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
                    onFrameTimestamp(timestampNs)
                }
            }
        val deviceCallback =
            object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    device = camera
                    try {
                        // 앱이 소유한 출력을 먼저 등록해야 ARCore가 그에 맞춰 자신의 surface 구성을 정한다.
                        // 프리뷰는 여기에 넣지 않는다. 대상 기기가 ARCore 2개 + recorder + preview의 4 stream
                        // 조합을 거부하므로, 프리뷰는 pose 스레드가 ARCore Camera 텍스처를 그려서 채운다.
                        sharedCamera.setAppSurfaces(cameraId, listOf(recorder.surface))
                        val surfaces = sharedCamera.arCoreSurfaces.toMutableList().apply { add(recorder.surface) }
                        val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply { surfaces.forEach(::addTarget) }
                        val stateCallback =
                            sharedCamera.createARSessionStateCallback(
                                object : CameraCaptureSession.StateCallback() {
                                    override fun onConfigured(configured: CameraCaptureSession) {
                                        session = configured
                                        configured.setRepeatingRequest(request.build(), captureCallback, handler)
                                    }

                                    override fun onActive(activeSession: CameraCaptureSession) {
                                        try {
                                            arSession.resume()
                                            sharedCamera.setCaptureCallback(captureCallback, handler)
                                            onStreaming()
                                        } catch (error: Exception) {
                                            failure = error
                                        } finally {
                                            ready.countDown()
                                        }
                                    }

                                    override fun onConfigureFailed(failedSession: CameraCaptureSession) {
                                        failure = IllegalStateException("ARCore shared camera session configuration failed")
                                        ready.countDown()
                                    }

                                    override fun onClosed(closedSession: CameraCaptureSession) {
                                        // ARCore가 이 콜백 안에서 native Session을 건드리므로,
                                        // 여기까지 끝난 뒤에야 ARCore Session을 닫을 수 있다.
                                        captureSessionClosed.countDown()
                                    }
                                },
                                handler,
                            )
                        camera.createCaptureSession(
                            SessionConfiguration(
                                SessionConfiguration.SESSION_REGULAR,
                                surfaces.map(::OutputConfiguration),
                                Executor(handler::post),
                                stateCallback,
                            ),
                        )
                    } catch (error: Exception) {
                        failure = error
                        ready.countDown()
                    }
                }

                override fun onDisconnected(camera: CameraDevice) {
                    camera.close()
                    failure =
                        IllegalStateException("ARCore camera was disconnected")
                    ready.countDown()
                }

                override fun onError(
                    camera: CameraDevice,
                    error: Int,
                ) {
                    camera.close()
                    failure =
                        IllegalStateException("ARCore camera error: $error")
                    ready.countDown()
                }
            }
        cameraManager.openCamera(cameraId, sharedCamera.createARDeviceStateCallback(deviceCallback, handler), handler)
        check(ready.await(OPEN_TIMEOUT_SECONDS, TimeUnit.SECONDS)) { "Timed out starting ARCore shared camera" }
        failure?.let { throw it }
    }

    /** 프레임 공급을 끊는다. 이미 진행 중인 프레임은 계속 인코딩된다. */
    fun stopRepeating() {
        runCatching { session?.stopRepeating() }
            .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not stop the repeating request", it) }
    }

    /**
     * capture session과 camera device를 닫는다.
     *
     * ARCore Session보다 먼저 닫아야 한다. capture session이 닫힐 때 ARCore가
     * `onCaptureSessionClosed`에서 native Session을 건드리는데, Session이 먼저 닫혀 있으면
     * 콜백 스레드에서 잡히지 않는 예외가 나 프로세스가 죽는다.
     */
    fun closeSession() {
        runCatching { session?.close() }
        session = null
        // close는 비동기다. onClosed가 끝난 것을 확인한 뒤 돌아간다.
        val closed = closedLatch?.await(CLOSE_TIMEOUT_SECONDS, TimeUnit.SECONDS) ?: true
        if (!closed) Log.w(CAPTURE_LOG_TAG, "Capture session did not report closing in time")
        closedLatch = null
        runCatching { device?.close() }
        device = null
    }

    /** 콜백을 나르던 핸들러 스레드를 정리한다. 콜백이 모두 전달된 뒤에 부른다. */
    fun closeThread() {
        thread?.quitSafely()
        thread = null
    }

    private companion object {
        /** 카메라가 열려 스트림이 돌기 시작할 때까지 기다리는 한계. */
        const val OPEN_TIMEOUT_SECONDS = 8L

        /** capture session 닫힘을 기다리는 한계. 넘기면 기다림을 포기하고 나머지 정리를 이어간다. */
        const val CLOSE_TIMEOUT_SECONDS = 2L
    }
}
