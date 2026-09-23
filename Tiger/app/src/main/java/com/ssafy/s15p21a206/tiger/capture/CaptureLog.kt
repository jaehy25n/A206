package com.ssafy.s15p21a206.tiger.capture

/**
 * 수집 경로가 함께 쓰는 logcat 태그.
 *
 * 한 번의 수집은 여러 클래스에 걸쳐 일어나지만 로그는 한 줄기로 읽혀야 한다. 태그가 하나면
 * `adb logcat -s TigerCapture`로 우리 줄만 걸러낼 수 있다. 같은 프로세스에서 ARCore와 Camera2가
 * 각자의 태그로 쏟아내므로, pid로 거르는 것으로는 부족하다.
 *
 * 어느 한 클래스의 파일에 두지 않는다. 여럿이 공유하는 것을 한 클래스 옆에 두면 나머지가 그
 * 파일을 바라보게 된다.
 */
internal const val CAPTURE_LOG_TAG = "TigerCapture"
