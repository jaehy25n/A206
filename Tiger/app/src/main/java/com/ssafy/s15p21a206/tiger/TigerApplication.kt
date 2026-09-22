package com.ssafy.s15p21a206.tiger

import android.app.Application
import android.content.Context
import androidx.room.Room
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_2_3
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_3_4
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_4_5
import com.ssafy.s15p21a206.tiger.data.local.MIGRATION_5_6
import com.ssafy.s15p21a206.tiger.data.local.TigerDatabase
import com.ssafy.s15p21a206.tiger.episode.SessionBundleStore
import com.ssafy.s15p21a206.tiger.episode.SessionRepository
import com.ssafy.s15p21a206.tiger.upload.SessionUploadRequestFactory
import com.ssafy.s15p21a206.tiger.upload.SessionUploadService
import com.ssafy.s15p21a206.tiger.upload.SessionUploader
import okhttp3.OkHttpClient

/**
 * 프로세스 수명을 갖는 객체를 소유한다.
 *
 * 이전에는 `CaptureScreen`이 `remember`로 만들었다. `remember`는 composition 수명이라 Activity가
 * 재생성되면 다시 돌아 두 번째 인스턴스가 생겼고, 앞의 것을 닫는 경로가 없었다. manifest의
 * `configChanges`가 회전은 받지만 `uiMode`·`locale`·`fontScale`·`density`는 받지 않으므로,
 * 시스템 다크 모드 전환만으로 일어나는 일이었다.
 *
 * Room 데이터베이스와 `OkHttpClient`를 프로세스에 하나씩 두는 것은 두 라이브러리의 권장 사용법이다.
 *
 * `by lazy`를 쓰는 것은 생성 시점을 이전과 맞추기 위해서다. `onCreate`에서 만들면 앱이 뜰 때마다
 * 쓰지 않을 수도 있는 객체를 세운다. Room은 어차피 첫 쿼리까지 연결을 열지 않는다.
 */
class TigerApplication : Application() {
    val database: TigerDatabase by lazy {
        Room
            .databaseBuilder(this, TigerDatabase::class.java, "tiger.db")
            .addMigrations(MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6)
            .build()
    }

    val repository: SessionRepository by lazy {
        SessionRepository(
            database.captureSessionDao(),
            database.episodeMarkerDao(),
            SessionBundleStore(this),
        )
    }

    /** 업로드 endpoint가 빌드에 주입되지 않았으면 전송 기능이 없다. */
    val uploadService: SessionUploadService? by lazy {
        BuildConfig.UPLOAD_BASE_URL.takeIf(String::isNotBlank)?.let { baseUrl ->
            SessionUploadService(
                repository,
                SessionUploader(
                    OkHttpClient
                        .Builder()
                        .followRedirects(false)
                        .followSslRedirects(false)
                        .build(),
                    SessionUploadRequestFactory(baseUrl),
                ),
            )
        }
    }
}

internal val Context.tigerApplication: TigerApplication
    get() = applicationContext as TigerApplication
