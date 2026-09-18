package com.ssafy.s15p21a206.tiger.ui.upload

/**
 * 앱이 백그라운드로 가면 진행 중인 전송을 끊을지 정한다.
 *
 * 백그라운드 업로드는 하지 않기로 한 계약이다. 판정 기준이 "업로드 상태 화면에 있는가"였으나 그
 * 화면을 없앴다. 전송은 이제 세션 상세에서 돌므로, 어느 화면에 있든 전송이 진행 중이면 끊고
 * `FAILED`로 남긴다. 사용자는 상세에서 다시 건다.
 */
internal fun cancelUploadOnStop(uploadInFlight: Boolean): Boolean = uploadInFlight
