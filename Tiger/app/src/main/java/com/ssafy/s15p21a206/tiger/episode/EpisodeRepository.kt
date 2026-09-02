package com.ssafy.s15p21a206.tiger.episode

import com.ssafy.s15p21a206.tiger.data.local.EpisodeDao
import com.ssafy.s15p21a206.tiger.data.local.EpisodeEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

class EpisodeRepository(
    private val episodeDao: EpisodeDao,
    private val bundleStore: EpisodeBundleStore
) {
    fun observeCompleted(): Flow<List<Episode>> = episodeDao.observeCompleted().map { episodes ->
        episodes.map(EpisodeEntity::toEpisode)
    }

    suspend fun save(episode: Episode) = episodeDao.upsert(episode.toEntity())

    suspend fun updateUploadState(episodeId: String, state: UploadState) =
        episodeDao.updateUploadState(episodeId, state.name)

    fun recoverStaging() = bundleStore.clearStaging()
}

private fun EpisodeEntity.toEpisode() = Episode(
    episodeId = episodeId,
    displayName = displayName,
    task = task,
    objectName = objectName,
    recordingState = RecordingState.valueOf(recordingState),
    uploadState = UploadState.valueOf(uploadState),
    recordingStartMonotonicTimestampNs = recordingStartNs,
    recordingEndMonotonicTimestampNs = recordingEndNs,
    bundlePath = bundlePath
)

private fun Episode.toEntity() = EpisodeEntity(
    episodeId = episodeId,
    displayName = displayName,
    task = task,
    objectName = objectName,
    recordingState = recordingState.name,
    uploadState = uploadState.name,
    recordingStartNs = recordingStartMonotonicTimestampNs,
    recordingEndNs = recordingEndMonotonicTimestampNs,
    bundlePath = bundlePath
)
