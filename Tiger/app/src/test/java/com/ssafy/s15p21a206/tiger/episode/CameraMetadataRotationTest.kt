package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertEquals
import org.junit.Test

class CameraMetadataRotationTest {
    private val base =
        CameraMetadata(
            cameraId = "0",
            imageWidth = 640,
            imageHeight = 480,
            fx = 497.3f,
            fy = 497.2f,
            cx = 324.0f,
            cy = 240.2f,
        )

    @Test fun `회전이 없으면 기하가 그대로다`() {
        val rotated = base.rotatedClockwise(0)
        assertEquals(base.copy(videoRotationDegrees = 0), rotated)
    }

    // 픽셀 (x, y)가 (H - y, x)로 옮겨지므로 가로세로와 초점거리 축이 바뀐다.
    @Test fun `시계 방향 90도는 가로세로와 축을 바꾼다`() {
        val rotated = base.rotatedClockwise(90)
        assertEquals(480, rotated.imageWidth)
        assertEquals(640, rotated.imageHeight)
        assertEquals(497.2f, rotated.fx)
        assertEquals(497.3f, rotated.fy)
        assertEquals(480f - 240.2f, rotated.cx)
        assertEquals(324.0f, rotated.cy)
        assertEquals(90, rotated.videoRotationDegrees)
    }

    @Test fun `180도는 크기를 유지하고 주점만 뒤집는다`() {
        val rotated = base.rotatedClockwise(180)
        assertEquals(640, rotated.imageWidth)
        assertEquals(480, rotated.imageHeight)
        assertEquals(497.3f, rotated.fx)
        assertEquals(640f - 324.0f, rotated.cx)
        assertEquals(480f - 240.2f, rotated.cy)
    }

    @Test fun `270도는 90도의 반대 방향이다`() {
        val rotated = base.rotatedClockwise(270)
        assertEquals(480, rotated.imageWidth)
        assertEquals(640, rotated.imageHeight)
        assertEquals(240.2f, rotated.cx)
        assertEquals(640f - 324.0f, rotated.cy)
        assertEquals(270, rotated.videoRotationDegrees)
    }

    // 네 번 돌리면 제자리로 돌아와야 공식이 서로 어긋나지 않는다.
    @Test fun `90도를 네 번 돌리면 원래 기하로 돌아온다`() {
        var m = base
        repeat(4) { m = m.rotatedClockwise(90) }
        assertEquals(base.imageWidth, m.imageWidth)
        assertEquals(base.imageHeight, m.imageHeight)
        assertEquals(base.fx, m.fx)
        assertEquals(base.fy, m.fy)
        assertEquals(base.cx, m.cx, 0.001f)
        assertEquals(base.cy, m.cy, 0.001f)
    }

    @Test fun `음수와 360을 넘는 각도도 정규화된다`() {
        assertEquals(base.rotatedClockwise(90), base.rotatedClockwise(450))
        assertEquals(base.rotatedClockwise(270), base.rotatedClockwise(-90))
    }
}
