package com.ssafy.s15p21a206.tiger.episode

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SessionExportModelsTest {
    @Test
    fun `export supports success and retry transitions`() {
        val first = SessionExport("session").start("tree", "attempt-1")
        assertEquals(ExportState.EXPORTED, first.complete().state)

        val retry = first.fail("I/O failure").start("tree", "attempt-2")
        assertEquals(ExportState.EXPORTING, retry.state)
        assertNotEquals(first.attemptId, retry.attemptId)
    }
}
