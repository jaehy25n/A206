package com.ssafy.s15p21a206.tiger

import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertSame
import org.junit.Test

/**
 * Activity가 재생성돼도 Room과 `OkHttpClient`가 하나씩만 있는지 확인한다.
 *
 * 이전에는 `CaptureScreen`이 `remember`로 만들어서, 재생성될 때마다 인스턴스가 하나씩 더 생기고
 * 앞의 것은 닫히지 않았다. manifest의 `configChanges`가 회전은 받지만 `uiMode`·`locale`은 받지
 * 않아 다크 모드 전환만으로 일어나던 일이다.
 *
 * `recreate()`는 그 경로를 그대로 탄다. 같이 확인되는 것이 하나 더 있는데, manifest에
 * `TigerApplication`이 등록되지 않았거나 화면이 그것을 못 읽으면 첫 composition에서
 * `ClassCastException`으로 죽으므로 배선 자체도 이 테스트가 지난다.
 */
class ApplicationScopedDependencyTest {
    @Test
    fun theSameDependenciesAreServedAcrossActivityRecreation() {
        val application = ApplicationProvider.getApplicationContext<TigerApplication>()
        val database = application.database
        val repository = application.repository
        val uploadService = application.uploadService

        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.recreate()
        }

        assertSame(database, application.database)
        assertSame(repository, application.repository)
        assertSame(uploadService, application.uploadService)
    }
}
