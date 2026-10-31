import { Component, type ReactNode } from 'react';

/** 화면 오류가 나도 빈 화면으로 끝나지 않게 하고, 홈으로 돌아갈 길을 준다. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-3 p-6 text-center" role="alert">
        <p className="text-lg font-bold text-ink">화면을 표시하다 문제가 생겼어요</p>
        <p className="text-sm text-ink-soft">기록된 산책과 피드백은 그대로 있어요. 홈에서 다시 시작해 주세요.</p>
        <a href="/" className="inline-flex min-h-12 items-center justify-center rounded-lg bg-mango-500 px-6 text-sm font-bold text-ink">
          홈으로 가기
        </a>
      </main>
    );
  }
}
