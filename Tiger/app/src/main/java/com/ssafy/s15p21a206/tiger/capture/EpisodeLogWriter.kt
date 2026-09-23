package com.ssafy.s15p21a206.tiger.capture

import com.ssafy.s15p21a206.tiger.episode.EpisodeMarker
import java.io.File

/**
 * 에피소드 경계를 세션 bundle의 `episodes.csv`에 적는다.
 *
 * task와 object는 사용자가 입력한 문자열이라 쉼표·따옴표·줄바꿈이 들어올 수 있다. 그 셋을 만나면
 * 따옴표로 감싸고 안의 따옴표를 겹쳐, 한 행이 두 행으로 갈라지거나 열이 밀리지 않게 한다.
 */
class EpisodeLogWriter(
    private val file: File,
) {
    /** 헤더를 적어 파일을 연다. */
    fun start() {
        file.writeText("episode_id,start_timestamp_ns,end_timestamp_ns,task,object,outcome\n")
    }

    fun append(marker: EpisodeMarker) {
        file.appendText(
            listOf(
                marker.episodeId,
                marker.startTimestampNs.toString(),
                marker.endTimestampNs.orEmpty(),
                marker.task.csvField(),
                marker.objectName.csvField(),
                marker.outcome.name,
            ).joinToString(",") +
                "\n",
        )
    }

    private fun Long?.orEmpty() = this?.toString().orEmpty()

    private fun String.csvField(): String = if (contains(',') || contains('"') || contains('\n')) "\"${replace("\"", "\"\"")}\"" else this
}
