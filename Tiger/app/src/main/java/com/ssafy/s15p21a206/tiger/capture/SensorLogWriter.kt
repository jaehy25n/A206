package com.ssafy.s15p21a206.tiger.capture

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import com.ssafy.s15p21a206.tiger.episode.SessionBundle
import java.io.File

/**
 * 가속도계·자이로·회전 벡터 표본을 세션 bundle의 CSV에 적는다.
 *
 * 여는 일이 [open]과 [listen] 둘로 나뉜 것은 시점이 다르기 때문이다. 헤더는 수집을 시작하기 전에
 * 적어 두어야 도중에 실패해도 파일 모양이 온전하고, 수신은 카메라가 돌기 시작한 뒤에 연다.
 *
 * 닫는 일도 [stopListening]과 [close] 둘이다. 수신을 끊은 뒤에도 이미 전달된 표본이 남아 있어,
 * 기록 대상을 비우는 것은 나머지 정리가 끝난 뒤다.
 */
class SensorLogWriter(
    private val sensorManager: SensorManager,
) : SensorEventListener {
    private val files = mutableMapOf<Int, File>()

    /** 세 센서의 CSV 헤더를 적고 기록 대상을 잡는다. */
    fun open(bundle: SessionBundle) {
        bundle.accelerometer.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.gyroscope.writeText("timestamp_ns,x,y,z,accuracy\n")
        bundle.rotationVector.writeText("timestamp_ns,x,y,z,scalar_component,heading_accuracy_rad,accuracy\n")
        files[Sensor.TYPE_ACCELEROMETER] = bundle.accelerometer
        files[Sensor.TYPE_GYROSCOPE] = bundle.gyroscope
        files[Sensor.TYPE_ROTATION_VECTOR] = bundle.rotationVector
    }

    /** 표본 수신을 연다. */
    fun listen() {
        register(Sensor.TYPE_ACCELEROMETER)
        register(Sensor.TYPE_GYROSCOPE)
        register(Sensor.TYPE_ROTATION_VECTOR)
    }

    /** 표본 수신을 끊는다. */
    fun stopListening() {
        sensorManager.unregisterListener(this)
    }

    /** 기록 대상을 비운다. 이 뒤에 닿은 표본은 버려진다. */
    fun close() {
        files.clear()
    }

    override fun onSensorChanged(event: SensorEvent) {
        val target = files[event.sensor.type] ?: return
        val values = event.values

        fun axis(index: Int) = values.getOrElse(index) { 0f }
        val row =
            when (event.sensor.type) {
                Sensor.TYPE_ROTATION_VECTOR ->
                    "${event.timestamp},${axis(0)},${axis(1)},${axis(2)},${axis(3)},${axis(4)},${event.accuracy}"
                else -> "${event.timestamp},${axis(0)},${axis(1)},${axis(2)},${event.accuracy}"
            }
        target.appendText("$row\n")
    }

    override fun onAccuracyChanged(
        sensor: Sensor?,
        accuracy: Int,
    ) = Unit

    private fun register(type: Int) {
        sensorManager.getDefaultSensor(type)?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }
    }
}
