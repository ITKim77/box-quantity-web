"""
변수 기반 수량 모델
1) 도면에서 읽은 값을 '입력 변수'로 등록한다. (cad_extracted.json)
2) 입력 변수로 '계산 변수'(평균 길이, 벽 안쪽 길이 등)를 구한다.
3) 모든 수량 행은 숫자가 아니라 변수식으로 쓴다. 예: 외곽폭*바닥두께*평균길이
값을 바꿔 다시 계산할 수 있도록 같은 구조를 html 계산 엔진과 xlsx 이름 정의가 그대로 쓴다.
산출서 값은 입력으로 쓰지 않는다. 도면에 없는 값만 ASSUMED로 사유와 함께 둔다.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.rules import UNIT_WEIGHT, premium_rate, round3

# 도면에 표기가 없는 입력. 코드에는 값을 두지 않는다. 사용자가 입력하거나, 기준 과업 값이 private/ 에 있으면 그 값을 쓴다.
# 원본 PDF를 읽어 자동으로 채우지 않는다. 그러면 비교가 자기 자신과의 비교가 된다.
UNTRACED: Dict[str, Dict[str, Any]] = {
    "contraction_count": {"value": None, "note": "블록별 수축이음 개소. 도면에 위치 치수 없음"},
    "wing_side_top": {"value": None, "note": "날개벽 유로폼 바깥 구간 폭. 도면 치수 표기 없음"},
    "scaffold_offset": {"value": None, "note": "본체 비계 높이 공제. 도면 표기 없음"},
    "wing_scaffold_h": {"value": None, "note": "날개벽 비계 높이. 도면 표기 없음"},
    "wing_scaffold_side": {"value": None, "note": "날개벽 비계 측면 폭. 도면 표기 없음"},
    "pvc_length": {"value": None, "note": "PVC 1개 길이. 도면 재료표는 범위만 표기"},
}
REFERENCE_ASSUMPTIONS = "private/assumptions_reference.json"
if os.path.exists(REFERENCE_ASSUMPTIONS):
    with open(REFERENCE_ASSUMPTIONS, encoding="utf-8") as _f:
        for _key, _value in json.load(_f).items():
            UNTRACED[_key]["value"] = _value
ASSUMPTION_FIELDS = {"contraction_count": "블록별 수축이음 개소 {B1, B2, B3}", "wing_side_top": "날개벽 유로폼 바깥 구간 폭(m)", "scaffold_offset": "본체 비계 높이 공제(m)",
                     "wing_scaffold_h": "날개벽 비계 높이(m)", "wing_scaffold_side": "날개벽 비계 측면 폭(m)", "pvc_length": "PVC 1개 길이(m)"}
BLOCK_PREFIX = {"B1": "블록1", "B2": "블록2", "B3": "블록3"}
LOC_CODE = {"시점좌": "SL", "시점우": "SR", "종점좌": "EL", "종점우": "ER"}
NAME_RE = re.compile(r"[가-힣A-Za-z_][가-힣A-Za-z0-9_]*")
FUNCS = {"sin", "cos", "tan", "sqrt", "abs", "sign"}


def apply_assumptions(path: str) -> None:
    """사용자가 정한 가정값을 넣는다. 빠진 값이 있으면 이유를 알려 주고 멈춘다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    absent = [f"{k} ({v})" for k, v in ASSUMPTION_FIELDS.items() if k not in data]
    if absent:
        raise ValueError("가정값 파일에 빠진 항목: " + ", ".join(absent))
    for key in ASSUMPTION_FIELDS:
        UNTRACED[key]["value"] = data[key]
        UNTRACED[key]["note"] = f"{ASSUMPTION_FIELDS[key]}. 도면 표기 없음, 사용자 입력값"


def scope_code(scope: str) -> str:
    return LOC_CODE[scope[3:]] if scope.startswith("WW-") else scope


def fmt_var(value: float, digits: int) -> str:
    """digits=-4: 소수 넷째 자리까지 쓰되 끝의 0은 하나 지운다."""
    if digits == -4:
        text = f"{value:.4f}"
        return text[:-1] if text.endswith("0") else text
    return f"{value:.{digits}f}"


