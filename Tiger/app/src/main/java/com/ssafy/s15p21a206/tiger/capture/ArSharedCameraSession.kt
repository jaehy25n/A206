package com.ssafy.s15p21a206.tiger.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
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
import android.os.SystemClock
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.ar.core.Session
import com.google.ar.core.SharedCamera
import com.ssafy.s15p21a206.tiger.episode.ActualCaptureSettings
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import kotlin.time.Duration.Companion.seconds

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

    /** ARCore가 가져간 repeating request를 되받는 감시자. 수동 설정을 쓸 때만 선다. */
    @Volatile private var manualGuard: ManualRequestGuard? = null

    /**
     * 센서가 실제로 사용한 값. 프레임이 한 장도 오기 전과 정리 후에는 null이다.
     *
     * 카메라 스레드가 매 프레임 갱신하고 마감이 읽는다.
     */
    @Volatile var appliedSettings: ActualCaptureSettings? = null
        private set

    /**
     * 카메라를 열어 recorder에 프레임을 흘려보낸다. 스트림이 돌기 시작하면 돌아온다.
     *
     * [manual]이 있으면 녹화 요청에 수동 값을 걸고, ARCore가 그것을 덮으면 되받는다. null이면
     * template의 자동 설정으로 찍는다.
     *
     * [onStreaming]은 스트림이 실제로 돌기 시작한 시점에 카메라 스레드에서 한 번 불린다. 여기서
     * 난 예외는 [open]이 그대로 올린다. 즉 호출부는 열기 실패와 시작 실패를 같은 자리에서 받는다.
     *
     * 기다리는 동안 스레드를 붙들지 않는다. 카메라가 열리는 데 수 초가 걸려도 호출한 쪽의
     * 디스패처는 다른 일을 한다.
     */
    suspend fun open(
        arSession: Session,
        recorder: MediaRecorder,
        manual: ManualCameraConfig?,
        onStreaming: () -> Unit,
    ) {
        check(ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            "Camera permission is required for ARCore capture"
        }
        appliedSettings = null
        val request = CameraOpenRequest(arSession, recorder, manual, onStreaming)
        check(usesRealtimeTimestamps(request.cameraId)) { "Camera timestamp source is not REALTIME" }
        closedLatch = CountDownLatch(1)
        val handler = startCameraThread()
        val streaming = CompletableDeferred<Unit>()
        cameraManager.openCamera(
            request.cameraId,
            request.sharedCamera.createARDeviceStateCallback(deviceCallback(request, handler, streaming), handler),
            handler,
        )
        withTimeoutOrNull(OPEN_TIMEOUT) { streaming.await() }
            ?: error("Timed out starting ARCore shared camera")
    }

    /** 프레임 공급을 끊는다. 이미 진행 중인 프레임은 계속 인코딩된다. */
    fun stopRepeating() {
        // 감시자를 먼저 내린다. 남겨 두면 정지 중에 반복 요청을 다시 걸어 프레임 공급이 되살아난다.
        manualGuard = null
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

    /**
     * 카메라 프레임 시각이 IMU와 같은 시계에서 오는지 본다.
     *
     * `REALTIME`이 아니면 카메라 시각이 `SystemClock.elapsedRealtimeNanos()`와 다른 시계를 쓴다.
     * 그러면 `main_frame_timestamps.csv`와 IMU CSV를 같은 시간축에서 비교할 수 없어 수집물 전체가
     * 쓸모없어진다. 수집을 시작한 뒤에는 되돌릴 수 없으므로 열기 전에 막는다.
     */
    private fun usesRealtimeTimestamps(cameraId: String): Boolean =
        isRealtimeTimestampSource(
            cameraManager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE),
        )

    /** 콜백을 받을 카메라 스레드를 띄우고 그 핸들러를 돌려준다. */
    private fun startCameraThread(): Handler =
        Handler(
            HandlerThread("TigerCamera")
                .also {
                    thread = it
                    it.start()
                }.looper,
        )

    private fun deviceCallback(
        request: CameraOpenRequest,
        handler: Handler,
        streaming: CompletableDeferred<Unit>,
    ) = object : CameraDevice.StateCallback() {
        override fun onOpened(camera: CameraDevice) {
            device = camera
            try {
                configure(camera, request, handler, streaming)
            } catch (error: Exception) {
                streaming.completeExceptionally(error)
            }
        }

        override fun onDisconnected(camera: CameraDevice) {
            camera.close()
            streaming.completeExceptionally(IllegalStateException("ARCore camera was disconnected"))
        }

        override fun onError(
            camera: CameraDevice,
            error: Int,
        ) {
            camera.close()
            streaming.completeExceptionally(IllegalStateException("ARCore camera error: $error"))
        }
    }

    /** 출력 surface를 정하고 capture session을 만든다. */
    private fun configure(
        camera: CameraDevice,
        request: CameraOpenRequest,
        handler: Handler,
        streaming: CompletableDeferred<Unit>,
    ) {
        // 앱이 소유한 출력을 먼저 등록해야 ARCore가 그에 맞춰 자신의 surface 구성을 정한다.
        // 프리뷰는 여기에 넣지 않는다. 대상 기기가 ARCore 2개 + recorder + preview의 4 stream
        // 조합을 거부하므로, 프리뷰는 pose 스레드가 ARCore Camera 텍스처를 그려서 채운다.
        request.sharedCamera.setAppSurfaces(request.cameraId, listOf(request.recorder.surface))
        val surfaces =
            request.sharedCamera.arCoreSurfaces
                .toMutableList()
                .apply { add(request.recorder.surface) }
        val repeating =
            camera
                .createCaptureRequest(CameraDevice.TEMPLATE_RECORD)
                .apply {
                    surfaces.forEach(::addTarget)
                    applyManualCamera(request.manual)
                }.build()
        camera.createCaptureSession(
            SessionConfiguration(
                SessionConfiguration.SESSION_REGULAR,
                surfaces.map(::OutputConfiguration),
                Executor(handler::post),
                request.sharedCamera.createARSessionStateCallback(sessionCallback(repeating, request, handler, streaming), handler),
            ),
        )
    }

    /** capture session의 상태 콜백. [repeating]은 구성이 끝난 뒤 반복 요청으로 건다. */
    private fun sessionCallback(
        repeating: CaptureRequest,
        request: CameraOpenRequest,
        handler: Handler,
        streaming: CompletableDeferred<Unit>,
    ) = object : CameraCaptureSession.StateCallback() {
        override fun onConfigured(configured: CameraCaptureSession) {
            session = configured
            configured.setRepeatingRequest(repeating, frameCallback, handler)
        }

        override fun onActive(activeSession: CameraCaptureSession) {
            try {
                request.arSession.resume()
                request.sharedCamera.setCaptureCallback(frameCallback, handler)
                // ARCore는 resume에서 repeating request를 제 것으로 갈아 끼운다. 여기서 감시자를
                // 세워 두면 다음 프레임에서 그것을 알아채고 우리 요청을 되돌린다. 근거는
                // [ManualRequestGuard]에 적었다.
                manualGuard = request.manual?.let { ManualRequestGuard(it, repeating, handler) }
                request.onStreaming()
                streaming.complete(Unit)
            } catch (error: Exception) {
                streaming.completeExceptionally(error)
            }
        }

        override fun onConfigureFailed(failedSession: CameraCaptureSession) {
            streaming.completeExceptionally(IllegalStateException("ARCore shared camera session configuration failed"))
        }

        override fun onClosed(closedSession: CameraCaptureSession) {
            // ARCore가 이 콜백 안에서 native Session을 건드리므로,
            // 여기까지 끝난 뒤에야 ARCore Session을 닫을 수 있다.
            closedLatch?.countDown()
        }
    }

    /**
     * 프레임 타임스탬프를 받는 콜백. 상태가 없어 한 인스턴스가 모든 열기를 감당한다.
     *
     * 반복 요청과 ARCore 양쪽에 같은 인스턴스를 건다. 그래서 같은 프레임이 두 번 도착할 수 있고,
     * 거르는 것은 받는 쪽(`FrameTimestampWriter`)의 몫이다.
     */
    private val frameCallback =
        object : CameraCaptureSession.CaptureCallback() {
            override fun onCaptureCompleted(
                cameraSession: CameraCaptureSession,
                request: CaptureRequest,
                result: TotalCaptureResult,
            ) {
                val timestampNs = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
                onFrameTimestamp(timestampNs)
                manualGuard?.observe(cameraSession, request, result)
            }
        }

    /**
     * ARCore가 가져간 repeating request를 되받고, 실제로 쓰인 값을 읽어 둔다.
     *
     * ARCore는 `Session.resume()`에서 repeating request를 제 것으로 바꿔 끼운다. 그래서 resume 전에
     * 건 수동 값은 한 프레임만 살아남고, 그다음부터 노출과 화이트 밸런스가 자동으로 돌아간다.
     * 기기에서 확인한 사실이며, 되받아 걸면 그 뒤로는 ARCore가 다시 가져가지 않는다.
     *
     * SharedCamera 문서는 ARCore가 도는 동안 `setRepeatingRequest`를 부르지 말라고 한다. 그러나
     * ARCore 공식 샘플도 초점 모드를 바꿀 때 같은 일을 하고, 1분 녹화에서 프레임 공급도 pose
     * 수급도 끊기지 않았다. 이 한 번 없이는 기능 자체가 성립하지 않는다.
     *
     * 되받기는 횟수와 간격으로 묶는다. ARCore와 매 프레임 요청을 주고받는 상태가 되면 그것대로
     * 망가진 것이고, 그때는 조용히 싸우기보다 로그를 남기고 멈추는 편이 낫다.
     */
    private inner class ManualRequestGuard(
        private val config: ManualCameraConfig,
        private val repeating: CaptureRequest,
        private val handler: Handler,
    ) {
        private var attempts = 0
        private var lastAttemptAtMs = 0L
        private var settledLogged = false

        /** 카메라 스레드에서 매 프레임 불린다. 이 클래스의 상태는 그 스레드만 만진다. */
        fun observe(
            active: CameraCaptureSession,
            observed: CaptureRequest,
            result: TotalCaptureResult,
        ) {
            if (observed.carriesManualCamera()) {
                val applied = result.readAppliedCameraSettings()
                appliedSettings = applied
                if (!settledLogged) {
                    settledLogged = true
                    logCameraSettingMismatch(config, applied)
                }
                return
            }
            val now = SystemClock.elapsedRealtime()
            if (attempts >= MAX_REAPPLY_ATTEMPTS || now - lastAttemptAtMs < REAPPLY_INTERVAL_MS) return
            attempts++
            lastAttemptAtMs = now
            Log.i(CAPTURE_LOG_TAG, "ARCore replaced the repeating request; restoring manual settings (attempt $attempts)")
            runCatching { active.setRepeatingRequest(repeating, frameCallback, handler) }
                .onFailure { Log.w(CAPTURE_LOG_TAG, "Could not restore the manual repeating request", it) }
            if (attempts == MAX_REAPPLY_ATTEMPTS) {
                Log.w(CAPTURE_LOG_TAG, "Manual settings did not stick after $attempts attempts; leaving ARCore's request in place")
            }
        }
    }

    private companion object {
        /** 카메라가 열려 스트림이 돌기 시작할 때까지 기다리는 한계. */
        val OPEN_TIMEOUT = 8.seconds

        /** capture session 닫힘을 기다리는 한계. 넘기면 기다림을 포기하고 나머지 정리를 이어간다. */
        const val CLOSE_TIMEOUT_SECONDS = 2L

        /** 수동 요청을 되받는 최대 횟수. 기기에서는 한 번으로 끝났다. */
        const val MAX_REAPPLY_ATTEMPTS = 10

        /** 되받기 사이의 최소 간격. 요청이 반영되기까지 몇 프레임 걸리므로 그동안 다시 걸지 않는다. */
        const val REAPPLY_INTERVAL_MS = 300L
    }
}

