"""프로젝트 공통 규칙: 철근 단위중량, 할증률, 수량 반올림."""
from __future__ import annotations

import re
from typing import Dict

# KS D 3504 단위중량(kg/m). 도면 재료표 값과 같은지는 감사 단계에서 다시 확인한다.
UNIT_WEIGHT: Dict[str, float] = {
    "S10": 0.560, "S13": 0.995, "S16": 1.560, "S19": 2.250, "S22": 3.040,
    "S25": 3.980, "S29": 5.040, "S32": 6.230, "S35": 7.510, "S38": 8.950,
    "S41": 10.500, "S51": 15.900,
}

PREMIUM_THRESHOLD_MM: int = 22  # 사용자 확정(2026-11-05): S22 이상 6%, S19 이하 3%
PREMIUM_LARGE: float = 0.06
PREMIUM_SMALL: float = 0.03


def bar_size(dia: str) -> int:
    """'S22' -> 22"""
    match = re.fullmatch(r"[A-Z](\d+)", dia)
    if not match:
        raise ValueError(f"철근 호칭 해석 불가: {dia}")
    return int(match.group(1))


# 원본 비교 판정 이름
STATE_LABEL = {"same": "일치", "same_assumed": "일치 (가정값 의존)", "diff": "차이", "missing": "원본에 없음", "no_original": "비교 안 함"}


def premium_rate(dia: str) -> float:
    """호칭경별 할증률."""
    return PREMIUM_LARGE if bar_size(dia) >= PREMIUM_THRESHOLD_MM else PREMIUM_SMALL


def round3(value: float) -> float:
    """산출서 관행(소수 3자리 반올림). 부동소수 경계값 보정을 포함한다."""
    return round(value + (1e-9 if value >= 0 else -1e-9), 3)


def same(a: float, b: float, tol: float = 0.0005) -> bool:
    return abs(a - b) <= tol