class Engine:
    """변수와 수식을 계산한다. html 계산 엔진과 같은 규칙을 쓴다."""

    def __init__(self) -> None:
        self.vars: List[Dict[str, Any]] = []
        self.env: Dict[str, float] = {}
        self.digits: Dict[str, int] = {}

    def lookup(self, name: str, scope: Optional[str], prefix: Optional[str]) -> str:
        for candidate in ([f"{scope}|{name}"] if scope else []) + ([f"{prefix}_{name}"] if prefix else []) + [name]:
            if candidate in self.env:
                return candidate
        raise KeyError(f"변수 없음: {name} (scope={scope}, prefix={prefix})")

    def ev(self, formula: str, scope: Optional[str] = None, prefix: Optional[str] = None) -> float:
        def repl(match: re.Match[str]) -> str:
            name = match.group(0)
            return name if name in FUNCS else repr(self.env[self.lookup(name, scope, prefix)])

        code = NAME_RE.sub(repl, formula).replace("^", "**")
        env = {"sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d)), "tan": lambda d: math.tan(math.radians(d)),
               "sqrt": math.sqrt, "abs": abs, "sign": lambda v: 0.0 if abs(v) < 0.0005 else (1.0 if v > 0 else -1.0)}
        return float(eval(code, {"__builtins__": {}}, env))  # noqa: S307 - 내부 생성 수식

    def numeric(self, formula: str, scope: Optional[str] = None, prefix: Optional[str] = None) -> str:
        """변수를 값으로 바꾼 식 (화면 표시용)"""
        def repl(match: re.Match[str]) -> str:
            name = match.group(0)
            if name in FUNCS:
                return name
            key = self.lookup(name, scope, prefix)
            return fmt_var(self.env[key], self.digits.get(key, 3))

        return NAME_RE.sub(repl, formula)

    def inp(self, name: str, label: str, value: float, source: str, kind: str = "drawing", unit: str = "m", digits: int = 3, prefix: Optional[str] = None) -> None:
        full = f"{prefix}_{name}" if prefix else name
        self.env[full] = float(value)
        self.digits[full] = digits
        self.vars.append({"name": full, "local": name, "prefix": prefix, "label": label, "value": float(value), "unit": unit, "kind": kind, "digits": digits, "source": source, "formula": None, "rnd": None})

    def der(self, name: str, label: str, formula: str, rnd: Optional[int] = 3, unit: str = "m", digits: int = 3, prefix: Optional[str] = None) -> None:
        full = f"{prefix}_{name}" if prefix else name
        value = self.ev(formula, None, prefix)
        value = round3(value) if rnd == 3 else (round(value + 1e-12, rnd) if rnd else value)
        self.env[full] = value
        self.digits[full] = digits
        self.vars.append({"name": full, "local": name, "prefix": prefix, "label": label, "value": value, "unit": unit, "kind": "derived", "digits": digits, "source": "", "formula": formula, "rnd": rnd})


class Book:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.lines: List[Dict[str, Any]] = []

    def add(self, scope: str, prefix: str, key: str, element: str, desc: str, formula: str, sheets: List[str], name: Optional[str] = None, accum: Optional[str] = None) -> float:
        e = self.engine
        value = round3(e.ev(formula, scope, prefix))
        n = sum(1 for l in self.lines if l["scope"] == scope and l["key"] == key) + 1
        self.lines.append({"id": f"{scope}.{key}.{n:02d}", "scope": scope, "prefix": prefix, "key": key, "element": element, "desc": desc, "formula": formula,
                           "expr": e.numeric(formula, scope, prefix), "value": value, "sheets": sheets, "name": name, "accum": accum})
        if name:
            e.env[f"{scope}|{name}"] = value
        if accum:
            e.env[f"{scope}|{accum}"] = round3(e.env.get(f"{scope}|{accum}", 0.0) + value)
        return value


