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
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.ar.core.Session
import com.ssafy.s15p21a206.tiger.episode.CameraMetadata
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.util.EnumSet
import java.util.concurrent.CountDownLatch
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

    @Volatile private var cameraMetadata: CameraMetadata? = null

    fun start(displayNumber: Int): SessionBundle {
        check(bundle == null) { "Capture is already running" }
        val next = store.createStagingBundle(displayNumber)
        writeHeaders(next)
        try {
            val session = Session(appContext, EnumSet.of(Session.Feature.SHARED_CAMERA))
            val recorder =
                MediaRecorder().apply {
                    setVideoSource(MediaRecorder.VideoSource.SURFACE)
                    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                    setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                    setVideoFrameRate(30)
                    setVideoSize(session.cameraConfig.imageSize.width, session.cameraConfig.imageSize.height)
                    setOutputFile(next.mainVideo.absolutePath)
                    prepare()
                }
            arSession = session
            mediaRecorder = recorder
            bundle = next
            openSharedCamera(session, recorder)
            register(Sensor.TYPE_ACCELEROMETER)
            register(Sensor.TYPE_GYROSCOPE)
            register(Sensor.TYPE_ROTATION_VECTOR)
            return next
        } catch (error: Exception) {
            Log.e(TAG, "Could not start ARCore shared capture", error)
            releaseResources()
            next.directory.deleteRecursively()
            throw error
        }
    }

    fun stop(): FinalizeResult {
        val active = requireNotNull(bundle) { "No active capture" }
        sensorManager.unregisterListener(this)
        frameTimestamps?.recording = false
        val stopError = runCatching { mediaRecorder?.stop() }.exceptionOrNull()
        val camera = cameraMetadata
        releaseResources()
        bundle = null
        if (stopError != null) return FinalizeResult.Failed(stopError.message ?: "Video recording could not be finalized")
        return SessionFinalizer(store).finalize(active, camera = camera)
    }

    fun interrupt() {
        sensorManager.unregisterListener(this)
        frameTimestamps?.recording = false
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
                        val surfaces = sharedCamera.arCoreSurfaces.toMutableList().apply { add(recorder.surface) }
                        sharedCamera.setAppSurfaces(cameraId, listOf(recorder.surface))
                        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply { surfaces.forEach(::addTarget) }
                        device.createCaptureSession(
                            surfaces,
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
                                            startPoseCollection(session)
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
                            ),
                            handler,
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

    private fun startPoseCollection(session: Session) {
        poseCollectionRunning = true
        poseThread =
            Thread {
                val egl = OffscreenEgl()
                try {
                    egl.makeCurrent()
                    session.setCameraTextureName(egl.createTexture())
                    while (poseCollectionRunning) {
                        val frame = session.update()
                        val timestampNs = frame.androidCameraTimestamp
                        if (timestampNs == 0L || timestampNs == lastPoseTimestampNs) continue
                        lastPoseTimestampNs = timestampNs
                        val camera = frame.camera
                        trackingState.value =
                            TrackingSample(camera.trackingState == com.google.ar.core.TrackingState.TRACKING, timestampNs)
                        if (cameraMetadata == null) cameraMetadata = readCameraMetadata(session, camera)
                        val translation = camera.pose.translation
                        val rotation = camera.pose.rotationQuaternion
                        bundle?.arcorePoses?.appendText(
                            "$timestampNs,${translation[0]},${translation[1]},${translation[2]},${rotation[0]},${rotation[1]},${rotation[2]},${rotation[3]},${camera.trackingState.name},${camera.trackingFailureReason}\n",
                        )
                    }
                } finally {
                    egl.close()
                }
            }.apply {
                name = "TigerArPose"
                start()
            }
    }

    /**
     * 첫 유효 프레임에서 촬영 Camera의 Intrinsic을 1회 확보한다.
     *
     * ARCore의 이미지 스트림 기준 값이며, MediaRecorder 해상도를 같은 `cameraConfig.imageSize`로
     * 설정하므로 녹화 해상도와 대응이 보장된다. 실패하면 null을 돌려주고 수집은 그대로 이어간다.
     */
    private fun readCameraMetadata(
        session: Session,
        camera: com.google.ar.core.Camera,
    ): CameraMetadata? =
        runCatching {
            val intrinsics = camera.imageIntrinsics
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

        /** capture session 닫힘을 기다리는 한계. 넘기면 기다림을 포기하고 나머지 정리를 이어간다. */
        const val CLOSE_TIMEOUT_SECONDS = 2L
    }
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
