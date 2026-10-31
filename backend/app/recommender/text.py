"""화면 문장에 쓰는 공통 표현."""


def hour_label(hour: int) -> str:
    if hour == 0:
        return "자정"
    if hour == 12:
        return "낮 12시"
    if hour < 12:
        return f"오전 {hour}시"
    return f"오후 {hour - 12}시"
