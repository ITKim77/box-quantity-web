"""
Agent CAD Parser
DXF 14종을 ezdxf로 읽어 치수 문자, 콘크리트 선형, 철근 재료표를 실제 추출한다.
값을 찾지 못하면 기본값으로 대체하지 않고 CadParseError로 중단한다.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

import ezdxf

Text = Dict[str, Any]
Seg = Tuple[float, float, float, float]


class CadParseError(RuntimeError):
    """도면에서 필수 값을 찾지 못한 경우."""


def clean(raw: str) -> str:
    s = re.sub(r"\\[A-Za-z][^;\\]*;", "", raw or "").replace("\\P", " ")
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"%%[Dd]", "°", s)
    s = re.sub(r"%%[Cc]", "Φ", s)
    return s.strip()


REQUIRED_HEADINGS = {"일반도 (1)": ["표준단면도", "평면도", "종단면도", "신축이음 상세", "상부 슬래브", "난간벽 상세"], "일반도 (2)": ["날개벽 시점 정면도", "시점부 좌측 단면 A-A", "시점부 우측 단면 A-A", "배수상세 재료표"]}


def sheet_headings(sheet: Dict[str, Any]) -> set:
    return {t["t"].replace(" ", "") for t in sheet["texts"] if t["kind"] == "TEXT" and t["h"] >= 350}


def assign_keys(sheets: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """파일 이름이 아니라 도면 내용으로 역할을 정한다. 일반도 2종을 빼면 나머지는 파일 이름 순서로 구조도 번호를 준다."""
    keys: Dict[str, str] = {}
    for path, sheet in sheets.items():
        heads = sheet_headings(sheet)
        for key, required in REQUIRED_HEADINGS.items():
            if all(h.replace(" ", "") in heads for h in required):
                keys[path] = key
    natural = lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", os.path.basename(p))]  # noqa: E731
    rest = sorted((p for p in sheets if p not in keys), key=natural)
    for n, path in enumerate(rest, 1):
        match = re.search(r"구조도 \((\d+)\)", path)
        keys[path] = f"구조도 ({match.group(1)})" if match else f"구조도 ({n})"
    return keys


def sheet_sort(key: str) -> Tuple[int, int]:
    found = re.search(r"\((\d+)\)", key)
    if not found:
        raise CadParseError(f"도면 키 해석 불가: {key}")
    return (0 if key.startswith("일반도") else 1, int(found.group(1)))


def number(text: str) -> Optional[float]:
    return float(text) if re.fullmatch(r"\d+(\.\d+)?", text) else None


def dim_to_m(text: str) -> float:
    """도면 치수 표기: 1.222 는 m, 691 은 mm."""
    return float(text) if "." in text else float(text) / 1000.0


def read_sheet(path: str) -> Dict[str, Any]:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    texts: List[Text] = []
    segs: List[Tuple[str, Seg]] = []
    frame_x: List[float] = []
    frame_y: List[float] = []

    def note_frame(layer: str, *points: Tuple[float, float]) -> None:
        if layer.startswith("CX-BORD"):
            for x, y in points:
                frame_x.append(x)
                frame_y.append(y)

    dimension_entities = 0
    for ent in msp:
        kind = ent.dxftype()
        layer = ent.dxf.layer
        if kind == "DIMENSION":
            dimension_entities += 1
        if kind == "TEXT":
            x, y = ent.dxf.insert.x, ent.dxf.insert.y
            texts.append({"t": clean(ent.dxf.text), "x": x, "y": y, "h": ent.dxf.height, "layer": layer, "kind": "TEXT", "style": ent.dxf.style, "rot": ent.dxf.get("rotation", 0.0)})
            note_frame(layer, (x, y))
        elif kind == "MTEXT":
            x, y = ent.dxf.insert.x, ent.dxf.insert.y
            texts.append({"t": clean(ent.text), "x": x, "y": y, "h": ent.dxf.char_height, "layer": layer, "kind": "MTEXT", "style": ent.dxf.style})
        elif kind == "LINE":
            a, b = ent.dxf.start, ent.dxf.end
            segs.append((layer, (a.x, a.y, b.x, b.y)))
            note_frame(layer, (a.x, a.y), (b.x, b.y))
        elif kind == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in ent.get_points()]
            pairs = list(zip(pts, pts[1:]))
            if ent.closed and pts:
                pairs.append((pts[-1], pts[0]))
            for p, q in pairs:
                segs.append((layer, (p[0], p[1], q[0], q[1])))
            note_frame(layer, *pts)
        elif kind == "INSERT":
            for att in ent.attribs:
                ax, ay = att.dxf.insert.x, att.dxf.insert.y
                texts.append({"t": clean(att.dxf.text), "x": ax, "y": ay, "h": att.dxf.height, "layer": att.dxf.layer, "kind": "ATTRIB", "style": att.dxf.style})
                note_frame(att.dxf.layer, (ax, ay))
    if not frame_x:
        raise CadParseError("도곽 레이어(CX-BORD)가 없습니다")
    return {
        "texts": texts, "segs": segs,
        "frame": [min(frame_x), max(frame_x), min(frame_y), max(frame_y)],
        "dimension_entities": dimension_entities,
        "styles": sorted(s.dxf.name for s in doc.styles),
    }


def find_one(texts: Iterable[Text], needle: str) -> Text:
    hits = [t for t in texts if t["t"].replace(" ", "") == needle.replace(" ", "")]
    if not hits:
        raise CadParseError(f"문자 미검출: {needle}")
    return hits[0]


def in_box(t: Text, x0: float, x1: float, y0: float, y1: float) -> bool:
    return x0 <= t["x"] <= x1 and y0 <= t["y"] <= y1


def section_window(segs: List[Seg], hx: float, hy: float) -> List[Seg]:
    """제목 아래에서 가장 가까운 큰 도형(연결된 선 묶음)을 단면으로 잡고, 그 둘레의 선을 모은다. 크기가 달라져도 따라간다."""
    parent = list(range(len(segs)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends: Dict[Tuple[int, int], int] = {}
    for i, s in enumerate(segs):
        for point in ((round(s[0]), round(s[1])), (round(s[2]), round(s[3]))):
            if point in ends:
                parent[root(i)] = root(ends[point])
            else:
                ends[point] = i
    groups: Dict[int, List[Seg]] = {}
    for i, s in enumerate(segs):
        groups.setdefault(root(i), []).append(s)
    best: Optional[Tuple[float, Tuple[float, float, float, float]]] = None
    for group in groups.values():
        x0, x1 = min(min(s[0], s[2]) for s in group), max(max(s[0], s[2]) for s in group)
        y0, y1 = min(min(s[1], s[3]) for s in group), max(max(s[1], s[3]) for s in group)
        if y1 > hy or y1 - y0 < 1500 or x1 - x0 < 1500:
            continue
        gap_x = max(x0 - hx, hx - x1, 0.0)
        distance = (gap_x ** 2 + (hy - y1) ** 2) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, (x0, x1, y0, y1))
    if best is None:
        raise CadParseError("일반도(1) 표준단면도: 제목 아래에서 콘크리트 단면 선을 찾지 못했습니다")
    x0, x1, y0, y1 = best[1]
    margin = 1000.0
    return [s for s in segs if x0 - margin <= min(s[0], s[2]) and max(s[0], s[2]) <= x1 + margin and y0 - margin <= min(s[1], s[3]) and max(s[1], s[3]) <= min(y1 + margin, hy)]


def measure_section(sheet: Dict[str, Any], heading: str = "표준단면도") -> Dict[str, Any]:
    """표준단면도 콘크리트 선형(CS-CONC-MAJR)에서 제원을 실측한다."""
    head = find_one(sheet["texts"], heading)
    window = section_window([s for lay, s in sheet["segs"] if lay == "CS-CONC-MAJR"], head["x"], head["y"])
    verticals = [s for s in window if abs(s[0] - s[2]) < 0.5 and abs(s[1] - s[3]) >= 300]
    horizontals = [s for s in window if abs(s[1] - s[3]) < 0.5 and abs(s[0] - s[2]) >= 300]
    diagonals = [s for s in window if abs(s[0] - s[2]) >= 100 and abs(abs(s[0] - s[2]) - abs(s[1] - s[3])) < 0.5]
    if not verticals or not horizontals:
        raise CadParseError("일반도(1) 표준단면도: 콘크리트 선을 찾지 못했습니다")

    height = max(abs(s[1] - s[3]) for s in verticals)
    outer = [s for s in verticals if abs(abs(s[1] - s[3]) - height) < 0.5]
    x_left = min(s[0] for s in outer)
    x_right = max(s[0] for s in outer)
    y_top = max(max(s[1], s[3]) for s in outer)
    y_bot = min(min(s[1], s[3]) for s in outer)

    inner_v = [s for s in verticals if x_left + 1 < s[0] < x_right - 1 and abs(s[1] - s[3]) < height - 1]
    wall_l = min(s[0] for s in inner_v)
    wall_r = max(s[0] for s in inner_v)
    inner_h = [s for s in horizontals if y_bot + 1 < s[1] < y_top - 1]
    y_soffit = max(s[1] for s in inner_h)
    y_floor = min(s[1] for s in inner_h)
    soffit_w = max(abs(s[0] - s[2]) for s in inner_h if abs(s[1] - y_soffit) < 0.5)
    floor_w = max(abs(s[0] - s[2]) for s in inner_h if abs(s[1] - y_floor) < 0.5)

    top_h = [d for d in diagonals if abs(max(d[1], d[3]) - y_soffit) < 0.5 or abs(min(d[1], d[3]) - y_soffit) < 0.5]
    bot_h = [d for d in diagonals if abs(max(d[1], d[3]) - y_floor) < 0.5 or abs(min(d[1], d[3]) - y_floor) < 0.5]
    haunch_w = abs(top_h[0][0] - top_h[0][2]) if top_h else 0.0
    haunch_h = abs(top_h[0][1] - top_h[0][3]) if top_h else 0.0

    lean = [s for s in horizontals if s[1] < y_bot - 1]
    lean_y = min(s[1] for s in lean)
    lean_w = max(abs(s[0] - s[2]) for s in lean)

    near = [t for t in sheet["texts"] if t["kind"] == "TEXT"
            and in_box(t, x_left - 2500, x_right + 2500, lean_y - 2500, y_top + 1500)]
    return {
        "total_width_mm": round(x_right - x_left, 1),
        "total_height_mm": round(y_top - y_bot, 1),
        "inner_width_mm": round(wall_r - wall_l, 1),
        "inner_height_mm": round(y_soffit - y_floor, 1),
        "wall_t_mm": round(wall_l - x_left, 1),
        "top_slab_t_mm": round(y_top - y_soffit, 1),
        "bot_slab_t_mm": round(y_floor - y_bot, 1),
        "soffit_width_mm": round(soffit_w, 1),
        "floor_width_mm": round(floor_w, 1),
        "haunch_w_mm": round(haunch_w, 1),
        "haunch_h_mm": round(haunch_h, 1),
        "haunch_count_top": len(top_h),
        "haunch_count_bottom": len(bot_h),
        "lean_width_mm": round(lean_w, 1),
        "lean_t_mm": round(y_bot - lean_y, 1),
        "section_box": {"x0": x_left, "x1": x_right, "y0": y_bot, "y1": y_top},
        "levels": {"y_soffit": y_soffit, "y_floor": y_floor, "wall_l": wall_l, "wall_r": wall_r},
        "text_dims": sorted(t["t"] for t in near if re.fullmatch(r"[\d.]+|\d+X\d+", t["t"])),
    }


def parse_plan(sheet: Dict[str, Any]) -> Dict[str, Any]:
    texts = sheet["texts"]
    collected: Dict[str, List[Tuple[float, float, str]]] = {}
    labels = [t for t in texts if re.fullmatch(r"\((?:BLOCK|Block)\d\)", t["t"])]
    for lab in labels:
        digit = re.search(r"\d", lab["t"])
        if not digit:
            raise CadParseError(f"블록 라벨 해석 불가: {lab['t']}")
        val = [t for t in texts if abs(t["x"] - lab["x"]) < 900 and 200 < t["y"] - lab["y"] < 600 and number(t["t"]) is not None]
        if not val:
            raise CadParseError(f"블록 길이 미검출: {lab['t']}")
        collected.setdefault("B" + digit.group(0), []).append((lab["y"], float(val[0]["t"]), lab["t"]))
    blocks: Dict[str, Dict[str, float]] = {}
    for name, values in sorted(collected.items()):
        ordered = sorted(values, key=lambda v: -v[0])
        plan_vals = [v for v in ordered if "BLOCK" in v[2]]
        long_vals = [v for v in ordered if "Block" in v[2]]
        blocks[name] = {"left": plan_vals[0][1], "right": plan_vals[1][1], "avg": long_vals[0][1]}
    # 총연장은 평면·종단 보기에서 가장 큰 m 단위 치수, 이음 간격은 가장 많이 나오는 100mm 미만 치수다.
    dims = view_dims(sheet, "평면도") + view_dims(sheet, "종단면도")
    totals = [float(t["t"]) for t in dims if "." in t["t"]]
    gaps = Counter(t["t"] for t in dims if "." not in t["t"] and float(t["t"]) < 100)
    angles = Counter(t["t"] for t in texts if re.fullmatch(r"\d+°", t["t"]))
    if not gaps or not totals or not angles:
        raise CadParseError("일반도(1) 평면도: 총연장, 이음 간격, 사각 치수 중 찾지 못한 값이 있습니다")
    return {
        "blocks": blocks,
        "joint_gap_mm": float(gaps.most_common(1)[0][0]),
        "joint_count": len(blocks) - 1,
        "total_length_m": max(totals),
        "skew_deg": float(angles.most_common(1)[0][0].rstrip("°")),
    }


def parse_misc(gen1: Dict[str, Any], gen2: Dict[str, Any]) -> Dict[str, Any]:
    t1, t2 = gen1["texts"], gen2["texts"]
    dowel_re = re.compile(r"[ΦφDH]\s*(\d+)\s*C\.?\s*T\.?\s*C\.?\s*(\d+)\s*L\s*=\s*(\d+)")
    match = next((m for m in (dowel_re.search(t["t"]) for t in t1) if m), None)
    if not match:
        raise CadParseError("일반도(1) 시공이음 상세: 다웰바 표기(예: Φ지름 C.T.C간격 L=길이)를 찾지 못했습니다")
    pipe_re = re.compile(r"[ΦφD]\s*(\d+)\s*\(\s*L\s*=\s*(\d+)\s*~\s*(\d+)\s*\)")
    pipes = [t["t"] for t in t2 if ("P.V.C" in t["t"].upper() or "PVC" in t["t"].upper()) and pipe_re.search(t["t"])]
    pipe = pipes[0] if pipes else ""
    pm = pipe_re.search(pipe)
    if not pm:
        raise CadParseError("일반도(2) 배수상세: 배수관 표기(예: P.V.C Φ지름(L=최대~최소))를 찾지 못했습니다")
    head = next((t for t in t2 if t["t"].replace(" ", "") == "품명"), None)
    if head is None:
        raise CadParseError("일반도(2) 배수상세 재료표: '품명' 머리글을 찾지 못했습니다")
    material = [t for t in t2 if in_box(t, head["x"] - 1000, head["x"] + 9000, head["y"] - 2000, head["y"] - 200)]
    ea = next((t["t"] for t in material if t["t"].endswith("EA")), None)
    fabric = next((t["t"] for t in material if t["t"].endswith("장")), None)
    fabric_spec = next((t["t"] for t in material if re.fullmatch(r"\d+\s*[Xx×]\s*\d+", t["t"])), None)
    if not ea or not fabric or not fabric_spec:
        raise CadParseError("일반도(2) 배수상세 재료표: 배수관 개수, 부직포 크기, 부직포 장수 중 찾지 못한 값이 있습니다")
    fw, fh = re.findall(r"\d+", fabric_spec)
    dims2 = Counter(t["t"] for t in t2 if t["layer"] == "CS-DIMT" and number(t["t"]))
    return {
        "dowel": {"dia": f"H{match.group(1)}", "ctc_mm": float(match.group(2)), "length_mm": float(match.group(3)),
                  "cap_noted": any(t["t"].replace(" ", "") == "DOWELCAP" for t in t1),
                  "paint_noted": any("녹막이" in t["t"] for t in t1)},
        "drain_pipe": {"spec": pipe, "dia_mm": float(pm.group(1)), "len_max_mm": float(pm.group(2)),
                       "len_min_mm": float(pm.group(3)), "ea_per_location": int(re.findall(r"\d+", ea)[0])},
        "filter_fabric": {"w_mm": float(fw), "h_mm": float(fh), "ea_per_location": int(re.findall(r"\d+", fabric)[0])},
        "wing_dim_counts": dict(dims2),
    }


def view_dims(sheet: Dict[str, Any], heading: str) -> List[Text]:
    """제목이 붙은 보기(view)에 속한 치수 문자. 치수 문자는 위쪽에 있는 가장 가까운 제목의 보기로 본다."""
    heads = [t for t in sheet["texts"] if t["kind"] == "TEXT" and t["h"] >= 350 and re.search("[가-힣]", t["t"])]
    me = find_one(heads, heading)
    out: List[Text] = []
    for t in sheet["texts"]:
        if t["kind"] != "TEXT" or t["layer"] != "CS-DIMT" or number(t["t"]) is None:
            continue
        above = [h for h in heads if h["y"] > t["y"]]
        if above and min(above, key=lambda h: (h["x"] - t["x"]) ** 2 + (h["y"] - t["y"]) ** 2) is me:
            out.append(t)
    return out


def lines_of(texts: List[Text], axis: str, tol: float = 200.0) -> List[List[Text]]:
    """같은 줄(axis='y') 또는 같은 열(axis='x')의 문자끼리 묶는다. 작은 좌표부터."""
    groups: List[List[Text]] = []
    for t in sorted(texts, key=lambda v: v[axis]):
        if groups and abs(groups[-1][-1][axis] - t[axis]) <= tol:
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


def split_dims(texts: List[Text]) -> Tuple[List[Text], List[Text]]:
    """가로 치수와 세로 치수로 나눈다."""
    return [t for t in texts if abs(t.get("rot", 0.0)) < 1], [t for t in texts if abs(abs(t.get("rot", 0.0)) - 90) < 1]


def need(condition: bool, message: str) -> None:
    if not condition:
        raise CadParseError(message)


def record(sheet: str, heading: str, label: str, text: Text) -> Dict[str, Any]:
    return {"value_m": dim_to_m(text["t"]), "text": text["t"], "sheet": sheet, "heading": heading, "label": label}


def read_anchored_dims(raw: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """날개벽, 난간벽, 방지벽 치수를 보기 안의 줄과 열 순서로 읽고 서로 대조한다. 값이나 좌표를 코드에 적지 않는다."""
    out: Dict[str, Dict[str, Any]] = {}
    gen1, gen2 = raw["일반도 (1)"], raw["일반도 (2)"]

    # 날개벽 정면도: 좌우 날개벽이 나란히 그려져 있어 왼쪽 것을 읽는다.
    # 아래 첫 줄의 맨 왼쪽이 전체 길이, 그 위 줄의 왼쪽 둘이 경사와 평평. 바깥 열이 전체 높이, 안쪽 열은 위부터 끝, 경사 구간, 받침.
    heading = "날개벽 시점 정면도"
    horiz, vert = split_dims(view_dims(gen2, heading))
    rows, cols = lines_of(horiz, "y"), lines_of(vert, "x")
    need(len(rows) >= 2 and len(rows[1]) >= 2, f"일반도(2) {heading}: 가로 치수 배치를 해석하지 못했습니다 (아래 첫 줄 전체 길이, 그 위 줄에 구간 2개 필요)")
    need(len(cols) >= 2 and len(cols[0]) == 1 and len(cols[1]) == 3, f"일반도(2) {heading}: 세로 치수 배치를 해석하지 못했습니다 (바깥 열 전체 높이, 안쪽 열에 구간 3개 필요)")
    slope, flat = sorted(rows[1], key=lambda t: t["x"])[:2]
    tip, low, base = sorted(cols[1], key=lambda t: -t["y"])
    wing = {"날개전체길이": (min(rows[0], key=lambda t: t["x"]), "날개벽 전체 길이"), "날개경사길이": (slope, "날개벽 경사 구간 길이"), "날개평평길이": (flat, "날개벽 평평한 구간 길이"),
            "날개전체높이": (cols[0][0], "날개벽 뿌리 높이"), "날개끝높이": (tip, "날개벽 끝 높이"), "날개아래높이": (low, "날개벽 경사 구간 높이"), "날개받침높이": (base, "날개벽 아래 받침 높이")}
    for name, (text, label) in wing.items():
        out[name] = record("일반도 (2)", heading, label, text)
    length_gap = out["날개경사길이"]["value_m"] + out["날개평평길이"]["value_m"] - out["날개전체길이"]["value_m"]
    height_gap = out["날개끝높이"]["value_m"] + out["날개아래높이"]["value_m"] - out["날개전체높이"]["value_m"]
    need(abs(length_gap) < 0.002, f"일반도(2) {heading}: 경사 {out['날개경사길이']['text']} + 평평 {out['날개평평길이']['text']} 이 전체 길이 {out['날개전체길이']['text']} 와 맞지 않습니다")
    need(abs(height_gap) < 0.002, f"일반도(2) {heading}: 끝 높이 {out['날개끝높이']['text']} + 경사 구간 {out['날개아래높이']['text']} 이 전체 높이 {out['날개전체높이']['text']} 와 맞지 않습니다")

    # 날개벽 단면: 좌우 단면의 맨 위 가로 치수가 두께
    heading = "시점부 좌측 단면 A-A"
    horiz, _ = split_dims(view_dims(gen2, heading) + view_dims(gen2, "시점부 우측 단면 A-A"))
    rows = lines_of(horiz, "y")
    need(bool(rows), f"일반도(2) {heading}: 맨 위 가로 치수(날개벽 두께)를 찾지 못했습니다")
    need(len({t["t"] for t in rows[-1]}) == 1, f"일반도(2) {heading}: 좌우 단면의 날개벽 두께가 다릅니다 ({sorted(t['t'] for t in rows[-1])})")
    out["날개두께"] = record("일반도 (2)", heading, "날개벽 두께", min(rows[-1], key=lambda t: t["x"]))

    # 난간벽 상세: 맨 위 가로 치수가 폭, 가장 오른쪽 세로 치수가 난간벽 높이
    heading = "난간벽 상세"
    horiz, vert = split_dims(view_dims(gen1, heading))
    rows, cols = lines_of(horiz, "y"), lines_of(vert, "x")
    need(bool(rows) and bool(cols), f"일반도(1) {heading}: 폭과 높이 치수를 찾지 못했습니다")
    out["난간벽폭"] = record("일반도 (1)", heading, "난간벽 폭", min(rows[-1], key=lambda t: t["x"]))
    out["난간벽높이"] = record("일반도 (1)", heading, "난간벽 높이", max(cols[-1], key=lambda t: t["y"]))

    # 신축이음 상세의 상부 슬래브 그림: 맨 위 줄의 가장 왼쪽 가로 치수가 방지벽 폭, 가장 위 세로 치수가 방지벽 높이
    heading = "상부 슬래브"
    horiz, vert = split_dims(view_dims(gen1, heading))
    rows = lines_of(horiz, "y")
    need(bool(rows) and bool(vert), f"일반도(1) 신축이음 상세 {heading}: 우수유입방지벽 치수를 찾지 못했습니다")
    out["방지벽폭"] = record("일반도 (1)", heading, "우수유입방지벽 폭", min(rows[-1], key=lambda t: t["x"]))
    out["방지벽높이"] = record("일반도 (1)", heading, "우수유입방지벽 높이", max(vert, key=lambda t: t["y"]))
    return out


def parse_schedule(sheet: Dict[str, Any], key: str) -> Dict[str, Any]:
    """철근 재료표(CS-TABL-TEX2)를 행 단위로 읽는다."""
    rows = [t for t in sheet["texts"] if t["layer"] == "CS-TABL-TEX2"]
    heads = sorted(t["x"] for t in rows if t["t"].replace(" ", "") == "기호")
    if not heads:
        raise CadParseError(f"재료표 머리글 미검출: {key}")
    tables: List[List[Text]] = [[] for _ in heads]
    for t in rows:
        index = max((i for i, h in enumerate(heads) if t["x"] >= h - 1200), default=0)
        tables[index].append(t)
    bars: List[Dict[str, Any]] = []
    subtotals: List[Dict[str, Any]] = []
    total: Dict[str, Any] = {}
    for table in tables:
        by_y: Dict[int, List[Text]] = {}
        for t in table:
            by_y.setdefault(round(t["y"] / 60), []).append(t)
        current: Optional[str] = None
        for y in sorted(by_y, reverse=True):
            cells = sorted(by_y[y], key=lambda t: t["x"])
            values = [c["t"] for c in cells]
            label = values[0].replace(" ", "")
            if label == "소계":
                gm = re.fullmatch(r"([\d.]+)\((\d+)%\)", values[4])
                if not gm:
                    raise CadParseError(f"소계 할증 표기 해석 불가: {values}")
                subtotals.append({"dia": current, "length_m": float(values[1]), "unit_weight": float(values[2]),
                                  "net_t": float(values[3]), "gross_t": float(gm.group(1)), "rate": int(gm.group(2)) / 100})
            elif label == "총계":
                total = {"length_m": float(values[1]), "net_t": float(values[2]), "gross_t": float(values[3])}
            elif len(values) >= 5 and re.fullmatch(r'S\d+|"', values[1]):
                if values[1] != '"':
                    current = values[1]
                bars.append({"mark": values[0], "dia": current, "length_m": dim_to_m(values[2]), "count": int(values[3]),
                             "total_length_m": float(values[4]), "text_x": cells[0]["x"], "text_y": cells[0]["y"]})
    if not bars or not subtotals or not total:
        raise CadParseError(f"재료표 해석 실패: {key}")

    # 철근 상세 라벨(L=, N=)
    labels: List[List[float]] = []
    ls = [t for t in sheet["texts"] if t["t"].startswith("L=") and t["layer"] != "CS-TABL-TEX2"]
    ns = [t for t in sheet["texts"] if t["t"].startswith("N=") and t["layer"] != "CS-TABL-TEX2"]
    for lab in ls:
        partner = [n for n in ns if abs(n["y"] - lab["y"]) < 30 and 0 < n["x"] - lab["x"] < 4000]
        if partner:
            labels.append([dim_to_m(lab["t"][2:]), int(partner[0]["t"][2:])])
    return {"bars": bars, "subtotals": subtotals, "total": total, "detail_labels": sorted(labels)}


def classify_sheets(sheets: Dict[str, Dict[str, Any]]) -> None:
    """표제 속성과 제목 문자에서 도면 역할과 소속 블록을 판별한다."""
    for key in sorted(sheets, key=sheet_sort):
        sheet = sheets[key]
        headings = sorted({t["t"] for t in sheet["texts"] if t["kind"] == "TEXT" and t["h"] >= 350 and re.search("[가-힣]", t["t"])})
        attrs = [t["t"] for t in sheet["texts"] if t["kind"] == "ATTRIB" and t["t"].startswith("(STA")]
        if not attrs:
            raise CadParseError(f"표제 속성 미검출: {key}")
        norm = {h.replace(" ", "") for h in headings}
        found = re.search(r"BLOCK (\d)", attrs[0])
        block: Optional[str] = f"B{found.group(1)}" if found else ("WW" if "시점" in attrs[0] else None)
        roles: List[str] = []
        if key == "일반도 (1)":
            roles.append("암거 본체 일반도(평면·종단·표준단면·이음 상세)")
        if key == "일반도 (2)":
            roles.append("날개벽 일반도(평면·정면·단면·배수·방수 상세)")
        if "벽체전면도" in norm:
            roles.append("날개벽 배근도")
        if key.startswith("구조도") and "표준단면도" in norm:
            roles.append("표준단면·주철근 조립도")
        if any("슬래브-" in h for h in norm):
            roles.append("상·하부 슬래브 배근도")
        if any(h.endswith("벽체-1단") for h in norm):
            roles.append("좌·우 벽체 배근도")
        if "철근재료표" in norm:
            roles.append("철근 상세·재료표")
        if not roles:
            raise CadParseError(f"도면 역할 판별 실패: {key}")
        sheet.update({"headings": headings, "title_attr": attrs[0], "role": " + ".join(roles), "block": block})


def read_project(sheet: Dict[str, Any]) -> Dict[str, str]:
    """표제의 공사명, 공구, 측점을 읽는다. 없으면 빈 문자열로 둔다."""
    attrs = [t["t"] for t in sheet["texts"] if t["kind"] == "ATTRIB"]
    station = next((m.group(1) for m in (re.search(r"STA\.?\s*([\d+]+)", a, re.I) for a in attrs) if m), "")
    return {"name": next((a for a in attrs if a.endswith("공사")), ""), "section": next((a for a in attrs if "공구" in a), ""), "station": station}


class CadParserAgent:
    def __init__(self, docs_dir: str = "docs", output_path: str = "data/cad_extracted.json") -> None:
        self.docs_dir = docs_dir
        self.output_path = output_path

    @staticmethod
    def check_structure(plan: Dict[str, Any], rebar: Dict[str, Any]) -> None:
        """지원하는 구조물 구성인지 확인한다. 맞지 않으면 틀린 수량을 내지 않고 이유를 알려 준다."""
        blocks = sorted(plan["blocks"])
        need(blocks == ["B1", "B2", "B3"], f"블록 {len(blocks)}개 구조물입니다. 현재는 블록 3개 구조물만 산출합니다")
        for name in blocks:
            need(any(s["block"] == name for s in rebar.values()), f"Block {name[1]}의 철근 재료표 도면이 없습니다")
        wings = [s for s in rebar.values() if s["block"] == "WW"]
        locations = sorted(loc for s in wings for loc in s["wing_locations"])
        need(len(wings) == 2 and locations == sorted(["시점좌", "시점우", "종점좌", "종점우"]), f"날개벽 철근 재료표는 2장이고 날개벽 4곳을 나눠 맡아야 합니다 (도면 {len(wings)}장, 위치 {locations})")
        need(len({s["wing_angle_deg"] for s in wings}) == 2, "날개벽 각도가 2종이어야 합니다. 직각 암거처럼 각도가 1종인 구조물은 아직 산출하지 않습니다")

    def run(self) -> Dict[str, Any]:
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        files = sorted(glob.glob(os.path.join(self.docs_dir, "*.dxf")))
        if not files:
            raise CadParseError(f"DXF 도면이 없습니다: {self.docs_dir}")
        loaded: Dict[str, Dict[str, Any]] = {}
        problems: List[str] = []
        for path in files:
            try:
                loaded[path] = read_sheet(path)
            except CadParseError as exc:
                problems.append(f"{os.path.basename(path)}: 통로암거 도면 양식이 아닙니다 ({exc})")
            except Exception as exc:  # noqa: BLE001 - ezdxf 구조 오류, 입출력 오류를 사용자 메시지로 바꾼다
                problems.append(f"{os.path.basename(path)}: DXF로 읽지 못했습니다 ({type(exc).__name__})")
        if problems:
            raise CadParseError("; ".join(problems))
        key_of = assign_keys(loaded)
        raw = {key_of[f]: loaded[f] for f in loaded}
        for key, required in REQUIRED_HEADINGS.items():
            if key not in raw:
                seen = set().union(*[sheet_headings(v) for v in raw.values()])
                absent = [h for h in required if h.replace(" ", "") not in seen]
                raise CadParseError(f"통로암거 {key.replace(' ', '')}에 해당하는 도면이 없습니다. 찾지 못한 제목: {', '.join(absent) or '같은 도면에 모두 있어야 합니다'}")
        if len(set(key_of.values())) != len(key_of):
            raise CadParseError("같은 역할의 도면이 2장 이상입니다. 한 구조물의 도면만 넣어 주세요")
        gen1, gen2 = raw["일반도 (1)"], raw["일반도 (2)"]
        for layer, where in (("CS-CONC-MAJR", gen1), ("CS-DIMT", gen1)):
            if not any(lay == layer for lay, _ in where["segs"]) and not any(t["layer"] == layer for t in where["texts"]):
                raise CadParseError(f"일반도(1): 필요한 레이어 {layer}가 없습니다")
        plan = parse_plan(gen1)
        section = measure_section(gen1)
        misc = parse_misc(gen1, gen2)
        anchored = read_anchored_dims(raw)
        classify_sheets(raw)

        rebar: Dict[str, Any] = {}
        for key in sorted(raw, key=sheet_sort):
            sheet = raw[key]
            if "철근 상세·재료표" not in sheet["role"]:
                continue
            sched = parse_schedule(sheet, key)
            if sheet["block"] == "WW":
                sched["wing_locations"] = re.findall(r"(시점좌|시점우|종점좌|종점우)", sheet["title_attr"])
                angle = Counter(t["t"] for t in sheet["texts"] if t["t"].startswith("x1=")).most_common(1)[0][0]
                sched["wing_angle_deg"] = float(re.findall(r"\d+", angle.split("=", 1)[1])[0])
            sched["sheet"] = key
            sched["block"] = sheet["block"]
            rebar[key] = sched
        self.check_structure(plan, rebar)

        sheets_out = {k: {
            "file": os.path.basename(next(f for f in loaded if key_of[f] == k)),
            "frame": v["frame"], "role": v["role"], "block": v["block"], "title_attr": v["title_attr"],
            "headings": v["headings"], "text_count": len(v["texts"]), "line_count": len(v["segs"]),
            "dimension_entities": v["dimension_entities"],
            "dims": sorted({t["t"] for t in v["texts"] if t["layer"] == "CS-DIMT" and re.fullmatch(r"[\d.]+", t["t"])}),
        } for k, v in sorted(raw.items(), key=lambda kv: sheet_sort(kv[0]))}

        results = {"source": "DXF 실측(ezdxf)", "project": read_project(gen1), "sheets": sheets_out, "section": section, "plan": plan,
                   "misc": misc, "anchored_dims": anchored, "rebar": rebar}
        with open(self.output_path, "w", encoding="utf-8") as out:
            json.dump(results, out, ensure_ascii=False, indent=1)
        return results


if __name__ == "__main__":
    data = CadParserAgent().run()
    print(json.dumps({k: data[k] for k in ("section", "plan")}, ensure_ascii=False))
    print(json.dumps(data["misc"], ensure_ascii=False))
    for k, v in data["sheets"].items():
        print(k, v["block"], v["role"], "|", v["title_attr"])
    for k, v in data["rebar"].items():
        print(k, v["block"], len(v["bars"]), v["total"], [(s["dia"], s["net_t"], s["gross_t"], s["rate"]) for s in v["subtotals"]],
              "labels", len(v["detail_labels"]), v.get("wing_locations"), v.get("wing_angle_deg"))
