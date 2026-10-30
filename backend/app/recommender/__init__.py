"""PawPath 개인화 추천 엔진.

DB와 웹 프레임워크에 의존하지 않는 순수 모듈이다. 입력을 받아 결과를 돌려줄 뿐이므로
단위 테스트로 모든 판단을 검증할 수 있다.

- types: 엔진 입출력 자료형
- features: 프로필 → 추천 특성값
- timeslots: 시간대 점수
- course_scoring: 코스 6개 항목 점수와 가중합
- preference: 피드백 온라인 학습
- explain: 계산 근거 기반 설명과 주의사항
- engine: 전체 파이프라인
"""
