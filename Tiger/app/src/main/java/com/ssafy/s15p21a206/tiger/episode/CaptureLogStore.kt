package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.CaptureLogDao
import com.ssafy.s15p21a206.tiger.data.local.CaptureLogEntity

class CaptureLogStore(private val captureLogDao: CaptureLogDao) {
    suspend fun add(log: CaptureLog) = captureLogDao.insert(
        CaptureLogEntity(log.id, log.sessionId, log.reason, log.summary, log.timestampNs, log.frameCount,
            log.accelerometerCount, log.gyroscopeCount, log.rotationVectorCount)
    )

    suspend fun clearAll() = captureLogDao.clearAll()
}
