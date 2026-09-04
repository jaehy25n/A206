package com.ssafy.s15p21a206.tiger.capture

import android.content.Context
import android.graphics.SurfaceTexture
import android.hardware.Camera
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.media.MediaRecorder
import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.FinalizeResult
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionFinalizer
import java.io.File

@Suppress("DEPRECATION")
class AndroidCaptureRuntime(private val context: Context, private val store: SessionBundleStore) : SensorEventListener {
    private val sensorManager = context.getSystemService(SensorManager::class.java)
    private var camera: Camera? = null
    private var previewTexture: SurfaceTexture? = null
    private var recorder: MediaRecorder? = null
    private var bundle: SessionBundle? = null
    private val sensorFiles = mutableMapOf<Int, File>()

    fun start(displayNumber: Int): SessionBundle {
        check(bundle == null) { "Capture is already running" }
        val next = store.createStagingBundle(displayNumber)
        writeHeaders(next)
        val openedCamera = Camera.open()
        val texture = SurfaceTexture(0)
        val mediaRecorder = try {
            openedCamera.setPreviewTexture(texture)
            openedCamera.startPreview()
            openedCamera.unlock()
            MediaRecorder().apply {
                setCamera(openedCamera)
                setVideoSource(MediaRecorder.VideoSource.CAMERA)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                setVideoFrameRate(30)
                setOutputFile(next.mainVideo.absolutePath)
                prepare()
                start()
            }
        } catch (error: Exception) {
            texture.release()
            openedCamera.release()
            throw error
        }
        camera = openedCamera
        previewTexture = texture
        recorder = mediaRecorder
        bundle = next
        register(Sensor.TYPE_ACCELEROMETER)
        register(Sensor.TYPE_GYROSCOPE)
        register(Sensor.TYPE_ROTATION_VECTOR)
        return next
    }

    fun stop(): FinalizeResult {
        val active = requireNotNull(bundle) { "No active capture" }
        sensorManager.unregisterListener(this)
        val stopError = runCatching { recorder?.stop() }.exceptionOrNull()
        recorder?.release(); recorder = null
        camera?.lock(); camera?.release(); camera = null
        previewTexture?.release(); previewTexture = null
        bundle = null
        if (stopError != null) return FinalizeResult.Failed(stopError.message ?: "Video recording could not be finalized")
        return SessionFinalizer(store).finalize(active)
    }

    fun interrupt() {
        sensorManager.unregisterListener(this)
        runCatching { recorder?.stop() }
        recorder?.release(); recorder = null
        camera?.lock(); camera?.release(); camera = null
        previewTexture?.release(); previewTexture = null
        bundle = null
    }

    override fun onSensorChanged(event: SensorEvent) {
        val target = sensorFiles[event.sensor.type] ?: return
        val values = event.values
        val row = when (event.sensor.type) {
            Sensor.TYPE_ROTATION_VECTOR -> "${event.timestamp},${values.getOrElse(0) { 0f }},${values.getOrElse(1) { 0f }},${values.getOrElse(2) { 0f }},${values.getOrElse(3) { 0f }},${values.getOrElse(4) { 0f }},${event.accuracy}"
            else -> "${event.timestamp},${values.getOrElse(0) { 0f }},${values.getOrElse(1) { 0f }},${values.getOrElse(2) { 0f }},${event.accuracy}"
        }
        target.appendText("$row\n")
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    fun appendEpisode(marker: EpisodeMarker) {
        val active = bundle ?: return
        active.episodes.appendText(
            listOf(
                marker.episodeId,
                marker.startTimestampNs.toString(),
                marker.endTimestampNs.orEmpty(),
                marker.task.csvField(),
                marker.objectName.csvField(),
                marker.outcome.name
            ).joinToString(",") + "\n"
        )
    }

    private fun register(type: Int) {
        sensorManager.getDefaultSensor(type)?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
    }

    private fun writeHeaders(bundle: SessionBundle) {
        File(bundle.mainFrameTimestamps.path).writeText("frame_number,timestamp_ns,timestamp_source\n")
        File(bundle.accelerometer.path).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(bundle.gyroscope.path).writeText("timestamp_ns,x,y,z,accuracy\n")
        File(bundle.rotationVector.path).writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        File(bundle.arcorePoses.path).writeText("android_camera_timestamp_ns,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_failure_reason\n")
        File(bundle.episodes.path).writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
        sensorFiles[Sensor.TYPE_ACCELEROMETER] = bundle.accelerometer
        sensorFiles[Sensor.TYPE_GYROSCOPE] = bundle.gyroscope
        sensorFiles[Sensor.TYPE_ROTATION_VECTOR] = bundle.rotationVector
    }

    private fun Long?.orEmpty() = this?.toString().orEmpty()

    private fun String.csvField(): String = if (contains(',') || contains('"') || contains('\n')) {
        "\"${replace("\"", "\"\"")}\""
    } else this
}
