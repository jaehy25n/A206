package com.ssafy.s15p21a206.tiger.capture

/**
 * 한 Session 내내 고정할 촬영 조건.
 *
 * 프리뷰와 녹화가 같은 값을 쓰게 하려고 하나의 객체로 든다. 화면이 따로, 카메라 요청이 따로
 * 값을 들면 둘이 어긋나도 아무도 모른다. calibration과 dataset이 같은 광학 조건이어야 한다는
 * 것이 이 기능의 전부이므로, 그 어긋남은 조용한 실패가 된다.
 *
 * 값은 전부 기기가 보고한 범위 안으로 좁힌 뒤에만 들어온다. [ManualCameraCapabilities.coerce]가
 * 그 일을 하며, 이 클래스는 좁히기를 스스로 하지 않는다.
 */
data class ManualCameraConfig(
    /** 0이 무한대, 클수록 가깝다. 단위는 diopter(1/m). */
    val focusDistanceDiopter: Float,
    val iso: Int,
    val exposureTimeNs: Long,
    val frameDurationNs: Long = TARGET_FRAME_DURATION_NS,
    /** null이면 AWB AUTO로 둔다. 값이 있으면 그 gain으로 고정한다. */
    val whiteBalance: FixedWhiteBalance? = null,
) {
    /**
     * 노출이 프레임 간격을 넘지 않는지.
     *
     * 넘으면 센서가 프레임 간격을 노출에 맞춰 늘려 30 fps가 깨진다. UI에서 고를 수 없게 막지만,
     * 저장된 값을 불러오는 경로도 있으므로 여기서도 물어볼 수 있게 둔다.
     */
    val exposureFitsFrame: Boolean get() = exposureTimeNs <= frameDurationNs

    val awbFixed: Boolean get() = whiteBalance != null

    companion object {
        const val TARGET_FPS = 30

        /** 30 fps의 프레임 간격. dataset contract가 고정한 값이다. */
        const val TARGET_FRAME_DURATION_NS = 33_333_333L
    }
}

/**
 * 프리뷰에서 수렴시킨 화이트 밸런스를 그대로 옮기기 위한 값.
 *
 * `CONTROL_AWB_LOCK`을 쓰지 않는 이유는 lock이 절대값이 아니라 "지금 수렴한 값을 유지"라는 상대
 * 상태이기 때문이다. 프리뷰의 `CameraDevice`를 닫고 ARCore가 새 session을 열면 AWB는 처음부터
 * 다시 수렴하므로, 프리뷰에서 잠근 색이 녹화본으로 넘어가지 않는다. gain과 transform을 숫자로
 * 들고 건너가는 것만이 두 session에서 같은 색을 보장한다.
 *
 * Camera2 타입(`RggbChannelVector`, `ColorSpaceTransform`) 대신 순수 값으로 두어 단위 테스트에서
 * 다룰 수 있게 한다. Camera2 타입으로의 변환은 [applyManualCamera]가 한다.
 */
data class FixedWhiteBalance(
    val redGain: Float,
    val greenEvenGain: Float,
    val greenOddGain: Float,
    val blueGain: Float,
    /** `COLOR_CORRECTION_TRANSFORM`의 유리수 9개를 분자·분모 쌍 18개로 편 것. */
    val transform: List<Int>,
) {
    init {
        require(transform.size == TRANSFORM_SIZE) { "Color correction transform must hold $TRANSFORM_SIZE values" }
    }

    companion object {
        const val TRANSFORM_SIZE = 18
    }
}

/**
 * md가 정한 shutter preset. 자유 입력 대신 이 다섯만 제공한다.
 *
 * 값은 1초를 분모로 나눈 나노초다. 1/500만 2,000,000 ns로 떨어지고 나머지는 반올림이 들어간다.
 */
enum class ShutterPreset(
    val label: String,
    val exposureTimeNs: Long,
) {
    ONE_THIRTIETH("1/30", 33_333_333L),
    ONE_SIXTIETH("1/60", 16_666_667L),
    ONE_TWENTIETH_HUNDRED("1/120", 8_333_333L),
    ONE_TWO_FORTIETH("1/240", 4_166_667L),
    ONE_FIVE_HUNDREDTH("1/500", 2_000_000L),
}

/**
 * 실제 녹화에 쓰일 카메라가 무엇을 지원하는지.
 *
 * 임의의 후면 카메라가 아니라 ARCore가 고른 `cameraId`에서 읽어야 한다. 논리 카메라가 여럿인
 * 기기에서는 ISO·노출 범위가 카메라마다 다르고, 프리뷰에서 고른 값이 녹화 카메라의 범위를
 * 벗어나면 조용히 다른 값으로 찍힌다.
 */
