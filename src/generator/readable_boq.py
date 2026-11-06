"""
대안 수량산출서 본문(HTML)
도면에서 읽을 수 있는 값은 변수로 쓴다. 표 왼쪽에 변수식, 오른쪽에 도면 값을 넣은 계산을 보여 준다.
원본 산출서가 있으면 맨 앞에 비교 결과를 보여 주고, 없으면 도면 산출 결과만 보여 준다.
글자색: 붉은색은 입력값을 받는 칸(문서에서 그 값이 처음 나오는 곳) 한 곳뿐이다. 이후 인용과 계산은 파란색, 가정값과 규칙은 검은색이다.
여러 공종에 쓰는 입력값은 앞쪽 공통 표에, 나머지는 처음 쓰는 공종 안에 둔다.
웹 화면용(frozen=False): 변수표의 값을 바꾸면 페이지 안의 계산 엔진이 전 공종을 다시 계산한다. 엔진은 파이썬 모델과 같은 규칙이며,
tests/test_parametric.py가 두 결과를 대조한다.
내려받는 파일용(frozen=True): 입력칸과 스크립트가 없어 값을 고칠 수 없고, 확인 사항, 검산, 설명, 원본 비교를 싣지 않는다.
수량 숫자를 이 파일에 직접 적지 않는다. 그림은 도면 실측 치수로 축척에 맞춰 그린다. (평면도의 날개벽만 개략)
"""
from __future__ import annotations

import html
import json
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

BODY = ["B1", "B2", "B3"]
BODY_NAME = {"B1": "Block 1", "B2": "Block 2", "B3": "Block 3"}
LOC_CODE = {"시점좌": "SL", "시점우": "SR", "종점좌": "EL", "종점우": "ER"}
NAME_RE = re.compile(r"[가-힣A-Za-z_][가-힣A-Za-z0-9_]*")
FUNCS = {"sin", "cos", "tan", "sqrt", "abs", "sign", "ceil"}
TOKEN_RE = re.compile(r"[가-힣A-Za-z_][가-힣A-Za-z0-9_]*|\d+(?:\.\d+)?")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
# 입력칸의 글자색: i = 붉은색(도면에서 읽어 입력), a = 검은색(도면에 없는 가정값·규칙)
INPUT_CLASS = {"drawing": "i", "assumed": "a", "rule": "a"}
# 인용하는 곳의 글자색: c = 파란색, a = 검은색. 붉은색은 입력칸에만 쓴다.
CITE_CLASS = {"drawing": "c", "assumed": "a", "rule": "a", "derived": "c"}
# 공통 입력값 기준: 본체에도 쓰이고 공종 4개 이상에 쓰인다. 날개벽에만 쓰는 값은 날개벽 앞에 둔다.
COMMON_MIN_KEYS = 4
# 문서에 나오는 공종 순서 (공종 키 -> 카드)
CARD_ORDER = ["concrete", "lean", "form", "form-simple", "shoring", "scaffold", "spacer", "waterproof", "joint", "construction-joint", "drain"]
CARD_OF_KEY = {"concrete": "concrete", "lean": "lean", "form_normal": "form", "form_simple": "form-simple", "shoring": "shoring", "scaffold": "scaffold", "spacer_wall": "spacer", "spacer_slab": "spacer",
               "waterproof": "waterproof", "curing": "waterproof", "sealant": "joint", "styrofoam": "joint", "waterstop": "joint", "rain_wall": "joint", "dowel": "joint",
               "joint_clean": "construction-joint", "swell": "construction-joint", "contraction": "construction-joint", "pvc": "drain", "fabric": "drain"}
STATE_ORDER = {"diff": 0, "missing": 1, "same_assumed": 2, "same": 3, "no_original": 4}

FRIENDLY: Dict[str, str] = {
    "① 하부슬래브": "① 바닥판", "② 상부슬래브": "② 천장판", "③ 좌측벽": "③ 왼쪽 벽", "④ 우측벽": "④ 오른쪽 벽",
    "⑤ 상부 좌측 헌치": "⑤ 왼쪽 모서리 삼각형", "⑥ 상부 우측 헌치": "⑥ 오른쪽 모서리 삼각형", "⑦ 난간벽": "⑦ 난간벽",
    "① 하부슬래브 측면": "바닥판 옆면 (양쪽)", "② 상부슬래브 하면": "천장 밑면", "② 상부슬래브 측면": "천장판 옆면 (양쪽)",
    "③ 좌측벽 내측면": "왼쪽 벽 안쪽", "③ 좌측벽 외측면": "왼쪽 벽 바깥쪽", "④ 우측벽 내측면": "오른쪽 벽 안쪽", "④ 우측벽 외측면": "오른쪽 벽 바깥쪽",
    "⑤ 좌측 헌치 경사면": "왼쪽 삼각형 빗면", "⑥ 우측 헌치 경사면": "오른쪽 삼각형 빗면",
    "⑦ 난간벽 측면": "난간벽 앞뒤", "⑦ 난간벽 마구리": "난간벽 양 끝",
    "마감거푸집 시점면": "시작 쪽 끝면 (단면 전체)", "마감거푸집 종점면": "끝 쪽 끝면 (단면 전체)",
    "버림 시·종점면": "앞뒤 끝", "버림 측면": "좌우 옆", "시스템동바리": "안쪽 빈 공간", "우측": "오른쪽 벽 옆", "좌측": "왼쪽 벽 옆",
    "좌측벽": "왼쪽 벽", "우측벽": "오른쪽 벽", "상면": "윗면", "우측면": "오른쪽 면", "좌측면": "왼쪽 면", "상면(방수 상면과 동일)": "윗면",
    "슬래브 하면·헌치": "천장 밑면 + 빗면 2개", "슬래브 및 기초": "바닥 넓이", "벽체용 = 거푸집 합계 − 천장 밑면 − 빗면 2개": "거푸집 합계에서 눕힌 면을 뺀다",
    "배면 경사부": "뒷면 경사 부분", "배면 상단부": "뒷면 윗부분", "배면 헌치": "뒷면 모서리 삼각형 빗면", "외측 경사면": "바깥 경사면",
    "외측 바깥구간": "바깥 구간", "외측 수직면": "바깥 수직면", "외측 수직면(단부)": "바깥 끝면", "전면 상단부": "앞면 윗부분", "전면 경사부": "앞면 경사 부분", "하면": "밑면",
    "본체": "벽 본체 (사다리꼴 + 네모) × 두께", "헌치": "모서리 삼각형", "내측 수평구간": "안쪽 평평한 구간", "외측 경사구간": "바깥 경사 구간", "배면": "뒤쪽", "전면": "앞쪽", "측면": "옆쪽",
    "배면 상단+경사부(거푸집 배면과 동일)": "뒷면 (거푸집 뒷면 넓이와 같음)", "다웰바 하부슬래브": "다웰바 (바닥판)", "외측(저면 제외 3변)": "바깥쪽 3변", "내측(헌치 반영 실둘레)": "안쪽 둘레",
    "지수판(단면 중심선)": "벽·판 가운데 둘레", "상부슬래브": "천장판 단면", "하부슬래브": "바닥판 단면", "벽체": "벽 2개 단면", "버림콘크리트": "버림콘크리트",
}


def fmt_var(value: float, digits: int) -> str:
    if digits == -4:
        text = f"{value:.4f}"
        return text[:-1] if text.endswith("0") else text
    return f"{value:.{digits}f}"


def num(value: float, digits: int = 3) -> str:
    return f"{value:,.{digits}f}"


def pretty(expr: str) -> str:
    """값을 넣은 식을 화면 표기로 바꾼다. 검증기가 이 표기를 그대로 다시 계산한다."""
    s = re.sub(r"sin\((\d+)\)", r"sin\1°", expr)
    s = s.replace("*", " × ").replace("/", " ÷ ").replace("+", " + ")
    return re.sub(r"(?<=[\d)])-(?=[\d(])", " − ", s)


def pretty_names(formula: str) -> str:
    return formula.replace("*", " × ").replace("/", " ÷ ").replace("+", " + ").replace("-", " − ").replace("^2", "²")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


