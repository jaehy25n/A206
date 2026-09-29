package com.ssafy.s15p21a206.tiger.capture

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager

/**
 * Camera2가 제공하는 부가 광학 값을 읽는다.
 *
 * Intrinsic(fx·fy·cx·cy)은 녹화와 같은 ARCore GPU 텍스처 스트림에서 얻으므로 여기서 다루지 않는다.
 * 여기서 읽는 값은 전부 선택 항목이며, 기기가 제공하지 않으면 `null`을 돌려주고 예외를 던지지 않는다.
 * 값을 검증하거나 거부하지 않는다. 기기가 알려 준 것을 그대로 옮긴다.
 */
class CameraMetadataReader(
    private val cameraManager: CameraManager,
) {
    fun read(cameraId: String): CameraOptics =
        runCatching {
            val characteristics = cameraManager.getCameraCharacteristics(cameraId)
            val focalLengths = characteristics.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
            val sensorSize = characteristics.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
            val distortion = characteristics.get(CameraCharacteristics.LENS_DISTORTION)
            CameraOptics(
                focalLengthMm = focalLengths?.firstOrNull(),
                sensorWidthMm = sensorSize?.width,
                sensorHeightMm = sensorSize?.height,
                distortionCoefficients = distortion?.toList()?.takeIf(List<Float>::isNotEmpty),
            )
        }.getOrElse { CameraOptics() }
}

data class CameraOptics(
    val focalLengthMm: Float? = null,
    val sensorWidthMm: Float? = null,
    val sensorHeightMm: Float? = null,
    val distortionCoefficients: List<Float>? = null,
)
