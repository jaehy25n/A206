package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import com.ssafy.s15p21a206.tiger.episode.EpisodeState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class EpisodeLogWriterTest {
    @get:Rule val folder = TemporaryFolder()

    private fun writer(): Pair<EpisodeLogWriter, File> {
        val file = File(folder.root, "episodes.csv")
        return EpisodeLogWriter(file).also(EpisodeLogWriter::start) to file
    }

    private fun marker(
        task: String = "pick",
        objectName: String = "cup",
        endTimestampNs: Long? = 200L,
    ) = EpisodeMarker(
        episodeId = "e1",
        sessionId = "s1",
        startTimestampNs = 100L,
        endTimestampNs = endTimestampNs,
        task = task,
        objectName = objectName,
        outcome = EpisodeState.COMPLETED,
    )

    private fun File.dataRows() = readLines().drop(1).filter(String::isNotBlank)

    @Test fun `header stays unchanged`() {
        val (_, file) = writer()
        assertEquals("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome", file.readLines().first())
    }

    @Test fun `a marker becomes one row in column order`() {
        val (writer, file) = writer()
        writer.append(marker())
        assertEquals(listOf("e1,100,200,pick,cup,COMPLETED"), file.dataRows())
    }

    // 끝나지 않은 에피소드는 열을 비운 채로 남긴다. 0을 적으면 길이 0인 에피소드와 구분되지 않는다.
    @Test fun `an unfinished episode leaves the end column empty`() {
        val (writer, file) = writer()
        writer.append(marker(endTimestampNs = null))
        assertEquals(listOf("e1,100,,pick,cup,COMPLETED"), file.dataRows())
    }

    // task와 object는 사용자가 입력한다. 쉼표가 열을 밀거나 따옴표가 열을 닫으면 안 된다.
    @Test fun `a field with a comma or a quote is wrapped`() {
        val (writer, file) = writer()
        writer.append(marker(task = "pick, then place", objectName = "the \"red\" cup"))
        assertEquals(listOf("e1,100,200,\"pick, then place\",\"the \"\"red\"\" cup\",COMPLETED"), file.dataRows())
    }

    // 줄바꿈이 든 값은 감싼 채로 두 줄에 걸친다. RFC 4180대로 읽는 쪽이 한 행으로 잇는다.
    @Test fun `a field with a newline stays inside the quotes`() {
        val (writer, file) = writer()
        writer.append(marker(task = "pick\nplace"))
        assertEquals(listOf("e1,100,200,\"pick", "place\",cup,COMPLETED"), file.dataRows())
    }
}