def register_global_vars(e: Engine, cad: Dict[str, Any]) -> None:
    sec, plan, misc = cad["section"], cad["plan"], cad["misc"]
    src = "일반도(1) 표준단면도 · 콘크리트 선 실측"
    for name, label, field in [("외곽폭", "암거 바깥 폭", "total_width_mm"), ("외곽높이", "암거 바깥 높이", "total_height_mm"), ("안쪽폭", "안쪽 빈 공간 폭", "inner_width_mm"), ("안쪽높이", "안쪽 빈 공간 높이", "inner_height_mm"),
                               ("천장두께", "천장판(상부 슬래브) 두께", "top_slab_t_mm"), ("바닥두께", "바닥판(하부 슬래브) 두께", "bot_slab_t_mm"), ("벽두께", "옆벽 두께", "wall_t_mm"),
                               ("헌치가로", "모서리 삼각형 가로", "haunch_w_mm"), ("헌치세로", "모서리 삼각형 세로", "haunch_h_mm"), ("버림폭", "버림콘크리트 폭", "lean_width_mm"), ("버림두께", "버림콘크리트 두께", "lean_t_mm")]:
        e.inp(name, label, sec[field] / 1000, src)
    e.inp("사각", "블록 끝이 비스듬한 각도", plan["skew_deg"], "일반도(1) 평면도 · 각도 문자", unit="°", digits=0)
    for name, rec in cad["anchored_dims"].items():
        e.inp(name, rec["label"], rec["value_m"], f"{rec['sheet'].replace(' ', '')} {rec['heading']} · 치수 문자")
    dowel, drain, fabric = misc["dowel"], misc["drain_pipe"], misc["filter_fabric"]
    e.inp("다웰간격", "다웰바 간격", dowel["ctc_mm"] / 1000, "일반도(1) 시공이음 상세 · 문자")
    e.inp("배수관개수", "날개벽 1곳의 배수관 수", drain["ea_per_location"], "일반도(2) 배수상세 재료표", unit="개", digits=0)
    e.inp("부직포가로", "부직포 가로", fabric["w_mm"] / 1000, "일반도(2) 배수상세 재료표")
    e.inp("부직포세로", "부직포 세로", fabric["h_mm"] / 1000, "일반도(2) 배수상세 재료표")
    e.inp("부직포장수", "날개벽 1곳의 부직포 수", fabric["ea_per_location"], "일반도(2) 배수상세 재료표", unit="장", digits=0)
    u = UNTRACED
    e.inp("비계공제", "본체 비계 높이에서 빼는 값", u["scaffold_offset"]["value"], u["scaffold_offset"]["note"], kind="assumed")
    e.inp("날개비계높이", "날개벽 비계 높이", u["wing_scaffold_h"]["value"], u["wing_scaffold_h"]["note"], kind="assumed")
    e.inp("날개비계측면", "날개벽 비계 옆쪽 폭", u["wing_scaffold_side"]["value"], u["wing_scaffold_side"]["note"], kind="assumed")
    e.inp("날개외측폭", "날개벽 거푸집 바깥 구간 폭", u["wing_side_top"]["value"], u["wing_side_top"]["note"], kind="assumed")
    e.inp("PVC길이", "배수관 1개 길이", u["pvc_length"]["value"], u["pvc_length"]["note"], kind="assumed")

    # 계산 변수
    e.der("벽안높이", "벽 안쪽 높이 (삼각형 아래)", "안쪽높이-헌치세로")
    e.der("천장밑폭", "천장 밑면 폭 (삼각형 사이)", "안쪽폭-2*헌치가로")
    e.der("빗면", "삼각형 빗변 길이", "sqrt(헌치가로^2+헌치세로^2)")
    e.der("단면넓이", "암거 단면 넓이", "외곽폭*외곽높이-안쪽폭*안쪽높이+2*(헌치가로*헌치세로/2)", rnd=None, unit="㎡", digits=4)
    e.der("미터당거푸집", "길이 1m에 필요한 거푸집 넓이", "외곽높이*2+벽안높이*2+천장밑폭+빗면*2", rnd=None, unit="㎡")
    e.der("지수판가로", "지수판 가로 (벽 가운데끼리)", "외곽폭-벽두께")
    e.der("지수판세로", "지수판 세로 (판 가운데끼리)", "외곽높이-천장두께/2-바닥두께/2")
    e.der("줄눈높이", "수축이음 벽 높이", "안쪽높이+천장두께")
    e.der("버림여유", "버림이 본체보다 나오는 폭 (한쪽)", "(버림폭-외곽폭)/2")
    e.der("기울기", "비스듬한 정도 (폭 1m당 길이 차)", "tan(사각-90)", rnd=None, unit="", digits=4)
    e.der("코사인", "비스듬한 끝의 폭 환산값", "cos(사각-90)", rnd=None, unit="", digits=4)
    e.der("사각폭", "비스듬한 끝의 폭", "외곽폭/코사인")
    e.der("사각벽", "비스듬한 끝의 벽 두께", "벽두께/코사인")
    e.der("사각버림폭", "비스듬한 끝의 버림 폭", "버림폭/코사인")
    e.der("경사빗길이", "날개벽 경사면 길이", "sqrt(날개경사길이^2+날개아래높이^2)")


