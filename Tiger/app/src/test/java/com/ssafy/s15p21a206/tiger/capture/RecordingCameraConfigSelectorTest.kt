package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.RecordingResolution
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RecordingCameraConfigSelectorTest {
    /** 실기기(SM-G973N)에서 확인한 후보. `imageSize`와 `textureSize` 쌍이다. */
    private data class Candidate(
        val imageSize: RecordingResolution,
        val textureSize: RecordingResolution,
    )

    private val vga = RecordingResolution(640, 480)
    private val candidates =
        listOf(
            Candidate(vga, RecordingResolution(1920, 1080)),
            Candidate(vga, RecordingResolution(1280, 720)),
            Candidate(vga, vga),
            Candidate(RecordingResolution(1280, 720), RecordingResolution(1280, 720)),
        )

    private fun select(target: RecordingResolution) =
        RecordingCameraConfigSelector.select(candidates, Candidate::imageSize, Candidate::textureSize, target)

    @Test
    fun `selects the candidate whose texture size matches the requested resolution`() {
        assertEquals(candidates[0], select(RecordingResolution(1920, 1080)))
        assertEquals(candidates[1], select(RecordingResolution(1280, 720)))
    }

    @Test
    fun `ignores candidates whose CPU image stream is larger than 640x480`() {
        assertEquals(vga, RecordingCameraConfigSelector.PREFERRED_IMAGE_SIZE)
        // 같은 textureSize를 가진 후보가 둘이면 imageSize가 640x480인 쪽만 고른다.
        assertEquals(candidates[1], select(RecordingResolution(1280, 720)))
    }

    @Test
    fun `returns null when no candidate has the requested texture size`() {
        assertNull(select(RecordingResolution(3840, 2160)))
    }
}
