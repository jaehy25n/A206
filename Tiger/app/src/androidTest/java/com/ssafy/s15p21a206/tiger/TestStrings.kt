package com.ssafy.s15p21a206.tiger

import android.content.Context
import androidx.annotation.StringRes
import androidx.test.core.app.ApplicationProvider

/**
 * 화면 문구를 리소스에서 읽어 온다.
 *
 * 테스트가 문구를 직접 적어 두면 문구를 다듬을 때마다 테스트가 함께 썩는다. 그때 깨지는 것은
 * 동작이 아니라 글자인데, 실패 메시지는 그 둘을 구분해 주지 않는다. 리소스를 거치면 테스트는
 * "이 자리에 이 문구가 보인다"가 아니라 "이 자리에 이 문구용 이름이 붙어 있다"를 검사한다.
 */
fun string(
    @StringRes resourceId: Int,
    vararg formatArgs: Any,
): String = ApplicationProvider.getApplicationContext<Context>().getString(resourceId, *formatArgs)