def register_block(e: Engine, cad: Dict[str, Any], name: str) -> None:
    rec = cad["plan"]["blocks"][name]
    p = BLOCK_PREFIX[name]
    n = name[1]
    source = "일반도(1) 평면도 · 치수 문자"
    e.inp("왼쪽길이", f"Block {n} 왼쪽 길이", rec["left"], source, prefix=p)
    e.inp("오른쪽길이", f"Block {n} 오른쪽 길이", rec["right"], source, prefix=p)
    count = UNTRACED["contraction_count"]
    e.inp("수축이음개소", f"Block {n} 수축이음 개소", count["value"][name], count["note"], kind="assumed", unit="곳", digits=0, prefix=p)
    D = lambda nm, lab, f, **kw: e.der(nm, f"Block {n} {lab}", f, prefix=p, **kw)  # noqa: E731
    D("평균길이", "평균 길이", "(왼쪽길이+오른쪽길이)/2", rnd=None, digits=-4)
    D("사각부호", "긴 쪽 표시 (왼쪽 1, 오른쪽 −1, 같음 0)", "sign(왼쪽길이-오른쪽길이)", rnd=None, unit="", digits=0)
    D("왼쪽안길이", "왼쪽 벽 안쪽 길이", "왼쪽길이-사각부호*벽두께*기울기")
    D("오른쪽안길이", "오른쪽 벽 안쪽 길이", "오른쪽길이+사각부호*벽두께*기울기")
    D("왼쪽벽평균", "왼쪽 벽 평균 길이", "(왼쪽길이+왼쪽안길이)/2", rnd=None, digits=-4)
    D("오른쪽벽평균", "오른쪽 벽 평균 길이", "(오른쪽길이+오른쪽안길이)/2", rnd=None, digits=-4)
    D("안길이평균", "벽 안쪽 평균 길이", "(왼쪽안길이+오른쪽안길이)/2", rnd=None, digits=-4)
    D("왼쪽밑길이", "천장 밑면 왼쪽 길이", "왼쪽길이-사각부호*(벽두께+헌치가로)*기울기")
    D("오른쪽밑길이", "천장 밑면 오른쪽 길이", "오른쪽길이+사각부호*(벽두께+헌치가로)*기울기")
    D("밑면평균", "천장 밑면 평균 길이", "(왼쪽밑길이+오른쪽밑길이)/2", rnd=None, digits=-4)
    D("왼쪽버림길이", "버림 왼쪽 길이", "왼쪽길이+abs(사각부호)*버림여유+사각부호*버림여유*기울기")
    D("오른쪽버림길이", "버림 오른쪽 길이", "오른쪽길이+abs(사각부호)*버림여유-사각부호*버림여유*기울기")
    D("버림평균", "버림 평균 길이", "(왼쪽버림길이+오른쪽버림길이)/2", rnd=None, digits=-4)
    # 비스듬한 끝: Block 1은 시점 쪽, Block 3은 종점 쪽 (평면도)
    start_skew, end_skew = name == "B1", name == "B3"
    D("시점끝폭", "시작 쪽 끝 폭", "사각폭" if start_skew else "외곽폭")
    D("시점끝벽", "시작 쪽 끝 벽 두께", "사각벽" if start_skew else "벽두께")
    D("시점버림폭", "시작 쪽 버림 폭", "사각버림폭" if start_skew else "버림폭")
    D("종점끝폭", "끝 쪽 끝 폭", "사각폭" if end_skew else "외곽폭")
    D("종점끝벽", "끝 쪽 끝 벽 두께", "사각벽" if end_skew else "벽두께")
    D("종점버림폭", "끝 쪽 버림 폭", "사각버림폭" if end_skew else "버림폭")