/**
 * 한 번의 열기에 필요한 것들. 값만 들고 아무 일도 하지 않는다.
 *
 * 콜백 넷이 같은 것들을 나눠 쓰므로 하나로 묶어 넘긴다. ARCore Session에서 파생되는 둘은 여기서
 * 한 번만 읽는다. 콜백마다 다시 읽으면 매번 같은 것을 가리키는지를 우리가 따져야 한다.
 */
private class CameraOpenRequest(
    val arSession: Session,
    val recorder: MediaRecorder,
    /** Session 내내 고정할 촬영 조건. null이면 기기 자동에 맡긴다. */
    val manual: ManualCameraConfig?,
    val onStreaming: () -> Unit,
) {
    val sharedCamera: SharedCamera = arSession.sharedCamera
    val cameraId: String = arSession.cameraConfig.cameraId
}

/**
 * 카메라가 알린 timestamp source가 IMU와 같은 시계를 뜻하는지 본다.
 *
 * 값을 읽는 일과 갈라 둔 것은 규칙만 따로 검사하기 위해서다. `CameraCharacteristics`는 만들 수 없어
 * 읽는 쪽은 실기기로만 확인된다.
 *
 * 모르는 값(`null`)은 거부한다. 기기가 알려 주지 않으면 같은 시계라고 볼 근거가 없고, 확인할 수
 * 없으면 시작하지 않는 것이 요구사항이다.
 */
internal fun isRealtimeTimestampSource(source: Int?): Boolean = source == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
