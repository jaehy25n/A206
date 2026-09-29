package com.ssafy.s15p21a206.tiger.episode

import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 이 Session을 어떤 촬영 조건으로 찍었는지.
 *
 * 요청값과 실제값을 나눠 담는다. `CaptureRequest`에 넣었다고 센서가 그 값을 쓴 것은 아니며,
 * calibration은 실제로 쓰인 값 위에서만 뜻이 있기 때문이다.
 *
 * 기존 `metadata.json`에 더해지는 객체다. 수동 설정을 쓰지 않은 Session은 객체째 쓰지 않으므로, 이
 * 객체가 없는 예전 Session을 읽는 쪽도 깨지지 않는다.
 */
@Serializable
data class CaptureSettingsMetadata(
    /** 지금은 늘 `manual`이다. 기기 자동에 맡긴 Session은 이 객체를 쓰지 않는다. */
    val mode: String,
    val requested: RequestedCaptureSettings? = null,
    val actual: ActualCaptureSettings? = null,
    /**
     * 기본값과 같아도 반드시 적는다.
     *
     * kotlinx는 기본값과 같은 필드를 생략한다. 그러면 화이트 밸런스를 고정하지 않은 Session에서
     * 항목이 통째로 사라져, "고정하지 않았다"와 "이 앱이 아직 그것을 기록하지 않던 시절"이
     * 같은 모양이 된다. 둘은 다른 사실이다.
     */
    @OptIn(ExperimentalSerializationApi::class)
    @EncodeDefault
    @SerialName("awb_fixed")
    val awbFixed: Boolean = false,
)

@Serializable
data class RequestedCaptureSettings(
    @SerialName("focus_distance_diopter") val focusDistanceDiopter: Float,
    val iso: Int,
    @SerialName("exposure_time_ns") val exposureTimeNs: Long,
    @SerialName("frame_duration_ns") val frameDurationNs: Long,
    /** 목표 FPS는 30으로 고정돼 있지만, 기본값과 같다는 이유로 빠지면 계약이 반쪽이 된다. */
    @OptIn(ExperimentalSerializationApi::class)
    @EncodeDefault
    @SerialName("fps_target")
    val fpsTarget: Int = DEFAULT_FPS_TARGET,
) {
    private companion object {
        const val DEFAULT_FPS_TARGET = 30
    }
}

/**
 * 센서가 실제로 사용한 값. 읽지 못한 항목은 null이다.
 *
 * 값을 지어내 채우지 않는다. 없는 것은 없는 대로 남겨야 나중에 읽는 쪽이 속지 않는다.
 */
@Serializable
data class ActualCaptureSettings(
    @SerialName("focus_distance_diopter") val focusDistanceDiopter: Float? = null,
    val iso: Int? = null,
    @SerialName("exposure_time_ns") val exposureTimeNs: Long? = null,
    @SerialName("frame_duration_ns") val frameDurationNs: Long? = null,
    @SerialName("af_mode") val afMode: String? = null,
    @SerialName("ae_mode") val aeMode: String? = null,
    @SerialName("awb_mode") val awbMode: String? = null,
    @SerialName("awb_locked") val awbLocked: Boolean? = null,
)