def build_body(book: Book, cad: Dict[str, Any], name: str) -> None:
    prefix = BLOCK_PREFIX[name]
    skewed = abs(cad["plan"]["blocks"][name]["left"] - cad["plan"]["blocks"][name]["right"]) > 0.001
    sheets = [k for k, v in cad["sheets"].items() if v["block"] == name] + ["일반도 (1)"]

    def A(key: str, el: str, desc: str, formula: str, line_name: Optional[str] = None, accum: Optional[str] = None) -> None:
        book.add(name, prefix, key, f"{name}-{el}" if el else name, desc, formula, sheets, line_name, accum)

    A("concrete", "SLAB-BOT", "① 하부슬래브", "외곽폭*바닥두께*평균길이")
    A("concrete", "SLAB-TOP", "② 상부슬래브", "외곽폭*천장두께*평균길이")
    A("concrete", "WALL-L", "③ 좌측벽", "벽두께*안쪽높이*왼쪽벽평균")
    A("concrete", "WALL-R", "④ 우측벽", "벽두께*안쪽높이*오른쪽벽평균")
    A("concrete", "HAUNCH-L", "⑤ 상부 좌측 헌치", "(헌치가로*헌치세로/2)*왼쪽안길이")
    A("concrete", "HAUNCH-R", "⑥ 상부 우측 헌치", "(헌치가로*헌치세로/2)*오른쪽안길이")
    if skewed:
        A("concrete", "PARAPET", "⑦ 난간벽", "난간벽폭*난간벽높이*사각폭")
    A("lean", "LEAN", "버림콘크리트", "버림폭*버림두께*버림평균")

    F = lambda el, desc, formula, line_name=None: A("form_normal", el, desc, formula, line_name, "거푸집합계")  # noqa: E731
    F("SLAB-BOT", "① 하부슬래브 측면", "바닥두께*평균길이*2")
    F("SLAB-TOP", "② 상부슬래브 하면", "천장밑폭*밑면평균", "천장밑면넓이")
    F("SLAB-TOP", "② 상부슬래브 측면", "천장두께*평균길이*2")
    F("WALL-L", "③ 좌측벽 내측면", "벽안높이*왼쪽길이")
    F("WALL-L", "③ 좌측벽 외측면", "안쪽높이*왼쪽길이")
    F("WALL-R", "④ 우측벽 내측면", "벽안높이*오른쪽길이")
    F("WALL-R", "④ 우측벽 외측면", "안쪽높이*오른쪽길이")
    F("HAUNCH-L", "⑤ 좌측 헌치 경사면", "빗면*왼쪽안길이", "왼쪽빗면넓이")
    F("HAUNCH-R", "⑥ 우측 헌치 경사면", "빗면*오른쪽안길이", "오른쪽빗면넓이")
    if skewed:
        F("PARAPET", "⑦ 난간벽 측면", "(난간벽높이*사각폭)*2")
        F("PARAPET", "⑦ 난간벽 마구리", "(난간벽폭*난간벽높이)*2")
    F("END-S", "마감거푸집 시점면", "시점끝폭*천장두께+시점끝폭*바닥두께+(시점끝벽*안쪽높이)*2+(헌치가로*헌치세로/2)*2")
    F("END-E", "마감거푸집 종점면", "종점끝폭*천장두께+종점끝폭*바닥두께+(종점끝벽*안쪽높이)*2+(헌치가로*헌치세로/2)*2")

    A("form_simple", "LEAN", "버림 시·종점면", "(버림두께*시점버림폭)+(버림두께*종점버림폭)")
    A("form_simple", "LEAN", "버림 측면", "(버림두께*왼쪽버림길이)+(버림두께*오른쪽버림길이)")
    A("shoring", "INNER", "시스템동바리", "안쪽폭*안쪽높이*안길이평균")
    A("scaffold", "WALL-R", "우측", "(외곽높이-비계공제)*오른쪽안길이")
    A("scaffold", "WALL-L", "좌측", "(외곽높이-비계공제)*왼쪽안길이")
    A("spacer_wall", "", "벽체용 = 거푸집 합계 − 천장 밑면 − 빗면 2개", "거푸집합계-천장밑면넓이-왼쪽빗면넓이-오른쪽빗면넓이")
    A("spacer_slab", "SLAB-TOP", "슬래브 하면·헌치", "천장밑면넓이+왼쪽빗면넓이+오른쪽빗면넓이")
    A("spacer_slab", "SLAB-BOT", "슬래브 및 기초", "외곽폭*평균길이")
    A("joint_clean", "WALL-L", "좌측벽", "(벽두께*왼쪽벽평균)*2")
    A("joint_clean", "WALL-R", "우측벽", "(벽두께*오른쪽벽평균)*2")
    A("swell", "WALL-L", "좌측벽", "왼쪽벽평균*2")
    A("swell", "WALL-R", "우측벽", "오른쪽벽평균*2")

    if name in ("B2", "B3"):  # 신축이음은 B1-B2, B2-B3 이음. 수량은 뒤쪽 블록에 계상
        J = lambda key, desc, formula: A(key, "JOINT", desc, formula)  # noqa: E731
        J("dowel", "다웰바 하부슬래브", "외곽폭/다웰간격")
        J("waterstop", "지수판(단면 중심선)", "지수판가로+지수판가로+지수판세로+지수판세로")
        J("sealant", "외측(저면 제외 3변)", "외곽폭+외곽높이+외곽높이")
        J("sealant", "내측(헌치 반영 실둘레)", "안쪽폭+천장밑폭+벽안높이+벽안높이+빗면+빗면")
        J("styrofoam", "상부슬래브", "외곽폭*천장두께")
        J("styrofoam", "하부슬래브", "외곽폭*바닥두께")
        J("styrofoam", "벽체", "(벽두께*안쪽높이)*2")
        J("styrofoam", "헌치", "(헌치가로*헌치세로/2)*2")
        J("rain_wall", "우수유입방지벽", "((방지벽폭*방지벽높이)*외곽폭)*2")

    A("waterproof", "SLAB-TOP", "상면", "외곽폭*평균길이")
    A("waterproof", "WALL-R", "우측면", "외곽높이*오른쪽길이")
    A("waterproof", "WALL-L", "좌측면", "외곽높이*왼쪽길이")
    A("curing", "SLAB-TOP", "상면(방수 상면과 동일)", "외곽폭*평균길이")
    A("contraction", "", "수축이음", "(줄눈높이*2+외곽폭)*수축이음개소")


