package com.ssafy.s15p21a206.tiger.capture

import android.graphics.Matrix
import android.view.Surface

/**
 * Camera2 프리뷰를 TextureView에 바로 그릴 때 필요한 회전 보정.
 *
 * Camera2는 SurfaceTexture에 센서 방향 그대로 프레임을 넣는다. TextureView는 그 버퍼를 뷰 크기에
 * 늘여 그릴 뿐 회전을 반영하지 않으므로, 앱이 변환 행렬을 직접 걸어야 한다. 수집 중 프리뷰는
 * ARCore가 `setDisplayGeometry`로 처리하지만, 수집 전 유휴 프리뷰는 이 경로를 쓴다.
 */
object CameraPreviewTransform {
    /**
     * 프리뷰에 적용할 시계 방향 회전.
     *
     * `(센서 방향 - 화면 회전)`으로 계산하면 `SENSOR_ORIENTATION` 90인 기기를 가로로 들었을 때 0이
     * 나오지만, 실기기에서는 그대로 두면 영상이 시계 방향 90도로 누워 보인다. Camera2 프리뷰는
     * 버퍼를 뷰에 늘여 그리는 경로라 기준이 다르다. Google `Camera2Basic` 샘플도 `ROTATION_90`에서
     * `-90`을, `ROTATION_270`에서 `+90`을 건다. 같은 규칙을 따른다.
     *
     * @param displayRotation `Surface.ROTATION_*`. 자연 방향 대비 현재 화면이 돌아간 정도다.
     * @param sensorOrientation `CameraCharacteristics.SENSOR_ORIENTATION`. 대상 기기는 90이다.
     *   다른 값이면 그 차이만큼 더 돌린다.
     */
    fun rotationDegrees(
        sensorOrientation: Int,
        displayRotation: Int,
    ): Int {
        val base =
            when (displayRotation) {
                Surface.ROTATION_90 -> 270
                Surface.ROTATION_270 -> 90
                Surface.ROTATION_180 -> 180
                else -> 0
            }
        return ((base + sensorOrientation - SENSOR_ORIENTATION_BASELINE) % 360 + 360) % 360
    }

    /**
     * 뷰 가운데를 축으로 [rotation]만큼 돌리는 행렬. 90·270도에서는 회전 뒤 가로세로가 뒤바뀌므로,
     * 비율을 지킨 채 뷰 안에 들어오도록 함께 줄인다. 잘라내지 않는다.
     */
    fun matrix(
        viewWidth: Int,
        viewHeight: Int,
        rotation: Int,
    ): Matrix {
        val matrix = Matrix()
        if (rotation == 0 || viewWidth <= 0 || viewHeight <= 0) return matrix
        val centerX = viewWidth / 2f
        val centerY = viewHeight / 2f
        matrix.postRotate(rotation.toFloat(), centerX, centerY)
        if (rotation == 90 || rotation == 270) {
            // 회전하면 뷰의 가로가 세로 자리에, 세로가 가로 자리에 놓인다. 둘 다 넘치지 않는 배율을 쓴다.
            val scale = minOf(viewWidth.toFloat() / viewHeight, viewHeight.toFloat() / viewWidth)
            matrix.postScale(scale, scale, centerX, centerY)
        }
        return matrix
    }

    /** 위 보정값을 확인한 기준 센서 방향. */
    private const val SENSOR_ORIENTATION_BASELINE = 90
}
