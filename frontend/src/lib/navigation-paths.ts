/** 로그인이나 프로필 설정 뒤 돌아갈 앱 안의 경로만 받는다. 다른 사이트 주소는 홈으로 바꾼다. */
export function safeNext(path: string | null | undefined, fallback = '/'): string {
  if (!path || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return fallback;
  // 프로필 화면으로 돌아오면 다시 고르게 되므로 홈으로 보낸다.
  return path.startsWith('/profiles') ? fallback : path;
}