def wing_groups(cad: Dict[str, Any]) -> List[Tuple[int, List[str], str]]:
    out: List[Tuple[int, List[str], str]] = []
    for sched in cad["rebar"].values():
        if sched["block"] == "WW":
            out.append((int(sched["wing_angle_deg"]), sched["wing_locations"], sched["sheet"]))
    return sorted(out, reverse=True)


def register_wing(e: Engine, cad: Dict[str, Any]) -> None:
    for angle, locs, sheet in wing_groups(cad):
        p = f"날개{angle}"
        e.inp("날개각", f"{'·'.join(locs)} 날개벽이 본체와 이루는 각도", angle, f"{sheet.replace(' ', '')} 철근 상세 · 각도 문자", unit="°", digits=0, prefix=p)
        D = lambda nm, lab, f, **kw: e.der(nm, f"{angle}° 날개벽 {lab}", f, prefix=p, **kw)  # noqa: E731
        D("두께차크기", "두께 때문에 생기는 길이 차", "날개두께*기울기")
        D("두께차", "뒷면이 앞면보다 긴 길이 (짧으면 −)", "두께차크기*sign(날개각-90)")
        D("뒷길이", "뒷면 길이", "날개전체길이+두께차")
        D("뒷아래길이", "뒷면 아래쪽 길이", "날개평평길이+두께차")
        D("뒤빗면", "뒷면 모서리 삼각형 빗변", "sqrt(날개두께^2+날개두께^2-2*날개두께*날개두께*cos(날개각))", rnd=4, digits=4)
        D("비계뒤길이", "뒤쪽 비계 길이", "뒷길이-날개두께")


def build_wing(book: Book, cad: Dict[str, Any]) -> None:
    for angle, locs, sheet in wing_groups(cad):
        prefix = f"날개{angle}"
        for loc in locs:
            scope = f"WW-{loc}"
            el = f"WW-{LOC_CODE[loc]}"
            sheets = [sheet, "일반도 (2)"]

            def A(key: str, desc: str, formula: str, accum: Optional[str] = None) -> None:
                book.add(scope, prefix, key, el, desc, formula, sheets, None, accum)

            A("concrete", "본체", "(날개끝높이+날개전체높이)/2*날개경사길이*날개두께+날개전체높이*날개평평길이*날개두께")
            A("concrete", "헌치", "sin(날개각)/2*날개두께*날개두께*날개전체높이")
            for desc, formula in [("배면 경사부", "(뒷길이+뒷아래길이)/2*날개아래높이"), ("배면 상단부", "뒷길이*날개끝높이"), ("배면 헌치", "뒤빗면*날개전체높이"),
                                  ("외측 경사면", "날개두께*경사빗길이"), ("외측 바깥구간", "날개외측폭*날개끝높이"), ("외측 수직면", "날개전체길이*날개끝높이"), ("외측 수직면(단부)", "날개두께*날개끝높이"),
                                  ("전면 상단부", "날개전체길이*날개끝높이"), ("전면 경사부", "(날개전체길이+날개평평길이)/2*날개아래높이"), ("하면", "날개두께*날개평평길이")]:
                A("form_normal", desc, formula, "거푸집합계")
            A("shoring", "내측 수평구간", "날개평평길이*날개받침높이*날개두께")
            A("shoring", "외측 경사구간", "날개경사길이*(날개받침높이+날개아래높이)/2*날개두께")
            A("scaffold", "배면", "비계뒤길이*날개비계높이")
            A("scaffold", "전면", "날개전체길이*날개비계높이")
            A("scaffold", "측면", "날개비계측면*날개비계높이")
            A("spacer_wall", "벽체용 = 거푸집 합계", "거푸집합계")
            A("waterproof", "배면 상단+경사부(거푸집 배면과 동일)", "뒷길이*날개끝높이+(뒷길이+뒷아래길이)/2*날개아래높이")
            A("waterproof", "배면 헌치", "뒤빗면*날개전체높이")
            A("pvc", "PVC 배수관", "PVC길이*배수관개수")
            A("fabric", "부직포", "부직포가로*부직포세로*부직포장수")


