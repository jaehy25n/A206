package com.ssafy.s15p21a206.tiger.capture

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.params.StreamConfigurationMap
import com.ssafy.s15p21a206.tiger.episode.CameraConfig
import com.ssafy.s15p21a206.tiger.episode.IntRect
import com.ssafy.s15p21a206.tiger.episode.RecordingResolution

class CameraCapabilityPreflight(
    private val cameraManager: CameraManager,
) {
    fun check(resolution: RecordingResolution): CameraPreflightResult {
        val candidate =
            cameraManager.cameraIdList.firstOrNull { id ->
                cameraManager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK
            } ?: return CameraPreflightResult.Failed("Rear main camera is unavailable")
        val characteristics = cameraManager.getCameraCharacteristics(candidate)
        val streamMap =
            characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?: return CameraPreflightResult.Failed("Camera stream configuration is unavailable")
        if (!streamMap.supports(resolution) || !characteristics.supportsThirtyFps()) {
            return CameraPreflightResult.Failed("Requested 30 FPS resolution is unavailable")
        }
        if (characteristics.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) !=
            CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
        ) {
            return CameraPreflightResult.Failed("Camera timestamp source is not REALTIME")
        }
        val focal =
            characteristics.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull()
                ?: return CameraPreflightResult.Failed("Focal length is unavailable")
        val sensor =
            characteristics.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
                ?: return CameraPreflightResult.Failed("Sensor size is unavailable")
        val active =
            characteristics.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
                ?: return CameraPreflightResult.Failed("Active array is unavailable")
        val preCorrection =
            characteristics.get(CameraCharacteristics.SENSOR_INFO_PRE_CORRECTION_ACTIVE_ARRAY_SIZE)
                ?: return CameraPreflightResult.Failed("Pre-correction active array is unavailable")
        val expected = intArrayOf(0, 0, 4032, 3024)
        if (kotlin.math.abs(focal - 4.32000017f) > 0.01f ||
            kotlin.math.abs(sensor.width - 5.64499998f) > 0.01f ||
            kotlin.math.abs(sensor.height - 4.23400021f) > 0.01f ||
            active.toArray().contentEquals(expected).not() ||
            preCorrection.toArray().contentEquals(expected).not()
        ) {
            return CameraPreflightResult.Failed("Camera does not match Galaxy S10 main 1× profile")
        }
        return CameraPreflightResult.Ready(
            CameraConfig(
                logicalCameraId = candidate,
                selectedPhysicalCameraId = candidate,
                focalLengthMm = focal,
                sensorPhysicalWidthMm = sensor.width,
                sensorPhysicalHeightMm = sensor.height,
                activeArray = active.toIntRect(),
                preCorrectionActiveArray = preCorrection.toIntRect(),
                resolution = resolution,
            ),
        )
    }
}

private fun StreamConfigurationMap.supports(resolution: RecordingResolution) =
    getOutputSizes(android.media.MediaRecorder::class.java)?.any { it.width == resolution.width && it.height == resolution.height } == true

private fun CameraCharacteristics.supportsThirtyFps() =
    get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)?.any { it.lower <= 30 && it.upper >= 30 } == true

private fun android.graphics.Rect.toArray() = intArrayOf(left, top, right, bottom)

private fun android.graphics.Rect.toIntRect() = IntRect(left, top, right, bottom)

sealed interface CameraPreflightResult {
    data class Ready(
        val config: CameraConfig,
    ) : CameraPreflightResult

    data class Failed(
        val reason: String,
    ) : CameraPreflightResult
}
