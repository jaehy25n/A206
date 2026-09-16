package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.RecordingResolution

/**
 * 녹화 해상도에 맞는 ARCore Camera config를 고른다.
 *
 * 녹화 stream은 `cameraConfig.textureSize`를 따르므로, 원하는 해상도를 얻으려면 그 크기를 가진
 * config를 세션에 지정해야 한다. ARCore의 `CameraConfig`는 인스턴스를 만들 수 없어 단위 테스트에서
 * 다룰 수 없으므로, 후보의 두 크기를 읽는 방법을 인자로 받아 선택 규칙만 분리한다.
 */
object RecordingCameraConfigSelector {
    /**
     * 후보가 가져야 할 CPU 이미지 크기.
     *
     * 이 값을 키우면 CPU 이미지 stream과 녹화 stream이 함께 커져 대상 기기가 stream 조합을
     * 거부한다. 근거는 `capture-state-machine.md`에 있다.
     */
    val PREFERRED_IMAGE_SIZE = RecordingResolution(640, 480)

    /** 조건을 만족하는 후보가 없으면 `null`을 돌려준다. 호출 측은 기본 config로 이어간다. */
    fun <T> select(
        candidates: List<T>,
        imageSizeOf: (T) -> RecordingResolution,
        textureSizeOf: (T) -> RecordingResolution,
        target: RecordingResolution,
    ): T? = candidates.firstOrNull { imageSizeOf(it) == PREFERRED_IMAGE_SIZE && textureSizeOf(it) == target }
}