class ReadableBoqAgent:
    def __init__(self, cad_path: str = "data/cad_extracted.json", model_path: str = "data/quantity_model.json", alt_path: str = "output/alternative_boq.json",
                 issues_path: str = "reports/audit_issues.json", output_path: str = "", frozen: bool = False) -> None:
        self.frozen = frozen
        for name, path in (("cad", cad_path), ("model", model_path), ("alt", alt_path), ("audit", issues_path)):
            with open(path, encoding="utf-8") as f:
                setattr(self, name, json.load(f))
        self.output_path = output_path or f"output/대안_수량산출서_Sta.{self.cad['project']['station'] or '도면'}.html"
        self.env: Dict[str, float] = dict(self.model["env"])
        self.digits: Dict[str, int] = self.model["digits"]
        self.summary = {s["key"]: s for s in self.alt["summary"]}
        self.has_original = not frozen and self.audit["original_status"] == "provided"
        self.originals: Dict[str, float] = {}
        if self.has_original:
            self.originals = {f"원본_{k}": s["original"] for k, s in self.summary.items() if s["original"] is not None}
            self.originals["원본_철근재료"] = self.audit["statistics"]["rebar"]["p3_gross"]
        self.result = {c["key"]: c for c in self.audit["comparison"]}
        self.env.update(self.originals)
        self.wing_groups: List[Tuple[int, List[str]]] = []
        for sched in self.cad["rebar"].values():
            if sched["block"] == "WW":
                self.wing_groups.append((int(sched["wing_angle_deg"]), sched["wing_locations"]))
        self.wing_groups.sort(reverse=True)
        v = self.env
        self.W, self.H, self.tt, self.tb, self.tw = v["외곽폭"], v["외곽높이"], v["천장두께"], v["바닥두께"], v["벽두께"]
        self.ih, self.iw, self.hw, self.lw, self.lt = v["안쪽높이"], v["안쪽폭"], v["헌치가로"], v["버림폭"], v["버림두께"]
        self.kinds: Dict[str, str] = {x["name"]: CITE_CLASS[x["kind"]] for x in self.model["variables"]}
        self.local_kinds: Dict[str, str] = {}
        for x in self.model["variables"]:
            self.local_kinds.setdefault(x["local"], CITE_CLASS[x["kind"]])
        # 입력칸 위치: 공통 표 또는 처음 쓰는 공종
        self.usage: Dict[str, Dict[str, Any]] = self.model["var_usage"]
        self.placed: set = set()
        self.first_place: Dict[str, Tuple[str, bool]] = {}
        for line in self.model["lines"]:
            place = (CARD_OF_KEY.get(line["key"], "drain"), line["scope"].startswith("WW-"))
            for name in line["deps"]:
                old = self.first_place.get(name)
                if old is None or (CARD_ORDER.index(place[0]), place[1]) < (CARD_ORDER.index(old[0]), old[1]):
                    self.first_place[name] = place
        self.common = [x for x in self.model["variables"] if x["kind"] == "drawing" and self.is_common(x["name"])]
        self.common.sort(key=lambda x: (-len(self.usage[x["name"]]["keys"]), -self.usage[x["name"]]["lines"]))

    def web(self, *parts: str) -> str:
        """웹 화면에만 싣는 조각(설명, 검산). 내려받는 파일에는 넣지 않는다."""
        return "" if self.frozen else "".join(parts)

    # ---------------------------------------------------------- 수식
    def ev(self, formula: str) -> float:
        code = NAME_RE.sub(lambda m: m.group(0) if m.group(0) in FUNCS else repr(self.env[m.group(0)]), formula).replace("^", "**")
        return float(eval(code, {"__builtins__": {}}, {}))  # noqa: S307 - 내부 생성 수식

    def numeric(self, formula: str) -> str:
        return NAME_RE.sub(lambda m: fmt_var(self.env[m.group(0)], self.digits.get(m.group(0), 3)), formula)

    def lines(self, scope: str, key: str) -> List[Dict[str, Any]]:
        return [l for l in self.model["lines"] if l["scope"] == scope and l["key"] == key]

    def is_common(self, name: str) -> bool:
        use = self.usage.get(name, {"keys": [], "body": False})
        return use["body"] and len(use["keys"]) >= COMMON_MIN_KEYS

    # ---------------------------------------------------------- 글자색
    def kind_of(self, name: str, prefix: Optional[str] = None) -> str:
        """변수 이름의 글자색 구분. 표에 없는 이름은 앞 줄의 계산 결과이므로 파란색이다."""
        if prefix and f"{prefix}_{name}" in self.kinds:
            return self.kinds[f"{prefix}_{name}"]
        return self.kinds.get(name, "c")

    def mark_values(self, shown: str, formula: str, prefix: Optional[str] = None) -> str:
        """값을 넣은 식의 숫자마다 변수식의 같은 자리 변수 색을 입힌다. 식 안의 고정 숫자는 검은색 그대로 둔다."""
        tokens = [t for t in TOKEN_RE.findall(formula) if t not in FUNCS]
        found = list(NUM_RE.finditer(shown))
        if len(tokens) != len(found):
            raise RuntimeError(f"식과 값의 항 수가 다름: {formula} / {shown}")
        out: List[str] = []
        last = 0
        for token, match in zip(tokens, found):
            out.append(esc(shown[last:match.start()]))
            out.append(match.group(0) if token[0].isdigit() else f'<var class="k-{self.kind_of(token, prefix)}">{match.group(0)}</var>')
            last = match.end()
        out.append(esc(shown[last:]))
        return "".join(out)

    def mark_names(self, formula: str, prefix: Optional[str] = None) -> str:
        """변수식의 이름마다 색을 입힌다."""
        return NAME_RE.sub(lambda m: m.group(0) if m.group(0) in FUNCS else f'<var class="k-{self.kind_of(m.group(0), prefix)}">{m.group(0)}</var>', pretty_names(formula))

    def tint_figures(self, page: str) -> str:
        """그림의 치수 글자에도 같은 색을 입힌다. 변수가 아닌 글자는 그대로 둔다."""
        def repl(m: Any) -> str:
            kind = next((self.local_kinds.get(n, self.kinds.get(n)) for n in NAME_RE.findall(m.group(4)) if n in self.local_kinds or n in self.kinds), None)
            if kind is None:
                return m.group(0)
            return f'<text {m.group(1)}class="{m.group(2)} k-{kind}"{m.group(3)}>{m.group(4)}</text>'
        return re.sub(r'<text ([^>]*?)class="(dim|dim-strong)"([^>]*)>([^<]*)</text>', repl, page)

    # ---------------------------------------------------------- 조각
    def calc_span(self, formula: str, digits: int = 3, unit: str = "") -> str:
        value = round(self.ev(formula), max(digits, 0) if digits >= 0 else 4)
        return f'<span class="calc" data-fx="{esc(formula)}" data-d="{digits}" data-val="{value}"><span class="ex">{self.mark_values(pretty(self.numeric(formula)), formula)}</span> = <b>{num(value, digits)}</b>{unit}</span>'

    def calc_cell(self, formula: str, digits: int = 3) -> str:
        value = round(self.ev(formula), digits)
        return f'<td class="cell" data-fx="{esc(formula)}" data-d="{digits}" data-val="{value}"><span class="ex">{self.mark_values(pretty(self.numeric(formula)), formula)}</span><b>{num(value, digits)}</b></td>'

    def line_cell(self, line: Dict[str, Any]) -> str:
        return f'<td class="cell" data-line="{esc(line["id"])}" data-val="{line["value"]}"><span class="ex">{self.mark_values(pretty(line["expr"]), line["formula"], line["prefix"])}</span><b>{num(line["value"])}</b></td>'

    def total_cell(self, name: str, digits: int = 3) -> str:
        value = self.env[name]
        return f'<td data-fx="{esc(name)}" data-d="{digits}" data-total="{value}"><b>{num(value, digits)}</b></td>'

    def matrix(self, key: str, scopes: Sequence[str] = BODY, names: Optional[Dict[str, str]] = None) -> str:
        names = names or BODY_NAME
        order: List[str] = []
        for scope in scopes:
            for line in self.lines(scope, key):
                if line["desc"] not in order:
                    order.append(line["desc"])
        out = ['<div class="scroll"><table class="matrix"><thead><tr><th>어디를 세나 / 변수식</th>' + "".join(f"<th>{names[s]}</th>" for s in scopes) + "</tr></thead><tbody>"]
        for desc in order:
            sample = next(l for s in scopes for l in self.lines(s, key) if l["desc"] == desc)
            row = [f'<tr><th scope="row">{FRIENDLY.get(desc, desc)}<small class="fx">{self.mark_names(sample["formula"], sample["prefix"])}</small></th>']
            for scope in scopes:
                found = [l for l in self.lines(scope, key) if l["desc"] == desc]
                row.append(self.line_cell(found[0]) if found else '<td class="none">없음</td>')
            out.append("".join(row) + "</tr>")
        out.append('<tr class="total"><th scope="row">합계 (위 줄을 모두 더함)</th>' + "".join(self.total_cell(f"합_{self.code(s)}_{key}") for s in scopes) + "</tr></tbody></table></div>")
        return "".join(out)

    @staticmethod
    def code(scope: str) -> str:
        return LOC_CODE[scope[3:]] if scope.startswith("WW-") else scope

    def wing_names(self) -> Tuple[List[str], Dict[str, str]]:
        scopes, names = [], {}
        for angle, locs in self.wing_groups:
            scope = f"WW-{locs[0]}"
            scopes.append(scope)
            names[scope] = f"{angle}° 날개벽 1곳 ({'·'.join(locs)})"
        return scopes, names

    def wing_matrix(self, key: str) -> str:
        scopes, names = self.wing_names()
        return self.matrix(key, scopes, names)

    def wing_sum(self, key: str) -> str:
        scopes, _ = self.wing_names()
        formula = f"(합_{self.code(scopes[0])}_{key}+합_{self.code(scopes[1])}_{key})*2"
        return f'<p class="line">날개벽 4곳: {self.calc_span(formula)}</p>'

    def final(self, key: str, unit: str) -> str:
        s = self.summary[key]
        names = {"Block 1": "합_B1", "Block 2": "합_B2", "Block 3": "합_B3", "날개벽": "군_날개벽"}
        parts = [(g, f"{names[g]}_{key}") for g, v in s["groups"].items() if v is not None]
        origin = f'<span class="diff" data-fx="총_{key}-원본_{key}" data-d="3" data-sign="1">원본과 {s["delta"]:+,.3f}</span>' if s["delta"] and self.has_original else ""
        return f'<div class="final"><span class="final-label">{" + ".join(g for g, _ in parts)}</span><div>{self.calc_span("+".join(n for _, n in parts), 3, " " + unit)}</div>{self.web(origin)}</div>'

    def note(self, needle: str, text: str) -> str:
        if self.frozen:
            return ""
        i = next((x for x in self.audit["issues"] if needle in x["title"] and x["status"] != "UNEXPLAINED"), None)
        if i is None:
            return ""
        tag = "원본과 다른 곳"
        return f'<div class="callout"><strong>{tag} · {i["issue_id"]}</strong><p>{text}</p><p class="meta">원본 {i["boq_value"]} → 대안 {i["corrected_value"]} (산출서 {", ".join(map(str, i["boq_pages"]))}쪽)</p></div>'

    def var_row(self, v: Dict[str, Any]) -> str:
        """입력칸 한 줄. 이 변수의 붉은색은 문서 전체에서 여기뿐이다."""
        value = fmt_var(v["value"], v["digits"] if v["digits"] != -4 else 3)
        cls = INPUT_CLASS[v["kind"]]
        self.placed.add(v["name"])
        box = f'<span class="num k-{cls}" id="v-{esc(v["name"])}">{value}</span>' if self.frozen else f'<input type="number" step="any" class="num k-{cls}" id="v-{esc(v["name"])}" data-var="{esc(v["name"])}" value="{value}" aria-label="{esc(v["name"])}">'
        # 가정값 표에는 출처 칸이 없으므로 웹에서 고친 사실은 뜻 칸에 남긴다
        label = f'{v["label"]} ({v["source"]})' if v["kind"] == "assumed" and v["source"].startswith("웹에서 수정") else v["label"]
        return (f'<th scope="row" class="vname k-{cls}">{esc(v["name"])}</th><td>{esc(label)}</td><td class="in">{box}</td><td>{esc(v["unit"])}</td>')

    def local_inputs(self, card: str, wing: bool = False) -> str:
        """이 공종에서 처음 쓰는 도면 입력값을 그 자리에서 받는다."""
        items = [v for v in self.model["variables"] if v["kind"] == "drawing" and v["name"] not in self.placed and not self.is_common(v["name"]) and self.first_place.get(v["name"]) == (card, wing)]
        if not items:
            return ""
        rows = "".join(f'<tr>{self.var_row(v)}<td class="src">{esc(v["source"])}</td></tr>' for v in items)
        return f'<div class="local"><h4>여기서 처음 쓰는 입력값</h4><div class="scroll"><table class="matrix vars"><thead><tr><th>변수</th><th>뜻</th><th>값</th><th>단위</th><th>도면 어디서 읽었나</th></tr></thead><tbody>{rows}</tbody></table></div></div>'

    def vars_for_card(self, names: Sequence[str], card: str, wing: bool = False) -> str:
        """카드의 입력칸(처음 나오는 값)과 앞에서 받은 값의 인용을 보여 준다."""
        before = set(self.placed)
        inputs = self.local_inputs(card, wing)
        names = [n for n in names if n not in (self.placed - before)]
        if not names:
            return inputs
        chips = "".join(f'<li><span class="vname k-{self.kind_of(n)}">{n}</span> <b class="k-{self.kind_of(n)}" data-fx="{n}" data-d="{self.digits.get(n, 3)}">{fmt_var(self.env[n], self.digits.get(n, 3))}</b></li>' for n in names)
        return inputs + f'<ul class="chips" aria-label="앞에서 받은 값">{chips}</ul>'

    # ---------------------------------------------------------- 그림
    def section_svg(self, mode: str, caption: str) -> str:
        s = 50.0
        ox, oy = 110.0, 44.0
        W, H, tt, tb, tw, hw = self.W * s, self.H * s, self.tt * s, self.tb * s, self.tw * s, self.hw * s
        x0, x1, y0, y1 = ox, ox + W, oy, oy + H
        ix0, ix1, iy0, iy1 = x0 + tw, x1 - tw, y0 + tt, y1 - tb
        hole = f"{ix0 + hw:.1f},{iy0:.1f} {ix1 - hw:.1f},{iy0:.1f} {ix1:.1f},{iy0 + hw:.1f} {ix1:.1f},{iy1:.1f} {ix0:.1f},{iy1:.1f} {ix0:.1f},{iy0 + hw:.1f}"
        lm = (self.lw - self.W) / 2 * s
        lt = max(self.lt * s, 4)
        g: List[str] = []

        def text(x: float, y: float, value: str, cls: str = "dim", anchor: str = "middle") -> None:
            g.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{esc(value)}</text>')

        def seg(a: float, b: float, c: float, d: float, cls: str) -> None:
            g.append(f'<line x1="{a:.1f}" y1="{b:.1f}" x2="{c:.1f}" y2="{d:.1f}" class="{cls}"/>')

        if mode == "pieces":
            g.append(f'<rect x="{x0}" y="{iy1}" width="{W}" height="{tb}" class="p1"/><rect x="{x0}" y="{y0}" width="{W}" height="{tt}" class="p2"/>')
            g.append(f'<rect x="{x0}" y="{iy0}" width="{tw}" height="{iy1 - iy0}" class="p3"/><rect x="{ix1}" y="{iy0}" width="{tw}" height="{iy1 - iy0}" class="p3"/>')
            g.append(f'<polygon points="{ix0},{iy0} {ix0 + hw},{iy0} {ix0},{iy0 + hw}" class="p4"/><polygon points="{ix1},{iy0} {ix1 - hw},{iy0} {ix1},{iy0 + hw}" class="p4"/>')
            for lab, x, y in (("①", x0 + W / 2, iy1 + tb / 2), ("②", x0 + W / 2, y0 + tt / 2), ("③", x0 + tw / 2, oy + H / 2), ("④", x1 - tw / 2, oy + H / 2), ("⑤", ix0 + hw * 0.4, iy0 + hw + 13), ("⑥", ix1 - hw * 0.4, iy0 + hw + 13)):
                text(x, y + 5, lab, "tag")
        else:
            g.append(f'<rect x="{x0}" y="{y0}" width="{W}" height="{H}" class="conc"/><polygon points="{hole}" class="void"/>')
        g.append(f'<rect x="{x0 - lm}" y="{y1}" width="{W + 2 * lm}" height="{lt}" class="{"hit-fill" if mode == "lean" else "conc"}"/>')

        text(x0 + W / 2, y1 + lt + 34, f"외곽폭 {self.W:.3f}" if mode != "lean" else f"버림폭 {self.lw:.3f}")
        if mode in ("pieces", "waterproof", "shoring", "lean"):
            text(x0 - 12, oy + H / 2, f"외곽높이 {self.H:.3f}", "dim", "end")
        if mode == "pieces":
            text(x1 + 12, y0 + tt / 2 + 4, f"천장두께 {self.tt:.3f}", "dim", "start")
            text(x1 + 12, y1 - tb / 2 + 4, f"바닥두께 {self.tb:.3f}", "dim", "start")
            text(x1 + 12, oy + H / 2, f"벽두께 {self.tw:.3f}", "dim", "start")
            text(x0 + W / 2, oy + H / 2 + 6, f"안쪽폭 {self.iw:.3f}")
            text(x0 + W / 2, oy + H / 2 + 24, f"안쪽높이 {self.ih:.3f}")
            text(x0 + W / 2, iy0 + hw + 14, f"헌치가로 {self.hw:.3f} × 헌치세로 {self.env['헌치세로']:.3f}")
        elif mode == "form":
            for a, b, c, d in ((x0, y0, x0, y1), (x1, y0, x1, y1), (ix0, iy0 + hw, ix0, iy1), (ix1, iy0 + hw, ix1, iy1), (ix0 + hw, iy0, ix1 - hw, iy0), (ix0, iy0 + hw, ix0 + hw, iy0), (ix1, iy0 + hw, ix1 - hw, iy0)):
                seg(a, b, c, d, "hit")
            text(x0 - 10, y0 + tt / 2 + 4, f"천장두께 {self.tt:.3f}", "dim", "end")
            text(x0 - 10, oy + H / 2, f"안쪽높이 {self.ih:.3f}", "dim", "end")
            text(x0 - 10, y1 - tb / 2 + 4, f"바닥두께 {self.tb:.3f}", "dim", "end")
            text(x0 + W / 2, iy0 + 18, f"천장밑폭 {self.env['천장밑폭']:.3f}")
            text(x0 + W / 2, oy + H / 2 + 10, f"벽안높이 {self.env['벽안높이']:.3f} (양쪽)")
            text(x0 + W / 2, iy0 + hw + 20, f"빗면 {self.env['빗면']:.3f} (양쪽)")
        elif mode == "shoring":
            g.append(f'<rect x="{ix0}" y="{iy0}" width="{ix1 - ix0}" height="{iy1 - iy0}" class="hit-fill"/>')
            text(x0 + W / 2, oy + H / 2, f"안쪽폭 {self.iw:.3f}", "dim-strong")
            text(x0 + W / 2, oy + H / 2 + 18, f"× 안쪽높이 {self.ih:.3f}", "dim-strong")
        elif mode == "scaffold":
            top = y0 + self.env["비계공제"] * s
            seg(x0 - 12, top, x0 - 12, y1, "hit")
            seg(x1 + 12, top, x1 + 12, y1, "hit")
            text(x0 - 20, oy + H / 2 + 6, "외곽높이", "dim", "end")
            text(x0 - 20, oy + H / 2 + 22, "− 비계공제", "dim", "end")
        elif mode == "waterproof":
            for a, b, c, d in ((x0, y0, x1, y0), (x0, y0, x0, y1), (x1, y0, x1, y1)):
                seg(a, b, c, d, "hit")
            text(x0 + W / 2, y0 - 10, f"윗면 외곽폭 {self.W:.3f}")
            text(x1 + 12, oy + H / 2, f"외곽높이 {self.H:.3f}", "dim", "start")
        elif mode == "joint":
            for a, b, c, d in ((x0, y0, x1, y0), (x0, y0, x0, y1), (x1, y0, x1, y1)):
                seg(a, b, c, d, "hit")
            g.append(f'<polygon points="{hole}" class="line-b"/>')
            cx0, cx1, cy0, cy1 = x0 + tw / 2, x1 - tw / 2, y0 + tt / 2, y1 - tb / 2
            g.append(f'<rect x="{cx0}" y="{cy0}" width="{cx1 - cx0}" height="{cy1 - cy0}" class="line-c"/>')
            text(x0 + W / 2, y0 - 10, "주황: 바깥 실런트 (3변)")
            text(x0 + W / 2, oy + H / 2, "파랑: 안쪽 실런트")
            text(x0 + W / 2, oy + H / 2 + 18, "점선: 지수판 (벽·판 가운데)")
        elif mode == "lean":
            text(x0 + W / 2, oy + H / 2, "본체")
            text(x1 + lm + 8, y1 + lt, f"버림두께 {self.lt:.3f}", "dim", "start")
        svg = f'<svg viewBox="0 0 480 {y1 + lt + 46:.0f}" role="img" aria-label="{esc(caption)}">' + "".join(g) + "</svg>"
        return f'<figure class="fig">{svg}<figcaption>{caption}</figcaption></figure>'

    def plan_svg(self) -> str:
        b = {n: {"left": self.env[f"{p}_왼쪽길이"], "right": self.env[f"{p}_오른쪽길이"]} for n, p in (("B1", "블록1"), ("B2", "블록2"), ("B3", "블록3"))}
        s = 15.0
        ox, oy = 150.0, 130.0
        w = self.W * s
        gap = self.cad["plan"]["joint_gap_mm"] / 1000 * s
        offs = (b["B1"]["left"] - b["B1"]["right"]) * s
        x_mid0 = ox + b["B1"]["left"] * s + gap
        x_mid1 = x_mid0 + b["B2"]["left"] * s
        x_e0 = x_mid1 + gap
        g = [f'<polygon points="{ox:.1f},{oy} {ox + b["B1"]["left"] * s:.1f},{oy} {ox + b["B1"]["left"] * s:.1f},{oy + w} {ox + offs:.1f},{oy + w}" class="p1"/>',
             f'<rect x="{x_mid0:.1f}" y="{oy}" width="{b["B2"]["left"] * s:.1f}" height="{w}" class="p2"/>',
             f'<polygon points="{x_e0:.1f},{oy} {x_e0 + b["B3"]["left"] * s:.1f},{oy} {x_e0 + b["B3"]["right"] * s:.1f},{oy + w} {x_e0:.1f},{oy + w}" class="p3"/>']
        tan = self.env["기울기"]
        dy = self.env["날개전체길이"] * s * 0.96
        dx = tan * dy
        for x, y, ddx, ddy, name in [(ox, oy, -dx, -dy, "시점좌"), (ox + offs, oy + w, dx, dy, "시점우"), (x_e0 + b["B3"]["left"] * s, oy, -dx, -dy, "종점좌"), (x_e0 + b["B3"]["right"] * s, oy + w, dx, dy, "종점우")]:
            g.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x + ddx:.1f}" y2="{y + ddy:.1f}" class="wing"/>')
            g.append(f'<text x="{x + ddx:.1f}" y="{y + ddy + (-6 if ddy < 0 else 16):.1f}" class="dim" text-anchor="middle">날개벽 {name}</text>')
        for name, cx in (("B1", ox + b["B1"]["left"] * s / 2 + offs / 4), ("B2", x_mid0 + b["B2"]["left"] * s / 2), ("B3", x_e0 + (b["B3"]["left"] + b["B3"]["right"]) * s / 4)):
            g.append(f'<text x="{cx:.1f}" y="{oy + w / 2 + 4:.1f}" class="tag" text-anchor="middle">{BODY_NAME[name]}</text>')
        tops = ((ox + b["B1"]["left"] * s / 2, "B1"), (x_mid0 + b["B2"]["left"] * s / 2, "B2"), (x_e0 + b["B3"]["left"] * s / 2, "B3"))
        lows = ((ox + offs + b["B1"]["right"] * s / 2, "B1"), (x_mid0 + b["B2"]["right"] * s / 2, "B2"), (x_e0 + b["B3"]["right"] * s / 2, "B3"))
        for cx, n in tops:
            g.append(f'<text x="{cx:.1f}" y="{oy - 6}" class="dim" text-anchor="middle">왼쪽길이 {b[n]["left"]:.3f}</text>')
        for cx, n in lows:
            g.append(f'<text x="{cx:.1f}" y="{oy + w + 15:.1f}" class="dim" text-anchor="middle">오른쪽길이 {b[n]["right"]:.3f}</text>')
        g.append(f'<text x="{x_mid0 - 1:.1f}" y="{oy + w + 32:.1f}" class="dim" text-anchor="middle">이음</text><text x="{x_e0 - 1:.1f}" y="{oy + w + 32:.1f}" class="dim" text-anchor="middle">이음</text>')
        g.append(f'<text x="{ox - 8:.1f}" y="{oy + w / 2 + 4:.1f}" class="dim" text-anchor="end">외곽폭 {self.W:.3f}</text>')
        plan = self.cad["plan"]
        caption = "" if self.frozen else f'<figcaption>위에서 내려다본 모습. 총길이 {plan["total_length_m"]:.3f}m = 블록 평균 길이 3개 + 이음 {plan["joint_gap_mm"]:.0f}mm 2곳. 위쪽이 왼쪽 벽, 아래쪽이 오른쪽 벽이다. 날개벽 선은 위치만 나타낸 개략이다.</figcaption>'
        return f'<figure class="fig wide"><div class="scroll"><svg viewBox="0 0 960 330" class="minw" role="img" aria-label="암거 평면도">' + "".join(g) + f'</svg></div>{caption}</figure>'

    def skew_svg(self) -> str:
        b = self.cad["plan"]["blocks"]["B1"]
        s = 28.0
        ox, oy = 30.0, 40.0
        w = self.W * s
        off = (b["left"] - b["right"]) * s
        g = [f'<polygon points="{ox},{oy} {ox + b["left"] * s:.1f},{oy} {ox + b["left"] * s:.1f},{oy + w} {ox + off:.1f},{oy + w}" class="p1"/>',
             f'<line x1="{ox + off / 2:.1f}" y1="{oy + w / 2:.1f}" x2="{ox + b["left"] * s:.1f}" y2="{oy + w / 2:.1f}" class="line-c"/>',
             f'<text x="{ox + b["left"] * s / 2:.1f}" y="{oy - 8}" class="dim" text-anchor="middle">왼쪽길이 {b["left"]:.3f}</text>',
             f'<text x="{ox + off + b["right"] * s / 2:.1f}" y="{oy + w + 18:.1f}" class="dim" text-anchor="middle">오른쪽길이 {b["right"]:.3f}</text>',
             f'<text x="{ox + b["left"] * s / 2 + 10:.1f}" y="{oy + w / 2 - 7:.1f}" class="dim-strong" text-anchor="middle">평균길이 {b["avg"]:.3f}</text>']
        return (f'<figure class="fig skew"><div class="scroll"><svg viewBox="0 0 500 {oy + w + 34:.0f}" class="minw-s" role="img" aria-label="비스듬한 블록">' + "".join(g) +
                "</svg></div><figcaption>Block 1을 위에서 본 모습. 한쪽 끝이 비스듬해 왼쪽과 오른쪽 길이가 다르다. 사다리꼴 넓이는 평균 길이로 구한다: 평균길이 = (왼쪽길이 + 오른쪽길이) ÷ 2</figcaption></figure>")

    def wing_svg(self) -> str:
        s = 40.0
        ox, oy = 118.0, 34.0
        v = self.env
        tip, root, slope, flat = v["날개끝높이"], v["날개전체높이"], v["날개경사길이"], v["날개평평길이"]
        pts = f"{ox},{oy} {ox + (flat + slope) * s:.1f},{oy} {ox + (flat + slope) * s:.1f},{oy + tip * s:.1f} {ox + flat * s:.1f},{oy + root * s:.1f} {ox},{oy + root * s:.1f}"
        g = [f'<polygon points="{pts}" class="p3"/>', f'<line x1="{ox + flat * s:.1f}" y1="{oy}" x2="{ox + flat * s:.1f}" y2="{oy + root * s:.1f}" class="line-c"/>',
             f'<text x="{ox + (flat + slope) * s / 2:.1f}" y="{oy - 10}" class="dim" text-anchor="middle">날개전체길이 {v["날개전체길이"]:.3f}</text>',
             f'<text x="{ox - 8}" y="{oy + root * s / 2:.1f}" class="dim" text-anchor="end">날개전체높이 {root:.3f}</text>',
             f'<text x="{ox + (flat + slope) * s - 8:.1f}" y="{oy + tip * s / 2 + 4:.1f}" class="dim" text-anchor="end">날개끝높이 {tip:.3f}</text>',
             f'<text x="{ox + flat * s / 2:.1f}" y="{oy + root * s + 18:.1f}" class="dim" text-anchor="middle">날개평평길이 {flat:.3f}</text>',
             f'<text x="{ox + flat * s + slope * s * 0.55:.1f}" y="{oy + root * s * 0.78:.1f}" class="dim">날개경사길이 {slope:.3f}</text>',
             f'<text x="{ox + flat * s + slope * s * 0.38:.1f}" y="{oy + 90}" class="tag" text-anchor="middle">사다리꼴</text>',
             f'<text x="{ox + flat * s / 2:.1f}" y="{oy + 90}" class="dim" text-anchor="middle">네모</text>']
        return (f'<figure class="fig wing-fig"><svg viewBox="0 0 470 {oy + root * s + 30:.0f}" role="img" aria-label="날개벽 정면">' + "".join(g) +
                "</svg><figcaption>" + ("날개벽 정면" if self.frozen else "날개벽을 앞에서 본 모습. 네모 하나와 사다리꼴 하나로 나눈다.") + "</figcaption></figure>")

    # ---------------------------------------------------------- 카드
    def card(self, cid: str, title: str, intro: str, *parts: str) -> str:
        return f'<section class="card" id="{cid}"><h2>{title}</h2>{self.web(f'<p class="intro">{intro}</p>')}' + "".join(parts) + "</section>"

    def card_concrete(self) -> str:
        tri = "헌치가로*헌치세로/2"
        pieces = [("① 바닥판", "외곽폭*바닥두께", 4), ("② 천장판", "외곽폭*천장두께", 4), ("③ 왼쪽 벽", "벽두께*안쪽높이", 4), ("④ 오른쪽 벽", "벽두께*안쪽높이", 4), ("⑤ 왼쪽 삼각형", tri, 5), ("⑥ 오른쪽 삼각형", tri, 5)]
        rows = "".join(f'<tr><th scope="row">{n}<small class="fx">{self.mark_names(f)}</small></th>{self.calc_cell(f, d)}</tr>' for n, f, d in pieces)
        rows += f'<tr class="total"><th scope="row">단면넓이</th>{self.total_cell("단면넓이", 4)}</tr>'
        step1 = f'<h3>1단계 · 단면을 조각내어 넓이를 더한다</h3><div class="scroll"><table class="matrix narrow"><thead><tr><th>조각 / 변수식</th><th>넓이 (㎡)</th></tr></thead><tbody>{rows}</tbody></table></div>'
        check = f'<p class="line">다른 방법으로 검산: 큰 네모 − 빈 공간 + 삼각형 2개 → {self.calc_span("외곽폭*외곽높이-안쪽폭*안쪽높이+2*(헌치가로*헌치세로/2)", 4, " ㎡")}</p>'
        step2 = "<h3>2단계 · 조각마다 길이를 곱한다</h3>" + self.web("<p>블록마다 단면은 같고 길이만 다르다. 비스듬한 블록의 벽 길이는 바깥쪽과 안쪽의 평균이다.</p>") + self.matrix("concrete")
        quick = []
        for b, name in (("B1", "블록1"), ("B2", "블록2"), ("B3", "블록3")):
            line = self.lines(b, "concrete")
            parapet = f' + 난간벽 <b data-line-val="{line[-1]["id"]}">{line[-1]["value"]:.3f}</b>' if len(line) == 7 else ""
            quick.append(f"<li>{BODY_NAME[b]}: {self.calc_span(f'단면넓이*{name}_평균길이')}{parapet} → 표 합계 <b data-fx=\"합_{b}_concrete\" data-d=\"3\">{num(self.env[f'합_{b}_concrete'])}</b></li>")
        quick_html = '<div class="quick"><h4>암산 검산: 단면넓이 × 평균길이</h4><ul>' + "".join(quick) + '</ul><p class="meta">표는 줄마다 반올림해서 0.001 정도 차이가 날 수 있다.</p></div>'
        wing = ("<h3>3단계 · 날개벽</h3>" + self.web("<p>벽을 앞에서 본 넓이에 날개두께를 곱하고, 뒤쪽 모서리 삼각형을 더한다. 삼각형 넓이에는 계산기의 sin을 쓴다.</p>") + self.local_inputs("concrete", True) + self.wing_svg() + self.wing_matrix("concrete") + self.wing_sum("concrete"))
        return self.card("concrete", "구조물 콘크리트", "콘크리트 양은 부피다. 부피는 단면 넓이 × 길이다.",
                         self.vars_for_card(["외곽폭", "외곽높이", "안쪽폭", "안쪽높이", "천장두께", "바닥두께", "벽두께", "헌치가로", "헌치세로"], "concrete"),
                         self.section_svg("pieces", "표준단면을 조각낸 그림. 치수 단위는 m"), step1, self.web(check), step2, self.web(quick_html), wing, self.final("concrete", "㎥"))

    def card_lean(self) -> str:
        return self.card("lean", "버림 콘크리트", "본체를 놓기 전에 바닥을 고르는 얇은 콘크리트다. 폭 × 두께 × 길이로 구한다. 비스듬한 끝에서는 조금 더 길어진다.",
                         self.vars_for_card(["버림폭", "버림두께"], "lean"), self.section_svg("lean", "주황색이 버림 콘크리트"), self.matrix("lean"), self.final("lean", "㎥"))

    def card_form(self) -> str:
        quick = []
        for b, name in (("B1", "블록1"), ("B2", "블록2"), ("B3", "블록3")):
            ends = sum(l["value"] for l in self.lines(b, "form_normal") if "마감" in l["desc"])
            par = sum(l["value"] for l in self.lines(b, "form_normal") if "난간벽" in l["desc"])
            quick.append(f"<li>{BODY_NAME[b]}: {self.calc_span(f'미터당거푸집*{name}_평균길이')} + 끝면 <b class=\"k-c\">{ends:.3f}</b>" + (f" + 난간벽 <b class=\"k-c\">{par:.3f}</b>" if par else "") + f" → 표 합계 <b data-fx=\"합_{b}_form_normal\" data-d=\"3\">{num(self.env[f'합_{b}_form_normal'])}</b></li>")
        quick_html = f'<div class="quick"><h4>암산 검산: 길이 1m에 필요한 판 넓이</h4><p>{self.calc_span("외곽높이*2+벽안높이*2+천장밑폭+빗면*2", 3, " ㎡")}</p><ul>' + "".join(quick) + "</ul></div>"
        return self.card("form", "유로폼 거푸집 (보통)", "거푸집은 콘크리트가 굳을 때까지 모양을 잡아 주는 판이다. 콘크리트가 판에 닿는 면을 모두 찾아 넓이를 더한다. 윗면과 안쪽 바닥은 판을 대지 않는다.",
                         self.vars_for_card(["천장밑폭", "벽안높이", "빗면"], "form"), self.section_svg("form", "주황색 선이 판을 대는 면"), self.matrix("form_normal"), self.web(quick_html),
                         "<h3>날개벽</h3>", self.local_inputs("form", True), self.wing_matrix("form_normal"), self.web('<p class="meta">뒷길이는 날개두께 때문에 각도에 따라 앞면보다 길거나 짧다. 뒤빗면은 각도에 따라 달라진다.</p>'), self.wing_sum("form_normal"), self.final("form_normal", "㎡"))

    def card_form_simple(self) -> str:
        return self.card("form-simple", "유로폼 거푸집 (간단)", "버림 콘크리트의 옆면에 대는 낮은 판이다. 둘레를 돌며 버림두께를 곱한다.", self.local_inputs("form-simple"), self.matrix("form_simple"), self.final("form_simple", "㎡"))

    def card_shoring(self) -> str:
        return self.card("shoring", "동바리", "천장이 굳을 때까지 아래에서 받치는 기둥들이다. 받치는 안쪽 빈 공간의 부피로 센다.",
                         self.local_inputs("shoring"), self.section_svg("shoring", "주황색 공간이 동바리가 서는 곳"), self.matrix("shoring"), "<h3>날개벽</h3>", self.local_inputs("shoring", True), self.wing_matrix("shoring"), self.wing_sum("shoring"), self.final("shoring", "㎥"))

    def card_scaffold(self) -> str:
        return self.card("scaffold", "시스템 비계", "벽 바깥쪽에서 일할 때 딛는 발판이다. 높이 × 길이로 넓이를 구한다.",
                         self.vars_for_card(["비계공제", "날개비계높이", "날개비계측면"], "scaffold"), self.section_svg("scaffold", "주황색 선이 비계를 세우는 곳"), self.matrix("scaffold"), "<h3>날개벽</h3>", self.local_inputs("scaffold", True), self.wing_matrix("scaffold"), self.wing_sum("scaffold"), self.final("scaffold", "㎡"))

    def card_spacer(self) -> str:
        scopes, _ = self.wing_names()
        wing = ('<h3>날개벽</h3>' + self.web('<p>날개벽은 전부 벽체용이다. 그래서 스페이서 넓이가 거푸집 넓이와 같다.</p>') + self.local_inputs("spacer", True) + self.wing_matrix("spacer_wall") + self.wing_sum("spacer_wall"))
        _ = scopes
        return self.card("spacer", "스페이서", "철근이 거푸집에 닿지 않게 띄워 주는 받침이다. 넓이로 세며, 거푸집 표의 값을 다시 쓴다. 벽처럼 세운 면과 슬래브처럼 눕힌 면으로 나눈다.",
                         self.local_inputs("spacer"), "<h3>벽체용</h3>", self.matrix("spacer_wall"), "<h3>슬래브·기초용</h3>", self.matrix("spacer_slab"),
                         self.note("체적이 합산", "날개벽 스페이서 식의 끝에 동바리 부피(㎥)가 더해져 있었다. 넓이(㎡)에 부피를 더할 수 없으므로 뺐다."), wing,
                         self.final("spacer_wall", "㎡ (벽체용)"), self.final("spacer_slab", "㎡ (슬래브·기초용)"))

    def card_waterproof(self) -> str:
        return self.card("waterproof", "아스팔트 방수와 양생", "방수는 흙에 닿는 겉면에 칠한다. 윗면과 양쪽 벽 바깥면을 더한다. 양생은 윗면 콘크리트를 굳히는 동안 보호하는 작업이라 윗면 넓이만 센다.",
                         self.local_inputs("waterproof"), self.section_svg("waterproof", "주황색 선이 방수를 칠하는 면"), self.matrix("waterproof"), "<h3>날개벽 (흙에 닿는 뒷면)</h3>", self.local_inputs("waterproof", True), self.wing_matrix("waterproof"),
                         self.note("방수면적", "원본은 각도가 다른 4곳에 같은 숫자를 썼고, 이 값은 도면에 없다. 대안은 거푸집 뒷면 넓이와 같게 맞췄다."),
                         self.wing_sum("waterproof"), self.final("waterproof", "㎡"), "<h3>콘크리트 양생</h3>", self.matrix("curing"), self.final("curing", "㎡"))

    def card_joint(self) -> str:
        one = [("sealant", "실런트", "m"), ("styrofoam", "스티로폼", "㎡"), ("waterstop", "지수판", "m"), ("rain_wall", "우수유입방지벽", "㎥"), ("dowel", "다웰바", "EA")]
        rows = []
        for key, name, unit in one:
            for line in self.lines("B2", key):
                label = FRIENDLY.get(line["desc"], line["desc"])
                rows.append(f'<tr><th scope="row">{name}: {label}<small class="fx">{self.mark_names(line["formula"], line["prefix"])}</small></th>{self.line_cell(line)}</tr>')
            rows.append(f'<tr class="sub"><th scope="row">{name} 이음 1곳 합계</th><td data-fx="합_B2_{key}" data-d="3"><b>{num(self.env[f"합_B2_{key}"])}</b> {unit}</td></tr>')
        table = '<div class="scroll"><table class="matrix narrow"><thead><tr><th>이음 1곳에서 세는 것 / 변수식</th><th>계산</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
        items = "".join(f"<li>{name}: {self.calc_span(f'합_B2_{key}*2', 3, ' ' + unit)}</li>" for key, name, unit in one)
        return self.card("joint", "신축이음", f"블록과 블록 사이 틈({self.cad['plan']['joint_gap_mm']:.0f}mm)이 물을 막고 함께 움직이도록 넣는 재료들이다. 이음은 Block 1-2 사이와 Block 2-3 사이 2곳이고, 두 곳이 똑같다. 한 곳만 계산해 2를 곱한다.",
                         self.vars_for_card(["방지벽폭", "방지벽높이", "다웰간격", "지수판가로", "지수판세로"], "joint"), self.section_svg("joint", "이음을 정면에서 본 그림"), table, f'<div class="quick"><h4>이음 2곳 합계</h4><ul>{items}</ul></div>',
                         self.note("내측 실런트", "원본은 안쪽 둘레를 삼각형 없이 셌다. 위쪽 모서리에 삼각형이 있어 실제 둘레는 더 짧다."))

    def card_construction(self) -> str:
        return self.card("construction-joint", "시공이음과 수축이음", "시공이음은 바닥을 먼저 치고 벽을 나중에 칠 때 생기는 벽 위아래의 경계다. 수축이음은 벽의 균열을 한곳으로 모으려고 일부러 만든 줄이다.",
                         self.local_inputs("construction-joint"), "<h3>시공이음 면정리 (넓이)</h3>", self.matrix("joint_clean"), self.final("joint_clean", "㎡"), "<h3>수팽창성 지수제 (길이)</h3>", self.matrix("swell"), self.final("swell", "m"), "<h3>수축이음 (길이)</h3>", self.matrix("contraction"), self.final("contraction", "m"))

    def card_drain(self) -> str:
        spec = self.model["pvc_spec"]
        return self.card("drain", "날개벽 배수", "날개벽 뒤 물이 빠지도록 벽을 뚫어 넣는 관과, 흙이 막지 못하게 씌우는 천이다. 한 곳에 2개씩, 날개벽 4곳에 넣는다.",
                         self.vars_for_card(["PVC길이", "배수관개수", "부직포가로", "부직포세로", "부직포장수"], "drain", True), "<h3>PVC 배수관 (길이)</h3>", self.wing_matrix("pvc"), self.wing_sum("pvc"), self.final("pvc", "m"),
                         self.note("PVC", f"원본은 쪽마다 관경이 달랐다. 도면 재료표의 {esc(spec)}을 따라 φ{self.model['pvc_dia_mm']:.0f}로 통일했다. 길이는 그대로다."),
                         "<h3>부직포 (넓이)</h3>", self.wing_matrix("fabric"), self.wing_sum("fabric"), self.final("fabric", "㎡"))

    def bar_input(self, row: int, field: str, value: str, label: str) -> str:
        if self.frozen:
            return f'<td class="in"><span class="num k-i">{value}</span></td>'
        step = "any" if field == "L" else "1"
        return f'<td class="in"><input type="number" step="{step}" class="num k-i" data-bar="{row}" data-field="{field}" value="{value}" aria-label="{esc(label)}"></td>'

    def card_rebar(self) -> str:
        rb = self.model["rebar"]
        first = rb["bars"][0]
        opened = " open" if self.frozen else ""
        example = (f'<div class="quick"><h4>철근 한 줄 읽는 법 ({esc(first["mark"])}, {first["dia"]})</h4><p>총길이 = 1개 길이 × 개수. 도면 재료표의 값을 그대로 넣는다.</p>'
                   "<p>같은 굵기의 총길이를 모두 더하고 1m 무게를 곱한 뒤 1000으로 나누면 톤(t)이 된다. 자르고 남는 양을 생각해 굵은 철근(S22 이상)은 6%, 가는 철근(S19 이하)은 3%를 더한다.</p></div>")
        names = {"B1": "Block 1", "B2": "Block 2", "B3": "Block 3"}
        rule_rows = "".join(f'<tr>{self.var_row(v)}<td class="src">{esc(v["source"])}</td></tr>' for v in self.model["variables"] if v["kind"] == "rule")
        rules = f'<div class="local"><h4>철근 규칙 (검은색: 도면 입력이 아닌 값)</h4><div class="scroll"><table class="matrix vars"><thead><tr><th>변수</th><th>뜻</th><th>값</th><th>단위</th><th>근거</th></tr></thead><tbody>{rule_rows}</tbody></table></div></div>'
        rows = []
        for i, rec in enumerate(rb["records"]):
            rows.append(f'<tr><th scope="row">{names.get(rec["scope"], "날개벽 " + rec["scope"][3:])}</th><td>{rec["dia"]}</td><td>{esc(rec["sheet"])}</td>'
                        f'<td class="cell" data-rec="{i}" data-part="net" data-val="{rec["net_t"]}"><span class="ex">{self.mark_values(pretty(rec["net_expr"]), rec["net_formula"])}</span><b>{num(rec["net_t"])}</b></td>'
                        f'<td class="cell" data-rec="{i}" data-part="gross" data-val="{rec["gross_t"]}"><span class="ex">{self.mark_values(pretty(rec["gross_expr"]), rec["gross_formula"])}</span><b>{num(rec["gross_t"])}</b></td></tr>')
        rows.append(f'<tr class="total"><th scope="row" colspan="3">합계</th>{self.total_cell("철근총_net")}{self.total_cell("철근총_gross")}</tr>')
        table = '<div class="scroll"><table class="matrix rebar"><thead><tr><th>어디</th><th>굵기</th><th>도면</th><th>NET: 총길이 × 1m 무게 ÷ 1000 (t)</th><th>재료량: NET × (1 + 할증률) (t)</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
        order = sorted(rb["by_dia"], key=lambda d: -int(d[1:]))
        dia_sum = '<div class="quick"><h4>굵기별 합계</h4><ul>' + "".join(f'<li>{d}: NET <b data-fx="철근_{d}_net" data-d="3">{rb["by_dia"][d]["net_t"]:.3f}</b> t → 재료량 <b data-fx="철근_{d}_gross" data-d="3">{rb["by_dia"][d]["gross_t"]:.3f}</b> t (할증 {round(rb["by_dia"][d]["rate"] * 100)}%)</li>' for d in order) + "</ul></div>"
        detail = []
        grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
        for i, bar in enumerate(rb["bars"]):
            grouped.setdefault(bar["sheet"], []).append((i, bar))
        for sheet, bars in grouped.items():
            sched = self.cad["rebar"][sheet]
            rows2 = "".join(
                f'<tr><th scope="row">{esc(b["mark"])}</th><td>{b["dia"]}</td>'
                + self.bar_input(i, "L", f'{b["L"]:.3f}', f'{sheet} {b["mark"]} 1개 길이') + self.bar_input(i, "N", str(b["N"]), f'{sheet} {b["mark"]} 개수') +
                f'<td class="cell" data-bar-total="{i}" data-val="{round(b["L"] * b["N"], 3)}"><span class="ex"><var class="k-c">{b["L"]:.3f}</var> × <var class="k-c">{b["N"]}</var></span><b>{num(b["L"] * b["N"])}</b></td></tr>' for i, b in bars)
            title = f"날개벽 {'·'.join(sched['wing_locations'])}" if sched["block"] == "WW" else BODY_NAME[sched["block"]]
            detail.append(f'<details{opened}><summary>{esc(sheet)} 재료표 {len(bars)}줄 ({title})</summary><div class="scroll"><table class="matrix narrow"><thead><tr><th>기호</th><th>굵기</th><th>1개 길이 (m)</th><th>개수</th><th>총길이 (m)</th></tr></thead><tbody>{rows2}</tbody></table></div></details>')
        return self.card("rebar", "철근", "철근은 무게(톤)로 센다. 무게 = 총길이 × 1m 무게다. 도면의 철근 재료표 한 줄 한 줄이 입력 변수다.",
                         "<h3>기호별 입력값</h3>", "".join(detail), rules, self.web(example), table, dia_sum,
                         f'<div class="final"><span class="final-label">철근가공조립 (NET) H13 + H16~25</span><div>{self.calc_span("총_H13+총_H16_25", 3, " t")}</div></div>',
                         f'<div class="final"><span class="final-label">철근 재료량 (할증 포함)</span><div><b class="big" data-fx="철근총_gross" data-d="3">{num(rb["gross_total_t"])}</b> t</div>' + (f'<span class="diff" data-fx="철근총_gross-원본_철근재료" data-d="3" data-sign="1">원본 p.3과 {rb["gross_total_t"] - self.env["원본_철근재료"]:+.3f}</span>' if self.has_original else "") + "</div>")

    # ---------------------------------------------------------- 머리말
    def variable_panel(self) -> str:
        """앞쪽 입력 표: 여러 공종에 쓰는 도면 값(많이 쓰는 순)과 도면에 없는 가정값."""
        common_rows = "".join(f'<tr>{self.var_row(v)}<td class="r">{len(self.usage[v["name"]]["keys"])}</td><td class="src">{esc(v["source"])}</td></tr>' for v in self.common)
        out = [f'<h3>공통 입력값 (많이 쓰는 순)</h3><div class="scroll"><table class="matrix vars"><thead><tr><th>변수</th><th>뜻</th><th>값</th><th>단위</th><th class="r">쓰는 공종 수</th><th>도면 어디서 읽었나</th></tr></thead><tbody>{common_rows}</tbody></table></div>']
        work = {s["key"]: s["work"] for s in self.alt["summary"]}
        assumed_rows = []
        for v in self.model["variables"]:
            if v["kind"] != "assumed":
                continue
            names = list(dict.fromkeys(work.get(k, k) for k in self.usage[v["name"]]["keys"]))
            assumed_rows.append(f'<tr>{self.var_row(v)}<td>{esc(", ".join(names))}</td></tr>')
        out.append('<h3>가정값 (검은색)</h3>' +
                   f'<div class="scroll"><table class="matrix vars assumed"><thead><tr><th>변수</th><th>뜻</th><th>값</th><th>단위</th><th>영향 공종</th></tr></thead><tbody>{"".join(assumed_rows)}</tbody></table></div>')
        return "".join(out)

    def derived_panel(self) -> str:
        derived_rows = "".join(f'<tr><th scope="row" class="vname k-c">{esc(v["name"])}</th><td>{esc(v["label"])}</td><td data-fx="{esc(v["name"])}" data-d="{v["digits"]}"><b>{fmt_var(v["value"], v["digits"])}</b></td><td class="src">{self.mark_names(v["formula"], v["prefix"])}</td></tr>' for v in self.model["variables"] if v["kind"] == "derived")
        count = sum(1 for v in self.model["variables"] if v["kind"] == "derived")
        return f'<details{" open" if self.frozen else ""}><summary>계산 변수 {count}개 보기</summary><div class="scroll"><table class="matrix vars"><thead><tr><th>변수</th><th>뜻</th><th>값</th><th>계산식</th></tr></thead><tbody>{derived_rows}</tbody></table></div></details>'

    LINKS = {"concrete": "concrete", "lean": "lean", "pump": "concrete", "plain_pour": "lean", "form_normal": "form", "form_simple": "form-simple", "shoring": "shoring", "scaffold": "scaffold", "spacer_wall": "spacer", "spacer_slab": "spacer",
             "dowel": "joint", "joint_clean": "construction-joint", "swell": "construction-joint", "waterstop": "joint", "sealant": "joint", "styrofoam": "joint", "rain_wall": "joint", "waterproof": "waterproof", "pvc": "drain", "fabric": "drain", "H13": "rebar", "H16_25": "rebar", "curing": "waterproof", "contraction": "construction-joint", "rebar_gross": "rebar"}

    def assumed_text(self, item: Dict[str, Any]) -> str:
        names = item["assumed"]
        if not names:
            return ""
        short = names[0] + (f" 외 {len(names) - 1}개" if len(names) > 1 else "")
        share = item["assumed_share"] * 100
        return f'가정값 {esc(short)} (수량의 {"1% 미만" if share < 1 else f"{share:.0f}%"})'

    def result_rows(self) -> List[Dict[str, Any]]:
        rb = self.model["rebar"]
        rows = [dict(s, fx=f"총_{s['key']}", original_name=f"원본_{s['key']}") for s in self.alt["summary"] if s["total"] is not None]
        res = self.result["rebar_gross"]
        rows.append({"key": "rebar_gross", "work": "철근 재료량", "spec": "할증 포함", "unit": "t", "total": rb["gross_total_t"], "original": res["original"], "delta": res["delta"], "fx": "철근총_gross", "original_name": "원본_철근재료"})
        for row in rows:
            row["res"] = self.result[row["key"]]
        return rows

    def compare_section(self) -> str:
        """원본이 있으면 비교 요약과 표, 없으면 도면 산출 표."""
        rows = self.result_rows()
        if self.frozen:
            body = "".join(f'<tr><th scope="row"><a href="#{self.LINKS[r["key"]]}">{r["work"]}</a></th><td>{esc(r["spec"])}</td><td class="r"><b data-fx="{r["fx"]}" data-d="{0 if r["key"] == "dowel" else 3}">{num(r["total"], 0 if r["key"] == "dowel" else 3)}</b></td><td>{r["unit"]}</td></tr>' for r in rows)
            return f'<section class="plain" id="result"><h2>수량 총괄</h2><div class="scroll"><table class="matrix sum"><thead><tr><th>공종</th><th>규격</th><th class="r">수량</th><th>단위</th></tr></thead><tbody>{body}</tbody></table></div></section>'
        if not self.has_original:
            why = esc(self.audit["original_note"]) + "." if self.audit["original_status"] == "parse_failed" else "원본 수량산출서가 제공되지 않았습니다."
            body = "".join(f'<tr><th scope="row"><a href="#{self.LINKS[r["key"]]}">{r["work"]}</a></th><td>{esc(r["spec"])}</td><td class="r"><b data-fx="{r["fx"]}" data-d="{0 if r["key"] == "dowel" else 3}">{num(r["total"], 0 if r["key"] == "dowel" else 3)}</b></td><td>{r["unit"]}</td><td>{self.assumed_text(r["res"])}</td></tr>' for r in rows)
            return (f'<section class="plain" id="result"><h2>도면 산출 결과</h2><p class="intro">{why} 원본과 비교하지 않고 도면에서 읽은 값으로만 산출했습니다. 항목을 누르면 계산 과정으로 갑니다.</p>'
                    f'<div class="scroll"><table class="matrix sum"><thead><tr><th>무엇을</th><th>규격</th><th class="r">얼마나</th><th>단위</th><th>도면에 없는 값</th></tr></thead><tbody>{body}</tbody></table></div></section>')
        count = {s: sum(1 for r in rows if r["res"]["state"] == s) for s in STATE_ORDER}
        unexplained = sum(1 for r in rows if r["res"]["unexplained"])
        missing = f', 원본에 없음 <b data-count="missing">{count["missing"]}</b>개' if count["missing"] else ""
        verdict = (f'<p class="verdict">공종 {len(rows)}개 중 일치 <b data-count="same">{count["same"]}</b>개, 가정값에 의존한 일치 <b data-count="same_assumed">{count["same_assumed"]}</b>개, 차이 <b data-count="diff">{count["diff"]}</b>개입니다{missing}.'
                   + (f' 차이 중 <b>{unexplained}</b>개는 원인을 규명하지 못했습니다.' if unexplained else ' 차이는 모두 원인을 확인했습니다.') + "</p>")
        caution = ('<div class="callout"><strong>가정값에 의존한 일치는 검증이 아닙니다</strong><p>도면에 없는 값이 들어간 수량입니다. 원본 값을 옮겨 넣었다면 원본과 같은 것이 당연합니다. 가정값의 근거를 따로 확인해야 합니다.</p></div>' if count["same_assumed"] else "")
        body = []
        for r in sorted(rows, key=lambda x: STATE_ORDER[x["res"]["state"]]):
            res = r["res"]
            digits = 0 if r["key"] == "dowel" else 3
            state = res["state"]
            cause = ", ".join(res["cause_ids"]) if res["cause_ids"] else ""
            if res["unexplained"]:
                cause = (cause + " " if cause else "") + "원인 미규명"
            note = " / ".join(t for t in (cause, self.assumed_text(res)) if t)
            original = f'<b class="k-c">{num(r["original"], digits)}</b>' if r["original"] is not None else "-"
            diff_text = "같음" if not r["delta"] else f'{r["delta"]:+,.3f}'
            diff = f'<span class="diff" data-fx="{r["fx"]}-{r["original_name"]}" data-d="3" data-sign="1">{diff_text}</span>' if r["original"] is not None else "-"
            body.append(f'<tr data-diff="1" data-base="{state}"{" class=changed" if state == "diff" else ""}><th scope="row"><a href="#{self.LINKS[r["key"]]}">{r["work"]}</a></th><td>{esc(r["spec"])}</td><td class="r"><b data-fx="{r["fx"]}" data-d="{digits}">{num(r["total"], digits)}</b></td><td class="r">{original}</td><td class="r">{diff}</td><td>{r["unit"]}</td><td><span class="state s-{state}" data-label="{res["label"]}">{res["label"]}</span></td><td class="src">{note}</td></tr>')
        table = '<div class="scroll"><table class="matrix sum"><thead><tr><th>무엇을</th><th>규격</th><th class="r">도면 산출</th><th class="r">원본</th><th class="r">차이</th><th>단위</th><th>판정</th><th>원인, 가정값</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></div>"
        source = f'비교한 원본: {esc(self.audit["original_file"])} ({self.audit["original_pages"]}쪽)'
        return f'<section class="plain" id="compare"><h2>원본 산출서와 비교</h2><p class="meta">{source}. 도면에서 읽은 값으로 따로 계산한 수량과 대조했습니다. 항목을 누르면 계산 과정으로 갑니다.</p>{verdict}{caution}{table}</section>'

    def glossary(self) -> str:
        terms = [("단면", "구조물을 칼로 자른 면의 모양"), ("헌치", "벽과 천장이 만나는 모서리에 더 채운 삼각형 콘크리트"), ("슬래브", "눕혀 놓은 판. 천장판(상부)과 바닥판(하부)"), ("거푸집(유로폼)", "콘크리트가 굳을 때까지 모양을 잡는 판"),
                 ("동바리", "천장판을 아래에서 받치는 임시 기둥"), ("비계", "벽 옆에서 일할 때 딛는 임시 발판"), ("스페이서", "철근과 거푸집 사이를 띄우는 받침"), ("버림콘크리트", "바닥을 평평하게 고르는 얇은 콘크리트"),
                 ("신축이음", "블록 사이의 틈. 온도에 따라 늘고 줄어도 되도록 남겨 둔다"), ("지수판·지수제", "틈이나 경계로 물이 새지 않게 막는 고무판과 재료"), ("다웰바", "이음 양쪽 바닥판을 잇는 굵은 철근"), ("NET과 할증", "NET은 도면에 그려진 순수한 양, 할증은 자투리를 생각해 더하는 여유분")]
        return '<dl class="terms">' + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in terms) + "</dl>"

    def issues_table(self) -> str:
        status = {"CORRECTED": "원인 확인", "CORRECTED_CONFIRM": "원인 확인", "UNEXPLAINED": "미규명"}
        rows = "".join(f'<tr><th scope="row">{i["issue_id"]}</th><td>{status[i["status"]]}</td><td>{esc(i["title"])}</td><td>{esc(i["boq_value"])}</td><td>{esc(i["corrected_value"])}</td><td class="r">{esc(i["delta"] or "-")}</td></tr>' for i in self.audit["issues"])
        return '<div class="scroll"><table class="matrix"><thead><tr><th>번호</th><th>상태</th><th>내용</th><th>원본</th><th>대안</th><th class="r">차이</th></tr></thead><tbody>' + rows + "</tbody></table></div>"

    def css(self) -> str:
        return """
/* 위에 변수표, 아래에 공종별 계산. 도면을 옆에 펴 놓고 위에서 아래로 따라가는 긴 검토 문서. 글자색은 값의 성격만 나타낸다: 붉은색 입력칸(값마다 한 곳), 파란색 인용·계산, 검은색 가정값·규칙. 링크와 제목에는 이 색을 쓰지 않는다. */
:root{--bg:#f6f8fa;--paper:#ffffff;--ink:#16212c;--mute:#566575;--rule:#cfd8e1;--blue:#0f5c94;--blue-soft:#e4eff7;--hit:#d9590f;--hit-soft:#fbe3d3;--conc:#d3d9df;--void:#ffffff;--p1:#a8c7e0;--p2:#b9d6b2;--p3:#e3cf9b;--p4:#d9a2a2;--warn-bg:#fff4dc;--warn-line:#b9770e;--input:#ffffff;--c-in:#c8102e;--c-calc:#0f5c94;--sans:'IBM Plex Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif;--mono:'IBM Plex Mono',Consolas,'Malgun Gothic',monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#10171e;--paper:#18222c;--ink:#e6edf3;--mute:#9fb0bf;--rule:#33414e;--blue:#7dbbe8;--blue-soft:#1d3346;--hit:#ff9352;--hit-soft:#47291a;--conc:#3f4c58;--void:#18222c;--p1:#37617f;--p2:#44693f;--p3:#7a6a39;--p4:#7a4646;--warn-bg:#3a2e16;--warn-line:#e0a944;--input:#10171e;--c-in:#ff8f8f;--c-calc:#7dbbe8;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#10171e;--paper:#18222c;--ink:#e6edf3;--mute:#9fb0bf;--rule:#33414e;--blue:#7dbbe8;--blue-soft:#1d3346;--hit:#ff9352;--hit-soft:#47291a;--conc:#3f4c58;--void:#18222c;--p1:#37617f;--p2:#44693f;--p3:#7a6a39;--p4:#7a4646;--warn-bg:#3a2e16;--warn-line:#e0a944;--input:#10171e;--c-in:#ff8f8f;--c-calc:#7dbbe8;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.65;margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.page{max-width:1000px;margin:0 auto;padding-block:32px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;grid-template-columns:minmax(0,1fr);gap:24px}
.page>*{min-width:0}
header h1{font-size:32px;line-height:1.25;margin:0 0 8px;text-wrap:balance}
header .sta{font-family:var(--mono);color:var(--mute);font-size:14px;letter-spacing:.04em;margin:0}
header p{max-width:66ch;margin:8px 0}
h2{font-size:24px;line-height:1.3;margin:0 0 6px;text-wrap:balance}
h3{font-size:18px;margin:26px 0 8px}
h4{font-size:15px;margin:0 0 6px}
a{color:var(--ink);text-decoration:underline}
var{font-style:normal}
.k-i{color:var(--c-in)}.k-a{color:var(--ink)}.k-c{color:var(--c-calc)}
text.k-i{fill:var(--c-in)}text.k-a{fill:var(--ink)}text.k-c{fill:var(--c-calc)}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:2px 14px;margin:0;padding:0;font-weight:600;font-size:13.5px;flex-basis:100%}
.card,.plain{background:var(--paper);border:1px solid var(--rule);padding:24px;scroll-margin-top:60px;min-width:0}
.intro{font-size:17px;max-width:66ch;margin:0 0 14px}
nav.index{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px}
.status{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--warn-bg);border:1px solid var(--warn-line);padding:8px 14px;display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:14.5px}
.status p{margin:0;flex:1 1 280px;min-width:0}
button{font:inherit;font-size:14px;padding:5px 12px;background:var(--paper);color:var(--ink);border:1px solid var(--ink);cursor:pointer}
.scroll{overflow-x:auto;min-width:0}
table{border-collapse:collapse}
.matrix{width:100%;font-size:14px;font-variant-numeric:tabular-nums;margin:8px 0}
.matrix th,.matrix td{border:1px solid var(--rule);padding:7px 9px;text-align:left;vertical-align:top}
.matrix thead th{background:var(--blue-soft);font-weight:600}
.matrix tbody th{font-weight:500;min-width:170px}
.matrix.narrow{max-width:680px}
.matrix .r,.r{text-align:right}
.fx{display:block;font-weight:400;font-size:12.5px;color:var(--ink);line-height:1.4;margin-top:2px}
.cell .ex{display:block;font-family:var(--mono);font-size:12.5px;color:var(--ink);white-space:nowrap}
.cell b{display:block;font-family:var(--mono);font-size:15px}
.cell b,td[data-fx] b,b[data-fx],b[data-line-val],.calc>b,.big{color:var(--c-calc)}
.none{color:var(--mute)}
.total th,.total td{background:var(--blue-soft);font-weight:600}
.total td b{font-family:var(--mono);font-size:15px}
.sub th,.sub td{background:var(--bg)}
.sum td b{font-family:var(--mono)}
tr.changed th,tr.changed td{background:var(--hit-soft)}
.diff{color:var(--c-calc);font-family:var(--mono);font-weight:600}
tr:not(.changed) .diff{color:var(--mute);font-weight:400}
.calc{font-family:var(--mono);font-size:14px}
.calc .ex{color:var(--ink)}
.line{margin:10px 0}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:5px 16px;padding:8px 12px;margin:10px 0;background:var(--bg);border:1px solid var(--rule);font-size:14px}
.chips b{font-family:var(--mono);font-weight:600}
.chips b.k-a{color:var(--ink)}
.verdict{font-size:17px;max-width:70ch;margin:10px 0}
.verdict b{font-family:var(--mono)}
.state{display:inline-block;padding:0 6px;font-size:13px;border:1px solid var(--rule);white-space:nowrap}
.s-diff{background:var(--hit-soft);border-color:var(--hit)}
.s-same_assumed,.s-missing{background:var(--warn-bg);border-color:var(--warn-line)}
.local{margin:12px 0}
.sum td:nth-child(6){white-space:nowrap}
.vname{font-weight:600}
.vars .src{color:var(--mute);font-size:13px}
.vars.assumed th,.vars.assumed td{background:var(--warn-bg)}
.vars tbody th{min-width:130px}
input.num{width:96px;max-width:100%;padding:3px 6px;font:14px var(--mono);background:var(--input);color:var(--ink);border:1px solid var(--mute)}
input.num.k-i{color:var(--c-in)}
input.num.edited{background:var(--hit-soft);border-color:var(--hit)}
td.in{white-space:nowrap}
.fig{margin:14px 0;max-width:480px}
.fig.wide{max-width:none}
.fig.skew{max-width:560px}
.fig.wing-fig{max-width:520px}
.fig svg{width:100%;height:auto;display:block}
.fig svg.minw{min-width:760px}
.fig svg.minw-s{min-width:420px}
figcaption{font-size:13.5px;color:var(--mute);margin-top:6px;max-width:66ch}
.dim{fill:var(--ink);font:12px var(--sans)}
.dim-strong{fill:var(--ink);font:600 13px var(--sans);text-anchor:middle}
.tag{fill:var(--ink);font:600 14px var(--sans)}
.conc{fill:var(--conc);stroke:var(--ink);stroke-width:1}
.void{fill:var(--void);stroke:var(--ink);stroke-width:1}
.p1{fill:var(--p1);stroke:var(--ink)}.p2{fill:var(--p2);stroke:var(--ink)}.p3{fill:var(--p3);stroke:var(--ink)}.p4{fill:var(--p4);stroke:var(--ink)}
.hit{stroke:var(--hit);stroke-width:4;fill:none}
.hit-fill{fill:var(--hit-soft);stroke:var(--hit);stroke-width:2}
.line-b{fill:none;stroke:var(--blue);stroke-width:3}
.line-c{fill:none;stroke:var(--ink);stroke-width:1.5;stroke-dasharray:6 4}
.wing{stroke:var(--ink);stroke-width:5;fill:none}
.quick{background:var(--bg);border:1px solid var(--rule);padding:12px 14px;margin:12px 0}
.quick ul{margin:0;padding-left:0;list-style:none;display:grid;gap:5px}
.quick p{margin:6px 0}
.meta{font-size:13.5px;color:var(--mute);margin:6px 0}
.callout{background:var(--warn-bg);border:1px solid var(--warn-line);padding:12px 14px;margin:14px 0}
.callout p{margin:4px 0;max-width:66ch}
.final{border-top:2px solid var(--ink);margin-top:18px;padding-top:8px;display:grid;gap:2px}
.final-label{font-size:13.5px;color:var(--mute)}
.final .calc b,.big{font-size:20px;font-family:var(--mono)}
input:focus-visible,a:focus-visible,summary:focus-visible,button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
details{border:1px solid var(--rule);padding:6px 10px;margin:6px 0}
summary{cursor:pointer;font-size:14.5px}
.terms{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 18px;margin:0}
.terms div{min-width:0}
.terms dt{font-weight:600}
.terms dd{margin:0;font-size:14.5px;color:var(--mute)}
.rules{display:grid;gap:10px;padding-left:22px;margin:0}
span.num{font:14px var(--mono)}
@media (max-width:640px){.card,.plain{padding:16px}header h1{font-size:26px}.cell .ex{white-space:normal;overflow-wrap:anywhere}}
@media print{.card,.plain{border-color:#999}.status{position:static}var,.k-i,.k-c,b{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

    @staticmethod
    def engine_js() -> str:
        """화면과 무관한 계산 엔진. 파이썬 모델과 같은 규칙. node로 대조 시험한다."""
        return r"""var QTO=(function(){
var NAME=/^[가-힣A-Za-z_][가-힣A-Za-z0-9_]*/;
function round3(v){return Number((v+(v>=0?1e-9:-1e-9)).toFixed(3))}
var FN={sin:function(d){return Math.sin(d*Math.PI/180)},cos:function(d){return Math.cos(d*Math.PI/180)},tan:function(d){return Math.tan(d*Math.PI/180)},sqrt:Math.sqrt,abs:Math.abs,sign:function(v){return Math.abs(v)<0.0005?0:(v>0?1:-1)},ceil:function(v){return Math.ceil(Number(v.toFixed(6)))}};
function tokens(s){var out=[],i=0;while(i<s.length){var c=s[i];if(c===' '){i++;continue}var m=/^\d+(\.\d+)?/.exec(s.slice(i));if(m){out.push({t:'n',v:parseFloat(m[0])});i+=m[0].length;continue}m=NAME.exec(s.slice(i));if(m){out.push({t:'id',v:m[0]});i+=m[0].length;continue}out.push({t:c});i++}return out}
function evaluate(src,get){var k=tokens(src),p=0;
function expr(){var v=term();while(p<k.length&&(k[p].t==='+'||k[p].t==='-')){var o=k[p++].t;var r=term();v=o==='+'?v+r:v-r}return v}
function term(){var v=pow();while(p<k.length&&(k[p].t==='*'||k[p].t==='/')){var o=k[p++].t;var r=pow();v=o==='*'?v*r:v/r}return v}
function pow(){var v=unary();if(p<k.length&&k[p].t==='^'){p++;return Math.pow(v,pow())}return v}
function unary(){if(k[p].t==='-'){p++;return -unary()}return prim()}
function prim(){var q=k[p++];if(q.t==='n')return q.v;if(q.t==='('){var v=expr();p++;return v}if(q.t==='id'){if(FN[q.v]&&p<k.length&&k[p].t==='('){p++;var a=expr();p++;return FN[q.v](a)}return get(q.v)}throw new Error('수식 오류: '+src)}
return expr()}
function fmtVar(v,d){if(d===-4){var t=v.toFixed(4);return t.slice(-1)==='0'?t.slice(0,-1):t}return v.toFixed(d)}
function pretty(e){return e.replace(/sin\((\d+)\)/g,'sin$1°').replace(/\*/g,' × ').replace(/\//g,' ÷ ').replace(/\+/g,' + ').replace(/([\d)])-([\d(])/g,'$1 − $2')}
function mark(shown,formula,prefix,K){var toks=(formula.match(/[가-힣A-Za-z_][가-힣A-Za-z0-9_]*|\d+(?:\.\d+)?/g)||[]).filter(function(t){return !FN[t]}),i=0;return shown.replace(/\d+(?:\.\d+)?/g,function(m){var t=toks[i++];if(t===undefined||/^\d/.test(t))return m;var k=prefix&&(prefix+'_'+t) in K?K[prefix+'_'+t]:(t in K?K[t]:'c');return '<var class="k-'+k+'">'+m+'</var>'})}
function compute(data,inputs,bars){
inputs=inputs||{};var env={},scoped={},digits={};
function getter(scope,prefix){return function(n){if(scope&&(scope+'|'+n) in scoped)return scoped[scope+'|'+n];if(prefix&&(prefix+'_'+n) in env)return env[prefix+'_'+n];if(n in env)return env[n];throw new Error('변수 없음: '+n)}}
data.vars.forEach(function(v){digits[v.name]=v.digits;if(v.formula){var x=evaluate(v.formula,getter(null,v.prefix));if(v.rnd===3)x=round3(x);else if(v.rnd)x=Number((x+1e-12).toFixed(v.rnd));env[v.name]=x}else{env[v.name]=(v.name in inputs)?inputs[v.name]:v.value}});
var useBars=bars||data.bars,len={};useBars.forEach(function(b){var n='총길이_'+b.code+'_'+b.dia;len[n]=(len[n]||0)+b.L*b.N});Object.keys(len).forEach(function(n){env[n]=len[n];digits[n]=3});
var lines={},expr={};
function numeric(f,scope,prefix){return f.replace(/[가-힣A-Za-z_][가-힣A-Za-z0-9_]*/g,function(n){if(FN[n])return n;var val=getter(scope,prefix)(n);var key=prefix&&(prefix+'_'+n) in digits?prefix+'_'+n:n;return fmtVar(val,key in digits?digits[key]:3)})}
var totals={};
data.lines.forEach(function(l){var v=round3(evaluate(l.formula,getter(l.scope,l.prefix)));expr[l.id]=numeric(l.formula,l.scope,l.prefix);lines[l.id]=v;if(l.name)scoped[l.scope+'|'+l.name]=v;if(l.accum)scoped[l.scope+'|'+l.accum]=round3((scoped[l.scope+'|'+l.accum]||0)+v);totals[l.key]=totals[l.key]||{};totals[l.key][l.scope]=round3((totals[l.key][l.scope]||0)+v)});
totals.pump=totals.concrete;totals.plain_pour=totals.lean;totals.H13={};totals.H16_25={};
var recs=data.records.map(function(r){var net=round3(evaluate(r.net_formula,getter())),gross=round3(evaluate(r.gross_formula,getter()));var k=r.dia==='S13'?'H13':'H16_25';totals[k][r.scope]=round3((totals[k][r.scope]||0)+net);return{net:net,gross:gross,net_expr:numeric(r.net_formula),gross_expr:numeric(r.gross_formula),dia:r.dia}});
function code(s){return data.codes[s]||s}
Object.keys(totals).forEach(function(k){var sum=0,wing=0,has=false;Object.keys(totals[k]).forEach(function(s){var v=totals[k][s];env['합_'+code(s)+'_'+k]=v;sum+=v;if(s.indexOf('WW-')===0){wing+=v;has=true}});if(has)env['군_날개벽_'+k]=round3(wing);env['총_'+k]=round3(sum)});
var tn=0,tg=0,dia={};recs.forEach(function(r){tn+=r.net;tg+=r.gross;dia[r.dia]=dia[r.dia]||{n:0,g:0};dia[r.dia].n=round3(dia[r.dia].n+r.net);dia[r.dia].g=round3(dia[r.dia].g+r.gross)});
env['철근총_net']=round3(tn);env['철근총_gross']=round3(tg);Object.keys(dia).forEach(function(d){env['철근_'+d+'_net']=dia[d].n;env['철근_'+d+'_gross']=dia[d].g});
Object.keys(data.originals).forEach(function(k){env[k]=data.originals[k]});
return{env:env,lines:lines,expr:expr,recs:recs,digits:digits}}
return{compute:compute,evaluate:evaluate,fmtVar:fmtVar,pretty:pretty,mark:mark}})();"""

    @staticmethod
    def ui_js() -> str:
        return r"""(function(){
var data=JSON.parse(document.getElementById('qto-data').textContent),bars=data.bars.map(function(b){return{code:b.code,dia:b.dia,L:b.L,N:b.N}});
var lineById={};data.lines.forEach(function(l){lineById[l.id]=l});
var inputs={},boxes=[].slice.call(document.querySelectorAll('input[data-var]')),barBoxes=[].slice.call(document.querySelectorAll('input[data-bar]'));
function comma(v,d){var t=Math.abs(v).toFixed(d).split('.');t[0]=t[0].replace(/\B(?=(\d{3})+(?!\d))/g,',');return(v<0?'-':'')+t.join('.')}
function run(){var r=QTO.compute(data,inputs,bars),g=function(n){if(n in r.env)return r.env[n];throw new Error(n)};
document.querySelectorAll('[data-line]').forEach(function(c){var id=c.getAttribute('data-line'),v=r.lines[id];c.setAttribute('data-val',v);c.querySelector('.ex').innerHTML=QTO.mark(QTO.pretty(r.expr[id]),lineById[id].formula,lineById[id].prefix,data.kinds);c.querySelector('b').textContent=comma(v,3)});
document.querySelectorAll('[data-line-val]').forEach(function(c){c.textContent=r.lines[c.getAttribute('data-line-val')].toFixed(3)});
document.querySelectorAll('[data-rec]').forEach(function(c){var x=r.recs[+c.getAttribute('data-rec')],p=c.getAttribute('data-part');c.querySelector('.ex').innerHTML=QTO.mark(QTO.pretty(x[p+'_expr']),data.records[+c.getAttribute('data-rec')][p+'_formula'],null,data.kinds);c.querySelector('b').textContent=comma(x[p],3)});
document.querySelectorAll('[data-bar-total]').forEach(function(c){var b=bars[+c.getAttribute('data-bar-total')];c.querySelector('.ex').innerHTML='<var class="k-c">'+b.L.toFixed(3)+'</var> × <var class="k-c">'+b.N+'</var>';c.querySelector('b').textContent=comma(b.L*b.N,3)});
document.querySelectorAll('[data-fx]').forEach(function(c){var f=c.getAttribute('data-fx'),d=parseInt(c.getAttribute('data-d'),10),v=QTO.evaluate(f,g);
if(c.hasAttribute('data-sign')){var z=Math.abs(v)<0.0005,tr=c.closest('tr[data-diff]');c.textContent=z?(tr?'같음':''):((v>0?'+':'')+comma(v,3));if(tr)tr.classList.toggle('changed',!z);return}
var text=d===-4?QTO.fmtVar(v,-4):comma(v,d),ex=c.querySelector('.ex'),b=c.querySelector('b');
if(ex){ex.innerHTML=QTO.mark(QTO.pretty(f.replace(/[가-힣A-Za-z_][가-힣A-Za-z0-9_]*/g,function(n){return QTO.fmtVar(g(n),n in r.digits?r.digits[n]:3)})),f,null,data.kinds)}
if(b)b.textContent=text;else c.textContent=text});
var changed=boxes.filter(function(b){return b.classList.contains('edited')}).length+barBoxes.filter(function(b){return b.classList.contains('edited')}).length;
var s=document.getElementById('edit-status');s.textContent=changed?('도면과 다른 값 '+changed+'개로 계산 중입니다. 내려받는 파일에 이 값이 반영됩니다. 이 화면의 그림과 설명 문구 숫자는 도면 값 기준입니다.'):'지금은 도면에서 읽은 값으로 계산한 결과입니다.';
document.getElementById('reset').hidden=!changed;
var cnt={same:0,same_assumed:0,diff:0,missing:0};
document.querySelectorAll('tr[data-base]').forEach(function(tr){var base=tr.getAttribute('data-base'),d=tr.querySelector('[data-sign]'),st=tr.querySelector('.state'),now=base;
if(d&&changed){var z=Math.abs(QTO.evaluate(d.getAttribute('data-fx'),g))<0.0005;if(!z)now='diff';else if(base==='diff')now='same'}
cnt[now]++;st.textContent=now===base?st.getAttribute('data-label'):(now==='diff'?'차이 (입력값 변경)':'일치 (입력값 변경)');tr.classList.toggle('changed',now==='diff')});
Object.keys(cnt).forEach(function(k){var e=document.querySelector('[data-count="'+k+'"]');if(e)e.textContent=cnt[k]})}
boxes.forEach(function(b){var base=parseFloat(b.defaultValue);b.addEventListener('input',function(){var v=parseFloat(b.value);if(isNaN(v))return;var name=b.getAttribute('data-var');if(Math.abs(v-base)<1e-9){delete inputs[name];b.classList.remove('edited')}else{inputs[name]=v;b.classList.add('edited')}run()})});
barBoxes.forEach(function(b){var base=parseFloat(b.defaultValue);b.addEventListener('input',function(){var v=parseFloat(b.value);if(isNaN(v))return;bars[+b.getAttribute('data-bar')][b.getAttribute('data-field')]=v;b.classList.toggle('edited',Math.abs(v-base)>=1e-9);run()})});
document.getElementById('reset').addEventListener('click',function(){inputs={};boxes.concat(barBoxes).forEach(function(b){b.value=b.defaultValue;b.classList.remove('edited')});bars=data.bars.map(function(b){return{code:b.code,dia:b.dia,L:b.L,N:b.N}});run()});
window.QTO_STATE=function(){var edited=[];bars.forEach(function(b,i){var o=data.bars[i];if(b.L!==o.L||b.N!==o.N)edited.push({i:i,L:b.L,N:b.N})});return{inputs:inputs,bars:edited}};
})();"""

    def data_json(self) -> str:
        m = self.model
        data = {
            "vars": [{k: v[k] for k in ("name", "prefix", "value", "digits", "formula", "rnd")} for v in m["variables"]],
            "lines": [{k: l[k] for k in ("id", "scope", "prefix", "key", "formula", "name", "accum")} for l in m["lines"]],
            "bars": [{k: b[k] for k in ("code", "dia", "L", "N")} for b in m["rebar"]["bars"]],
            "records": [{k: r[k] for k in ("scope", "dia", "net_formula", "gross_formula")} for r in m["rebar"]["records"]],
            "codes": {f"WW-{k}": v for k, v in LOC_CODE.items()}, "originals": self.originals, "kinds": self.kinds,
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    def write_frozen(self) -> Dict[str, Any]:
        """내려받는 문서. 입력칸과 스크립트와 외부 글꼴이 없고, 수량 표와 산출 근거만 싣는다."""
        cards = [self.card_concrete(), self.card_lean(), self.card_form(), self.card_form_simple(), self.card_shoring(), self.card_scaffold(), self.card_spacer(), self.card_waterproof(), self.card_joint(), self.card_construction(), self.card_drain(), self.card_rebar()]
        panel = self.variable_panel()
        project = " · ".join(x for x in (self.cad["project"]["name"], self.cad["project"]["section"], "STA." + self.cad["project"]["station"] if self.cad["project"]["station"] else "") if x)
        body = f"""<div class="page">
<header>
<p class="sta">{esc(project)}</p>
<h1>통로암거 수량산출서</h1>
<ul class="legend" aria-label="글자색 구분"><li class="k-i">붉은색: 입력값</li><li class="k-c">파란색: 인용·계산한 값</li><li class="k-a">검은색: 가정값·규칙</li></ul>
</header>
{self.compare_section()}
<section class="plain" id="vars"><h2>입력값</h2>{panel}</section>
<section class="plain" id="shape"><h2>평면도</h2>{self.plan_svg()}</section>
{"".join(cards)}
<section class="plain" id="derived"><h2>계산 변수</h2>{self.derived_panel()}</section>
</div>"""
        page = ('<meta charset="utf-8"><title>통로암거 수량산출서</title><meta name="viewport" content="width=device-width,initial-scale=1">'
                f"<style>{self.css()}</style>{self.tint_figures(body)}\n")
        with open(self.output_path, "w", encoding="utf-8") as out:
            out.write(page)
        return {"status": "success", "path": self.output_path, "bytes": len(page.encode("utf-8")), "cards": len(cards)}

    def run(self) -> Dict[str, Any]:
        if self.frozen:
            return self.write_frozen()
        cards = [self.card_concrete(), self.card_lean(), self.card_form(), self.card_form_simple(), self.card_shoring(), self.card_scaffold(), self.card_spacer(), self.card_waterproof(), self.card_joint(), self.card_construction(), self.card_drain(), self.card_rebar()]
        titles = re.findall(r'<section class="card" id="([^"]+)"><h2>([^<]+)</h2>', "".join(cards))
        first = ("compare", "원본과 비교") if self.has_original else ("result", "결과")
        nav = (f'<nav class="index" aria-label="공종 바로가기"><a href="#{first[0]}">{first[1]}</a><a href="#vars">입력값</a><a href="#shape">구조물 모양</a><a href="#rules">계산 규칙</a>' + "".join(f'<a href="#{a}">{b}</a>' for a, b in titles)
               + '<a href="#derived">계산 변수</a>' + ('<a href="#changes">차이 원인</a>' if self.has_original else "") + '<a href="#questions">확인 요청</a></nav>')
        open_rows = "".join(f'<tr><th scope="row">{esc(o["item"])}</th><td>{esc(o["note"])}</td></tr>' for o in self.audit["open_items"])
        kinds = {k: sum(1 for v in self.model["variables"] if v["kind"] == k) for k in ("drawing", "assumed", "derived")}
        panel = self.variable_panel()
        missed = [v["name"] for v in self.model["variables"] if v["name"] not in self.placed and v["kind"] != "derived"]
        if missed:
            raise RuntimeError(f"입력칸을 두지 못한 변수: {missed}")
        changes = (f'<section class="plain" id="changes"><h2>차이 원인</h2><p class="intro">원본과 값이나 표기가 다른 {len(self.audit["issues"])}건입니다.</p>{self.issues_table()}</section>' if self.has_original else "")
        body = f"""<div class="page">
<header>
<p class="sta">{esc(" · ".join(x for x in (self.cad["project"]["name"], self.cad["project"]["section"], "STA." + self.cad["project"]["station"] if self.cad["project"]["station"] else "") if x))}</p>
<h1>통로암거 {"대안 " if self.has_original else ""}수량산출서</h1>
<p>도면에서 읽은 값으로 수량을 계산합니다. 도면을 옆에 펴 놓고 위에서 아래로 읽으면 됩니다. 수량 식은 숫자 대신 변수로 쓰고, 계산은 곱하기로 한 덩어리를 구한 뒤 더하고 빼는 것이 전부입니다. 길이 단위는 m입니다.</p>
{nav}
</header>
<div class="status" role="status"><p id="edit-status">지금은 도면에서 읽은 값으로 계산한 결과입니다.</p><button type="button" id="reset" hidden>도면 값으로 되돌리기</button><ul class="legend" aria-label="글자색 구분"><li class="k-i">붉은색: 입력값 (처음 나오는 곳)</li><li class="k-c">파란색: 인용·계산한 값</li><li class="k-a">검은색: 가정값·규칙</li></ul></div>
{self.compare_section()}
<section class="plain" id="vars"><h2>입력값</h2><p class="intro">도면에서 읽은 값 {kinds["drawing"]}개 중 여러 공종에 쓰는 {len(self.common)}개를 여기에 모았습니다. 나머지 {kinds["drawing"] - len(self.common)}개는 처음 쓰는 공종에서 받습니다. 도면에 없는 가정값은 {kinds["assumed"]}개입니다. 값을 바꾸면 아래 수량이 모두 다시 계산됩니다.</p>{panel}</section>
<section class="plain" id="shape"><h2>구조물 모양 먼저 보기</h2><p class="intro">차와 사람이 지나가는 네모난 콘크리트 통로입니다. 세 덩어리(Block)를 이어 만들고, 양 끝 네 귀퉁이에 흙을 막는 날개벽이 붙습니다.</p>{self.plan_svg()}<h3>이 문서에 나오는 말</h3>{self.glossary()}</section>
<section class="plain" id="rules"><h2>표 읽는 법과 계산 규칙</h2><ol class="rules"><li><strong>표 읽는 법.</strong> 왼쪽이 변수식이고, 오른쪽 칸은 그 변수에 값을 넣은 계산입니다.</li><li><strong>글자색.</strong> <span class="k-i">붉은색</span>은 입력값으로, 그 값을 받는 칸(문서에서 처음 나오는 곳)에만 씁니다. 그 뒤에 인용하거나 계산한 값은 <span class="k-c">파란색</span>입니다. 검은색(어두운 화면에서는 흰색)은 도면에 근거가 없는 값으로, 가정값, 철근 규칙, 식 안의 고정 숫자입니다.</li><li><strong>넓이와 부피.</strong> 넓이 = 가로 × 세로. 부피 = 단면 넓이 × 길이.</li><li><strong>비스듬한 블록.</strong> 왼쪽과 오른쪽 길이가 다르면 평균길이를 씁니다.</li><li><strong>반올림.</strong> 줄마다 소수 셋째 자리로 맞춘 뒤 더합니다. 그래서 다른 방법으로 검산하면 0.001 정도 차이가 날 수 있습니다.</li></ol>{self.skew_svg()}</section>
{''.join(cards)}
<section class="plain" id="derived"><h2>계산 변수</h2><p class="intro">입력값에서 자동으로 계산되는 중간 값입니다.</p>{self.derived_panel()}</section>
{changes}
<section class="plain" id="questions"><h2>설계자에게 확인할 것</h2><p class="intro">도면만으로 판단할 수 없는 항목입니다.</p><div class="scroll"><table class="matrix"><tbody>{open_rows}</tbody></table></div><p class="meta">값을 고친 내용은 내려받는 파일에 반영되며, 이 화면을 닫으면 저장되지 않습니다.</p></section>
</div>"""
        head = ('<meta charset="utf-8"><title>통로암거 수량산출서</title><meta name="claude:viewport-fit-sides" content="cover">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600&display=swap">')
        body = self.tint_figures(body)
        page = (f'{head}<style>{self.css()}</style>{body}<script type="application/json" id="qto-data">{self.data_json()}</script>'
                f'<script id="qto-engine">{self.engine_js()}</script><script id="qto-ui">{self.ui_js()}</script>\n')
        with open(self.output_path, "w", encoding="utf-8") as out:
            out.write(page)
        return {"status": "success", "path": self.output_path, "bytes": len(page.encode("utf-8")), "cards": len(cards)}


if __name__ == "__main__":
    _ = math
    print(ReadableBoqAgent().run())
