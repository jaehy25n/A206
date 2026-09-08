package com.ssafy.s15p21a206.tiger.sensor

import android.hardware.Sensor
import android.hardware.SensorManager

class SensorCapabilityPreflight(
    private val sensorManager: SensorManager,
) {
    fun check(): SensorPreflightResult {
        val required = listOf(Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE, Sensor.TYPE_ROTATION_VECTOR)
        val missing = required.firstOrNull { sensorManager.getDefaultSensor(it) == null }
        return if (missing == null) SensorPreflightResult.Ready else SensorPreflightResult.Failed("Required sensor is unavailable")
    }
}

sealed interface SensorPreflightResult {
    data object Ready : SensorPreflightResult

    data class Failed(
        val reason: String,
    ) : SensorPreflightResult
}
