package com.ssafy.s15p21a206.tiger.capture

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.MediaRecorder
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Surface
import androidx.core.content.ContextCompat
import com.google.ar.core.CameraConfigFilter
import com.google.ar.core.Session
import com.ssafy.s15p21a206.tiger.episode.CameraMetadata
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.RecordingInputValidator
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.util.EnumSet
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

class AndroidCaptureRuntime(
    context: Context,
    private val store: SessionBundleStore,
) : SensorEventListener {
    private val appContext = context.applicationContext
    private val sensorManager = appContext.getSystemService(SensorManager::class.java)
    private val cameraManager = appContext.getSystemService(CameraManager::class.java)
    private val sensorFiles = mutableMapOf<Int, File>()
    private var cameraThread: HandlerThread? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var mediaRecorder: MediaRecorder? = null
    private var arSession: Session? = null
    private var poseThread: Thread? = null

    /** capture session이 완전히 닫혔음을 알린다. ARCore Session을 닫기 전에 기다린다. */
    @Volatile private var captureSessionClosedLatch: CountDownLatch? = null

    private val trackingState = MutableStateFlow(TrackingSample(false, 0L))

    /**
     * 최신 ARCore Tracking 관측값. pose 수집 스레드가 갱신하고 수집 화면이 주기적으로 읽는다.
     *
     * 카메라 시각을 함께 실어 보내므로, 유실 구간의 기록용 시작 시각을 `arcore_poses.csv`와
     * 같은 값으로 맞출 수 있다.
     */
    val tracking: StateFlow<TrackingSample> = trackingState.asStateFlow()

    @Volatile private var poseCollectionRunning = false
    private var bundle: SessionBundle? = null
    private var frameTimestamps: FrameTimestampWriter? = null
    private var lastPoseTimestampNs = Long.MIN_VALUE

    /** 마지막 `TRACKING` 이후 처음 유실된 pose의 카메라 시각. 회복하면 비운다. */
    private var lossStartedAtNs: Long? = null

    @Volatile private var cameraMetadata: CameraMetadata? = null

    fun start(
        displayNumber: Int,
        resolution: RecordingResolution = RecordingInputValidator.DEFAULT_RESOLUTION,
        previewSurfaces: PreviewSurfaceProvider = PreviewSurfaceProvider { _, _ -> null },
    ): SessionBundle {
        check(bundle == null) { "Capture is already running" }
        val next = store.createStagingBundle(displayNumber)
        writeHeaders(next)
        try {
            val session = Session(appContext, EnumSet.of(Session.Feature.SHARED_CAMERA))
            applyRecordingResolution(session, resolution)
            val recorder =
                MediaRecorder().apply {
                    setVideoSource(MediaRecorder.VideoSource.SURFACE)
                    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                    setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                    setVideoFrameRate(30)
                    setVideoSize(session.cameraConfig.textureSize.width, session.cameraConfig.textureSize.height)
                    setOutputFile(next.mainVideo.absolutePath)
                    // 회전 정보를 남기지 않는다. 폰을 가로로 눕혀 촬영하므로 센서가 내보내는
                    // 가로 프레임이 곧 똑바로 선 장면이다. Intrinsic도 같은 기준으로 기록한다.
                    prepare()
                }
            arSession = session
            mediaRecorder = recorder
            bundle = next
            // 프리뷰도 녹화와 같은 가로 기준으로 그린다.
            val textureSize = session.cameraConfig.textureSize
            val previewSurface =
                runCatching { previewSurfaces.surfaceFor(textureSize.width, textureSize.height) }
                    .onFailure { Log.w(TAG, "Could not obtain a preview surface", it) }
                    .getOrNull()

            openSharedCamera(session, recorder, previewSurface)
            register(Sensor.TYPE_ACCELEROMETER)
            register(Sensor.TYPE_GYROSCOPE)
            register(Sensor.TYPE_ROTATION_VECTOR)
            return next
        } catch (error: Exception) {
            Log.e(TAG, "Could not start ARCore shared capture", error)
            releaseResources()
            // 마감되지 않은 bundle을 남기면 다음 start가 막힌다.
            bundle = null
            next.directory.deleteRecursively()
            throw error
        }
    }

    fun stop(): FinalizeResult {
        val active = requireNotNull(bundle) { "No active capture" }
        sensorManager.unregisterListener(this)
        closeFrameWindow()
        val stopError = runCatching { mediaRecorder?.stop() }.exceptionOrNull()
        val camera = cameraMetadata
        releaseResources()
        bundle = null
        if (stopError != null) return FinalizeResult.Failed(stopError.message ?: "Video recording could not be finalized")
        return SessionFinalizer(store).finalize(active, camera = camera)
    }

    /**
     * Camera 프레임 공급을 먼저 끊고 타임스탬프 기록 창을 닫는다.
     *
     * 공급이 계속되는 상태에서 창만 닫으면, `MediaRecorder.stop()`이 끝나기까지 인코딩된 프레임이
     * `main_frame_timestamps.csv`에 남지 않아 MP4 frame 수와 벌어진다. 공급을 먼저 끊으면 인코더와
     * CSV가 같은 마지막 프레임에서 끝난다.
     */
    private fun closeFrameWindow() {
        runCatching { captureSession?.stopRepeating() }
            .onFailure { Log.w(TAG, "Could not stop the repeating request", it) }
        // stopRepeating 시점에 이미 진행 중인 프레임은 계속 인코딩된다. 그 프레임의
        // onCaptureCompleted까지 받고 창을 닫아야 CSV가 MP4와 같은 프레임에서 끝난다.
        runCatching { Thread.sleep(FRAME_DRAIN_DELAY_MS) }
        frameTimestamps?.recording = false
    }

    fun interrupt() {
        sensorManager.unregisterListener(this)
        closeFrameWindow()
        runCatching { mediaRecorder?.stop() }
        releaseResources()
        bundle = null
    }

    override fun onSensorChanged(event: SensorEvent) {
        val target = sensorFiles[event.sensor.type] ?: return
        val values = event.values
        val row =
            when (event.sensor.type) {
                Sensor.TYPE_ROTATION_VECTOR -> "${event.timestamp},${values.getOrElse(
                    0,
                ) { 0f }},${values.getOrElse(
                    1,
                ) { 0f }},${values.getOrElse(2) { 0f }},${values.getOrElse(3) { 0f }},${values.getOrElse(4) { 0f }},${event.accuracy}"
                else -> "${event.timestamp},${values.getOrElse(
                    0,
                ) { 0f }},${values.getOrElse(1) { 0f }},${values.getOrElse(2) { 0f }},${event.accuracy}"
            }
        target.appendText("$row\n")
    }

    override fun onAccuracyChanged(
        sensor: Sensor?,
        accuracy: Int,
    ) = Unit

    fun appendEpisode(marker: EpisodeMarker) {
        val active = bundle ?: return
        active.episodes.appendText(
            listOf(
                marker.episodeId,
                marker.startTimestampNs.toString(),
                marker.endTimestampNs.orEmpty(),
                marker.task.csvField(),
                marker.objectName.csvField(),
                marker.outcome.name,
            ).joinToString(",") +
                "\n",
        )
    }

    private fun openSharedCamera(
        session: Session,
        recorder: MediaRecorder,
        previewSurface: Surface?,
    ) {
        check(ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            "Camera permission is required for ARCore capture"
        }
        val sharedCamera = session.sharedCamera
        val cameraId = session.cameraConfig.cameraId
        val captureSessionClosed = CountDownLatch(1).also { captureSessionClosedLatch = it }
        val handler =
            Handler(
                HandlerThread("TigerCamera")
                    .also {
                        cameraThread = it
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
                    frameTimestamps?.record(timestampNs)
                }
            }
        val deviceCallback =
            object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    cameraDevice = device
                    try {
                        // 앱이 소유한 출력을 먼저 등록해야 ARCore가 그에 맞춰 자신의 surface 구성을 정한다.
                        // 프리뷰는 여기에 넣지 않는다. 대상 기기가 ARCore 2개 + recorder + preview의 4 stream
                        // 조합을 거부하므로, 프리뷰는 pose 스레드가 ARCore Camera 텍스처를 그려서 채운다.
                        sharedCamera.setAppSurfaces(cameraId, listOf(recorder.surface))
                        val surfaces = sharedCamera.arCoreSurfaces.toMutableList().apply { add(recorder.surface) }
                        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply { surfaces.forEach(::addTarget) }
                        val stateCallback =
                            sharedCamera.createARSessionStateCallback(
                                object : CameraCaptureSession.StateCallback() {
                                    override fun onConfigured(configured: CameraCaptureSession) {
                                        captureSession = configured
                                        configured.setRepeatingRequest(request.build(), captureCallback, handler)
                                    }

                                    override fun onActive(activeSession: CameraCaptureSession) {
                                        try {
                                            session.resume()
                                            sharedCamera.setCaptureCallback(captureCallback, handler)
                                            recorder.start()
                                            // 인코더가 실제로 돌기 시작한 뒤부터 Camera timestamp를 남긴다.
                                            frameTimestamps?.recording = true
                                            startPoseCollection(session, previewSurface)
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
                        device.createCaptureSession(
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

                override fun onDisconnected(device: CameraDevice) {
                    device.close()
                    failure =
                        IllegalStateException("ARCore camera was disconnected")
                    ready.countDown()
                }

                override fun onError(
                    device: CameraDevice,
                    error: Int,
                ) {
                    device.close()
                    failure =
                        IllegalStateException("ARCore camera error: $error")
                    ready.countDown()
                }
            }
        cameraManager.openCamera(cameraId, sharedCamera.createARDeviceStateCallback(deviceCallback, handler), handler)
        check(ready.await(8, TimeUnit.SECONDS)) { "Timed out starting ARCore shared camera" }
        failure?.let { throw it }
    }

    private fun startPoseCollection(
        session: Session,
        previewSurface: Surface?,
    ) {
        poseCollectionRunning = true
        lossStartedAtNs = null
        lastPoseTimestampNs = Long.MIN_VALUE
        poseThread =
            Thread {
                val egl = CaptureEgl(previewSurface)
                try {
                    egl.makeCurrent()
                    val renderer = if (egl.hasWindow) CameraTextureRenderer() else null
                    val textureId = renderer?.createTexture() ?: IntArray(1).also { GLES20.glGenTextures(1, it, 0) }[0]
                    session.setCameraTextureName(textureId)
                    // 표시 회전을 Sensor 방향과 같게 준다. ARCore는 (Sensor 방향 - 표시 회전)만큼 이미지를
                    // 돌리므로, 두 값이 같으면 회전이 0이 되어 녹화본과 같은 방향의 프레임이 그려진다.
                    //
                    // 크기도 Camera 텍스처 그대로 가로로 준다. 녹화본과 같은 비율이라 ARCore가
                    // 잘라내지 않고, 프리뷰와 저장물의 화각이 일치한다.
                    val textureSize = session.cameraConfig.textureSize
                    if (renderer != null) {
                        session.setDisplayGeometry(SENSOR_DISPLAY_ROTATION, textureSize.width, textureSize.height)
                    }
                    while (poseCollectionRunning) {
                        // Tracking 유실·회복 구간에서 한 번 실패한다고 프리뷰와 pose 수집이 통째로
                        // 멈추면 안 된다. 실패를 남기고 다음 프레임으로 넘어간다.
                        val frame =
                            runCatching { session.update() }
                                .onFailure {
                                    Log.w(TAG, "Could not update the ARCore frame", it)
                                    Thread.sleep(FRAME_RETRY_DELAY_MS)
                                }.getOrNull() ?: continue
                        if (renderer != null) {
                            // 타임스탬프 중복으로 걸러지는 프레임도 화면에는 그려야 프리뷰가 끊기지 않는다.
                            runCatching {
                                renderer.draw(frame, textureId, textureSize.width, textureSize.height)
                                // swapBuffers는 예외 대신 false를 돌려주므로, 조용히 정지하지 않게 확인한다.
                                check(egl.swapBuffers()) { "eglSwapBuffers rejected the preview surface" }
                            }.onFailure { Log.w(TAG, "Could not draw the capture preview", it) }
                        }
                        val timestampNs = frame.androidCameraTimestamp
                        if (timestampNs == 0L || timestampNs == lastPoseTimestampNs) continue
                        lastPoseTimestampNs = timestampNs
                        val camera = frame.camera
                        val isTracking = camera.trackingState == com.google.ar.core.TrackingState.TRACKING
                        // 유실 구간에서는 첫 유실 pose 시각을 계속 실어 보낸다. 화면 ticker는 100 ms
                        // 주기로 읽으므로, 매 프레임 최신 시각을 덮어쓰면 그사이 진행한 pose 시각이
                        // 기록에 들어가 `end_timestamp_ns`가 첫 유실 + 0.5초보다 늦어진다.
                        lossStartedAtNs = if (isTracking) null else lossStartedAtNs ?: timestampNs
                        trackingState.value = TrackingSample(isTracking, lossStartedAtNs ?: timestampNs)
                        if (cameraMetadata ==
                            null
                        ) {
                            // 회전하지 않는다. 녹화본이 회전 전 가로 프레임 그대로이고,
                            // `arcore_poses.csv`의 Camera 좌표계도 같은 기준이다.
                            cameraMetadata = readCameraMetadata(session, camera)
                        }
                        val translation = camera.pose.translation
                        val rotation = camera.pose.rotationQuaternion
                        bundle?.arcorePoses?.appendText(
                            "$timestampNs,${translation[0]},${translation[1]},${translation[2]},${rotation[0]},${rotation[1]},${rotation[2]},${rotation[3]},${camera.trackingState.name},${camera.trackingFailureReason}\n",
                        )
                    }
                } catch (error: Throwable) {
                    // 여기서 끝나면 프리뷰와 pose 기록이 함께 멈춘다. 원인을 반드시 남긴다.
                    Log.e(TAG, "Pose collection stopped unexpectedly", error)
                    throw error
                } finally {
                    egl.close()
                }
            }.apply {
                name = "TigerArPose"
                start()
            }
    }

    /**
     * 고른 녹화 해상도를 가진 Camera config를 세션에 지정한다.
     *
     * 녹화·프리뷰·Intrinsic이 모두 `cameraConfig.textureSize`를 따르므로, 여기서 config를 바꾸면
     * 나머지가 자동으로 같은 해상도를 쓴다. 후보가 없으면 기본 config 그대로 수집을 이어간다.
     * 해상도 하나 때문에 수집 자체를 막지 않는다.
     */
    private fun applyRecordingResolution(
        session: Session,
        resolution: RecordingResolution,
    ) {
        val selected =
            runCatching {
                RecordingCameraConfigSelector.select(
                    candidates = session.getSupportedCameraConfigs(CameraConfigFilter(session)),
                    imageSizeOf = { RecordingResolution(it.imageSize.width, it.imageSize.height) },
                    textureSizeOf = { RecordingResolution(it.textureSize.width, it.textureSize.height) },
                    target = resolution,
                )
            }.onFailure { Log.w(TAG, "Could not read the supported camera configs", it) }.getOrNull()
        if (selected == null) {
            Log.w(TAG, "No camera config matches ${resolution.width}x${resolution.height}; keeping the default config")
            return
        }
        runCatching { session.cameraConfig = selected }
            .onFailure { Log.w(TAG, "Could not apply the selected camera config", it) }
    }

    /**
     * 첫 유효 프레임에서 촬영 Camera의 Intrinsic을 1회 확보한다.
     *
     * ARCore의 GPU 텍스처 스트림 기준 값이며, MediaRecorder 해상도를 같은 `cameraConfig.textureSize`로
     * 설정하므로 녹화 해상도와 대응이 보장된다. 실패하면 null을 돌려주고 수집은 그대로 이어간다.
     */
    private fun readCameraMetadata(
        session: Session,
        camera: com.google.ar.core.Camera,
    ): CameraMetadata? =
        runCatching {
            val intrinsics = camera.textureIntrinsics
            val focalLength = intrinsics.focalLength
            val principalPoint = intrinsics.principalPoint
            val dimensions = intrinsics.imageDimensions
            val optics = CameraMetadataReader(cameraManager).read(session.cameraConfig.cameraId)
            CameraMetadata(
                cameraId = session.cameraConfig.cameraId,
                imageWidth = dimensions[0],
                imageHeight = dimensions[1],
                fx = focalLength[0],
                fy = focalLength[1],
                cx = principalPoint[0],
                cy = principalPoint[1],
                focalLengthMm = optics.focalLengthMm,
                sensorWidthMm = optics.sensorWidthMm,
                sensorHeightMm = optics.sensorHeightMm,
                distortionCoefficients = optics.distortionCoefficients,
            )
        }.onFailure { Log.w(TAG, "Could not read camera metadata", it) }.getOrNull()

    private fun releaseResources() {
        poseCollectionRunning = false
        poseThread?.join(500)
        poseThread = null
        // ARCore Session은 반드시 마지막에 닫는다. capture session이 닫힐 때 ARCore가
        // onCaptureSessionClosed에서 native Session을 건드리는데, Session이 먼저 닫혀 있으면
        // 콜백 스레드에서 잡히지 않는 예외가 나 프로세스가 죽는다.
        runCatching { arSession?.pause() }
        runCatching { captureSession?.close() }
        captureSession = null
        // close는 비동기다. onClosed가 끝난 것을 확인한 뒤 Session을 닫는다.
        val closed = captureSessionClosedLatch?.await(CLOSE_TIMEOUT_SECONDS, TimeUnit.SECONDS) ?: true
        if (!closed) Log.w(TAG, "Capture session did not report closing in time")
        captureSessionClosedLatch = null
        runCatching { cameraDevice?.close() }
        cameraDevice = null
        runCatching { arSession?.close() }
        arSession = null
        mediaRecorder?.release()
        mediaRecorder = null
        // 콜백이 모두 전달된 뒤에 핸들러 스레드를 정리한다.
        cameraThread?.quitSafely()
        cameraThread = null
        frameTimestamps = null
        cameraMetadata = null
        sensorFiles.clear()
    }

    private fun register(type: Int) {
        sensorManager.getDefaultSensor(type)?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
    }

    private fun writeHeaders(bundle: SessionBundle) {
        frameTimestamps = FrameTimestampWriter(bundle.mainFrameTimestamps).also(FrameTimestampWriter::start)
        bundle.accelerometer.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.gyroscope.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.rotationVector.writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        bundle.arcorePoses.writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        bundle.episodes.writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
        sensorFiles[Sensor.TYPE_ACCELEROMETER] = bundle.accelerometer
        sensorFiles[Sensor.TYPE_GYROSCOPE] = bundle.gyroscope
        sensorFiles[Sensor.TYPE_ROTATION_VECTOR] = bundle.rotationVector
    }

    private fun Long?.orEmpty() = this?.toString().orEmpty()

    private fun String.csvField(): String = if (contains(',') || contains('"') || contains('\n')) "\"${replace("\"", "\"\"")}\"" else this

    private companion object {
        const val TAG = "TigerCapture"

        /**
         * ARCore에 알리는 표시 회전. Sensor 방향과 같은 값을 주면 (Sensor 방향 - 표시 회전)이 0이
         * 되어 이미지를 돌리지 않는다. 센서가 내보내는 가로 프레임이 그대로 그려져 녹화본과 방향이
         * 같고, 표시 기하의 비율도 텍스처와 같으므로 ARCore가 잘라내지 않는다.
         *
         * 돌리게 하면 세로 모양이 된 이미지를 가로 표시 기하에 맞추느라 크게 잘라내고 확대해,
         * 비율이 어긋나고 화질이 떨어진다. 수집 화면을 가로로 고정해 두므로 값이 바뀌지 않는다.
         */
        val SENSOR_DISPLAY_ROTATION = Surface.ROTATION_90

        /** capture session 닫힘을 기다리는 한계. 넘기면 기다림을 포기하고 나머지 정리를 이어간다. */
        const val CLOSE_TIMEOUT_SECONDS = 2L

        /** ARCore frame 갱신이 실패했을 때 다음 시도까지 쉬는 시간. 실패가 이어져도 CPU를 태우지 않는다. */
        const val FRAME_RETRY_DELAY_MS = 20L

        /**
         * stopRepeating 뒤 진행 중인 프레임이 정리될 때까지 기다리는 시간.
         *
         * 120 ms에서는 중단 경로의 차이가 3 frame으로 남았다. 중단은 `ON_STOP`에서 일어나 마감이
         * 더 오래 걸린다. 220 ms에서 정상 마감과 중단 모두 1~2 frame으로 내려왔다.
         */
        const val FRAME_DRAIN_DELAY_MS = 220L
    }
}

/**
 * 수집에 사용할 preview Surface를 내어 준다.
 *
 * ARCore Camera 텍스처의 크기를 인자로 받는다. 프리뷰가 그 텍스처를 잘림 없이 그리려면
 * 호출 측이 이 크기로 버퍼를 맞춘 Surface를 돌려줘야 한다.
 * 프리뷰를 붙일 수 없으면 `null`을 돌려주며, 수집은 프리뷰 없이 진행된다.
 */
fun interface PreviewSurfaceProvider {
    fun surfaceFor(
        width: Int,
        height: Int,
    ): Surface?
}

/**
 * ARCore Tracking 관측 한 건.
 *
 * [observedAtNs]는 이 관측을 만든 프레임의 카메라 시각이며 `arcore_poses.csv`의
 * `android_camera_timestamp_ns`와 같은 값이다.
 */
data class TrackingSample(
    val isTracking: Boolean,
    val observedAtNs: Long,
)
