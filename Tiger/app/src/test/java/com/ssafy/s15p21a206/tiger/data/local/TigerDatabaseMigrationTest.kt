package com.ssafy.s15p21a206.tiger.data.local

import org.junit.Assert.assertEquals
import org.junit.Test

class TigerDatabaseMigrationTest {
    @Test
    fun `version four migration adds a non null wall clock start timestamp`() {
        assertEquals(3, MIGRATION_3_4.startVersion)
        assertEquals(4, MIGRATION_3_4.endVersion)
    }
}
