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
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
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

    @Volatile private var poseCollectionRunning = false
    private var bundle: SessionBundle? = null
    private var lastFrameTimestampNs = Long.MIN_VALUE
    private var lastPoseTimestampNs = Long.MIN_VALUE

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
        val stopError = runCatching { mediaRecorder?.stop() }.exceptionOrNull()
        releaseResources()
        bundle = null
        if (stopError != null) return FinalizeResult.Failed(stopError.message ?: "Video recording could not be finalized")
        return SessionFinalizer(store).finalize(active)
    }

    fun interrupt() {
        sensorManager.unregisterListener(this)
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
                    if (timestampNs != lastFrameTimestampNs) {
                        lastFrameTimestampNs = timestampNs
                        bundle?.mainFrameTimestamps?.appendText("$timestampNs,$timestampNs,SENSOR_TIMESTAMP\n")
                    }
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

    private fun releaseResources() {
        poseCollectionRunning = false
        poseThread?.join(500)
        poseThread = null
        runCatching { arSession?.pause() }
        arSession?.close()
        arSession = null
        captureSession?.close()
        captureSession = null
        cameraDevice?.close()
        cameraDevice = null
        mediaRecorder?.release()
        mediaRecorder = null
        cameraThread?.quitSafely()
        cameraThread = null
        sensorFiles.clear()
    }

    private fun register(type: Int) {
        sensorManager.getDefaultSensor(type)?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
    }

    private fun writeHeaders(bundle: SessionBundle) {
        bundle.mainFrameTimestamps.writeText("frame_number,timestamp_ns,timestamp_source\n")
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
    }
}