def sheet_code(sheet: str) -> str:
    return sheet.replace(" ", "").replace("(", "").replace(")", "")


def build_rebar(e: Engine, cad: Dict[str, Any]) -> Dict[str, Any]:
    """재료표 행이 입력 변수다. 총길이 × 1m 무게로 재계산하고 할증은 호칭경 규칙으로 판정한다."""
    dias = sorted({b["dia"] for s in cad["rebar"].values() for b in s["bars"]}, key=lambda d: -int(d[1:]))
    for dia in dias:
        e.inp(f"무게_{dia}", f"{dia} 철근 1m 무게", UNIT_WEIGHT[dia], "KS D 3504 (도면 재료표 값과 일치 확인)", kind="rule", unit="kg/m")
        e.inp(f"할증_{dia}", f"{dia} 철근 할증률", premium_rate(dia), "S22 이상 6%, S19 이하 3% (2026-11-05 확정)", kind="rule", unit="", digits=2)
    bars: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    for sheet, sched in cad["rebar"].items():
        code = sheet_code(sheet)
        scopes = [f"WW-{loc}" for loc in sched["wing_locations"]] if sched["block"] == "WW" else [sched["block"]]
        by_dia: Dict[str, float] = {}
        for bar in sched["bars"]:
            by_dia[bar["dia"]] = by_dia.get(bar["dia"], 0.0) + bar["length_m"] * bar["count"]
            bars.append({"sheet": sheet, "code": code, "mark": bar["mark"], "dia": bar["dia"], "L": bar["length_m"], "N": bar["count"]})
        for dia, length in by_dia.items():
            var = f"총길이_{code}_{dia}"
            e.env[var] = length
            e.digits[var] = 3
            net_f = f"{var}*무게_{dia}/1000"
            gross_f = f"{var}*무게_{dia}/1000*(1+할증_{dia})"
            for scope in scopes:
                records.append({"scope": scope, "dia": dia, "length_m": round3(length), "unit_weight": UNIT_WEIGHT[dia], "net_t": round3(e.ev(net_f)), "rate": premium_rate(dia),
                                "gross_t": round3(e.ev(gross_f)), "sheet": sheet, "net_formula": net_f, "gross_formula": gross_f, "net_expr": e.numeric(net_f), "gross_expr": e.numeric(gross_f)})
    return {"records": records, "bars": bars}


def compute_totals(e: Engine, lines: List[Dict[str, Any]], rebar: Dict[str, Any]) -> Dict[str, Any]:
    totals: Dict[str, Dict[str, float]] = {}
    for line in lines:
        totals.setdefault(line["key"], {})
        totals[line["key"]][line["scope"]] = round3(totals[line["key"]].get(line["scope"], 0.0) + line["value"])
    totals["pump"] = dict(totals["concrete"])
    totals["plain_pour"] = dict(totals["lean"])
    totals["H13"], totals["H16_25"] = {}, {}
    for rec in rebar["records"]:
        key = "H13" if rec["dia"] == "S13" else "H16_25"
        totals[key][rec["scope"]] = round3(totals[key].get(rec["scope"], 0.0) + rec["net_t"])
    grand = {key: round3(sum(vals.values())) for key, vals in totals.items()}
    rebar["net_total_t"] = round3(sum(r["net_t"] for r in rebar["records"]))
    rebar["gross_total_t"] = round3(sum(r["gross_t"] for r in rebar["records"]))
    by_dia: Dict[str, Dict[str, float]] = {}
    for rec in rebar["records"]:
        slot = by_dia.setdefault(rec["dia"], {"net_t": 0.0, "gross_t": 0.0, "rate": rec["rate"]})
        slot["net_t"] = round3(slot["net_t"] + rec["net_t"])
        slot["gross_t"] = round3(slot["gross_t"] + rec["gross_t"])
    rebar["by_dia"] = by_dia
    e.env["철근총_net"] = rebar["net_total_t"]
    e.env["철근총_gross"] = rebar["gross_total_t"]
    for dia, slot in by_dia.items():
        e.env[f"철근_{dia}_net"] = slot["net_t"]
        e.env[f"철근_{dia}_gross"] = slot["gross_t"]
    # 화면 합계용 전역 변수
    for key, vals in totals.items():
        for scope, value in vals.items():
            e.env[f"합_{scope_code(scope)}_{key}"] = value
        wing = [v for s, v in vals.items() if s.startswith("WW-")]
        if wing:
            e.env[f"군_날개벽_{key}"] = round3(sum(wing))
        e.env[f"총_{key}"] = grand[key]
    return {"totals": totals, "grand": grand}