data class ManualCameraCapabilities(
    val cameraId: String,
    val manualSensor: Boolean,
    val aeOffSupported: Boolean,
    val afOffSupported: Boolean,
    val awbOffSupported: Boolean,
    val awbLockSupported: Boolean,
    /** `LENS_INFO_MINIMUM_FOCUS_DISTANCE`. 0이면 고정 초점 렌즈라 초점을 옮길 수 없다. */
    val maxFocusDiopter: Float,
    val isoRange: IntRange?,
    val exposureRangeNs: LongRange?,
    val maxFrameDurationNs: Long?,
) {
    val focusSupported: Boolean get() = afOffSupported && maxFocusDiopter > 0f

    val isoSupported: Boolean get() = manualSensor && aeOffSupported && isoRange != null

    val exposureSupported: Boolean get() = manualSensor && aeOffSupported && exposureRangeNs != null

    /** gain을 직접 거는 방식이라 `AWB_MODE_OFF`가 있어야 한다. lock 가능 여부는 참고로만 든다. */
    val whiteBalanceSupported: Boolean get() = awbOffSupported

    /** 수동 설정을 쓸 수 없는 이유. null이면 쓸 수 있다. 화면은 이 문구를 그대로 보여 준다. */
    val unsupportedReason: String?
        get() =
            when {
                !manualSensor -> "이 카메라는 MANUAL_SENSOR를 지원하지 않습니다"
                !aeOffSupported -> "이 카메라는 노출 수동 제어를 지원하지 않습니다"
                isoRange == null -> "ISO 범위를 읽을 수 없습니다"
                exposureRangeNs == null -> "셔터 범위를 읽을 수 없습니다"
                else -> null
            }

    /** 이 preset을 고를 수 있는지. 기기 범위 밖이거나 30 fps 프레임 간격을 넘으면 고를 수 없다. */
    fun allows(preset: ShutterPreset): Boolean {
        val range = exposureRangeNs ?: return false
        return preset.exposureTimeNs in range && preset.exposureTimeNs <= frameDurationNs()
    }

    /**
     * 실제로 걸 프레임 간격.
     *
     * 30 fps를 목표로 하되 기기가 허용하는 최대를 넘지 않는다. `SENSOR_INFO_MAX_FRAME_DURATION`은
     * 보통 30 fps보다 훨씬 길어 그대로 통과한다.
     */
    fun frameDurationNs(): Long {
        val max = maxFrameDurationNs ?: return ManualCameraConfig.TARGET_FRAME_DURATION_NS
        return minOf(ManualCameraConfig.TARGET_FRAME_DURATION_NS, max)
    }

    /** 이 기기에서 고를 수 있는 preset만. 하나도 없으면 빈 목록이다. */
    fun availableShutterPresets(): List<ShutterPreset> = ShutterPreset.entries.filter(::allows)

    /** 처음 열었을 때 보여 줄 값. 저장된 설정이 없을 때 쓴다. */
    fun defaultConfig(): ManualCameraConfig =
        coerce(
            ManualCameraConfig(
                focusDistanceDiopter = DEFAULT_FOCUS_DIOPTER,
                iso = DEFAULT_ISO,
                exposureTimeNs = ShutterPreset.ONE_SIXTIETH.exposureTimeNs,
            ),
        )

    /**
     * 설정을 이 기기가 받는 범위 안으로 좁힌다.
     *
     * 노출은 프레임 간격까지 함께 넘지 않게 자른다. 두 제약을 한곳에서 거는 것은, 화면과 저장소와
     * 카메라 요청이 각자 자르면 어디서 잘렸는지 알 수 없기 때문이다.
     */
    fun coerce(config: ManualCameraConfig): ManualCameraConfig {
        val frameDuration = frameDurationNs()
        val exposureCeiling = minOf(frameDuration, exposureRangeNs?.last ?: frameDuration)
        val exposureFloor = exposureRangeNs?.first ?: 1L
        return config.copy(
            focusDistanceDiopter = config.focusDistanceDiopter.coerceIn(0f, maxFocusDiopter),
            iso = isoRange?.let { config.iso.coerceIn(it.first, it.last) } ?: config.iso,
            exposureTimeNs = config.exposureTimeNs.coerceIn(minOf(exposureFloor, exposureCeiling), exposureCeiling),
            frameDurationNs = frameDuration,
            whiteBalance = config.whiteBalance.takeIf { whiteBalanceSupported },
        )
    }

    private companion object {
        /** 25 cm. manipulation 작업 영역이 대개 이 근처다. 기기 최대보다 멀면 그쪽으로 잘린다. */
        const val DEFAULT_FOCUS_DIOPTER = 4f

        const val DEFAULT_ISO = 100
    }
}
