package com.ssafy.s15p21a206.tiger.capture

import android.graphics.Matrix
import android.graphics.RectF
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
     * 뷰 가운데를 축으로 [rotation]만큼 돌리는 행렬.
     *
     * 90·270도에서는 버퍼의 가로세로가 뒤바뀐 채 놓이므로 회전만 걸면 비율이 반대로 보인다.
     * 가로세로를 바꾼 버퍼 사각형을 뷰에 맞춘 뒤 다시 키우고 돌려, 원래 비율로 뷰를 채운다.
     * `Camera2Basic` 샘플의 `configureTransform`과 같은 방식이다.
     */
    fun matrix(
        viewWidth: Int,
        viewHeight: Int,
        bufferWidth: Int,
        bufferHeight: Int,
        rotation: Int,
    ): Matrix {
        val matrix = Matrix()
        if (viewWidth <= 0 || viewHeight <= 0 || bufferWidth <= 0 || bufferHeight <= 0) return matrix
        if (rotation != 90 && rotation != 270) {
            if (rotation == 180) matrix.postRotate(180f, viewWidth / 2f, viewHeight / 2f)
            return matrix
        }
        val centerX = viewWidth / 2f
        val centerY = viewHeight / 2f
        val viewRect = RectF(0f, 0f, viewWidth.toFloat(), viewHeight.toFloat())
        // 회전 뒤 버퍼가 놓일 모양이므로 가로세로를 바꿔 잡는다.
        val bufferRect = RectF(0f, 0f, bufferHeight.toFloat(), bufferWidth.toFloat())
        bufferRect.offset(centerX - bufferRect.centerX(), centerY - bufferRect.centerY())
        matrix.setRectToRect(viewRect, bufferRect, Matrix.ScaleToFit.FILL)
        val scale = maxOf(viewHeight.toFloat() / bufferHeight, viewWidth.toFloat() / bufferWidth)
        matrix.postScale(scale, scale, centerX, centerY)
        matrix.postRotate(rotation.toFloat(), centerX, centerY)
        return matrix
    }

    /** 위 보정값을 확인한 기준 센서 방향. */
    private const val SENSOR_ORIENTATION_BASELINE = 90
}