def trace_dependencies(variables: List[Dict[str, Any]], lines: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """산출 행마다 어떤 입력 변수(도면, 가정, 규칙)에 기대는지 수식을 거슬러 찾는다. 줄에 deps를 달고 변수별 사용처를 돌려준다."""
    deps: Dict[str, set] = {}
    for var in variables:
        if not var["formula"]:
            deps[var["name"]] = {var["name"]}
            continue
        found: set = set()
        for token in NAME_RE.findall(var["formula"]):
            if token in FUNCS:
                continue
            found |= deps.get(f"{var['prefix']}_{token}", deps.get(token, set()))
        deps[var["name"]] = found
    scoped: Dict[str, set] = {}
    usage: Dict[str, Dict[str, Any]] = {v["name"]: {"keys": [], "lines": 0, "body": False} for v in variables if not v["formula"]}
    for line in lines:
        found = set()
        for token in NAME_RE.findall(line["formula"]):
            if token in FUNCS:
                continue
            found |= scoped.get(f"{line['scope']}|{token}", deps.get(f"{line['prefix']}_{token}", deps.get(token, set())))
        line["deps"] = sorted(found)
        for field in ("name", "accum"):
            if line.get(field):
                key = f"{line['scope']}|{line[field]}"
                scoped[key] = scoped.get(key, set()) | found
        for name in found:
            usage[name]["lines"] += 1
            usage[name]["body"] = usage[name]["body"] or not line["scope"].startswith("WW-")
            if line["key"] not in usage[name]["keys"]:
                usage[name]["keys"].append(line["key"])
    return usage


def build_model(cad: Dict[str, Any], overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """overrides는 시험용. 도면을 고치지 않고 입력 변수만 바꿔 계산한다(html·xlsx와 대조)."""
    engine = Engine()
    if overrides:
        original_inp = engine.inp

        def patched(name: str, label: str, value: float, source: str, kind: str = "drawing", unit: str = "m", digits: int = 3, prefix: Optional[str] = None) -> None:
            full = f"{prefix}_{name}" if prefix else name
            original_inp(name, label, overrides.get(full, value), source, kind, unit, digits, prefix)

        engine.inp = patched  # type: ignore[method-assign]
    register_global_vars(engine, cad)
    for name in BLOCK_PREFIX:
        register_block(engine, cad, name)
    register_wing(engine, cad)
    book = Book(engine)
    for name in BLOCK_PREFIX:
        build_body(book, cad, name)
    build_wing(book, cad)
    rebar = build_rebar(engine, cad)
    result = compute_totals(engine, book.lines, rebar)
    env_public = {k: v for k, v in engine.env.items() if "|" not in k}
    return {"variables": engine.vars, "lines": book.lines, "scope_totals": result["totals"], "grand_totals": result["grand"], "rebar": rebar,
            "env": env_public, "digits": engine.digits, "untraced_inputs": UNTRACED, "var_usage": trace_dependencies(engine.vars, book.lines), "pvc_dia_mm": cad["misc"]["drain_pipe"]["dia_mm"], "pvc_spec": cad["misc"]["drain_pipe"]["spec"]}


class QuantityModelAgent:
    def __init__(self, cad_path: str = "data/cad_extracted.json", output_path: str = "data/quantity_model.json", assumptions_path: str = "") -> None:
        self.cad_path = cad_path
        self.output_path = output_path
        self.assumptions_path = assumptions_path

    def run(self) -> Dict[str, Any]:
        with open(self.cad_path, encoding="utf-8") as f:
            cad = json.load(f)
        if self.assumptions_path:
            apply_assumptions(self.assumptions_path)
        model = build_model(cad)
        model["assumptions_from"] = "user" if self.assumptions_path else "reference"
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as out:
            json.dump(model, out, ensure_ascii=False, indent=1)
        return model


if __name__ == "__main__":
    result = QuantityModelAgent().run()
    kinds: Dict[str, int] = {}
    for v in result["variables"]:
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    print(len(result["lines"]), kinds, result["grand_totals"], result["rebar"]["net_total_t"], result["rebar"]["gross_total_t"])
