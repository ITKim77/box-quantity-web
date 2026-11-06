"""
DXF Alternative Generator
원본 도면의 기존 객체는 수정하지 않고(철근 재료표 기호 문자에 XDATA만 부착) 다음을 추가한다.
 - 정의된 레이어 QTO-LINK
 - 도곽 안의 빈 영역에 도면별 수량 연계표(값은 data/quantity_model.json에서 읽음)
 - 일반도(1) 표준단면에 부재 ID 라벨
 - 철근 재료표 기호 문자에 산출 행 연결 XDATA
빈 영역을 찾지 못하면 임의 좌표에 넣지 않고 오류로 중단한다.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox as ezbbox


LAYER = "QTO-LINK"
APPID = "QTO_LINK"
Row = Tuple[str, str, str, str]  # 항목, 값, 단위, 행 ID
Rect = Tuple[float, float, float, float]

SCOPE_NAME = {"B1": "BLOCK 1", "B2": "BLOCK 2", "B3": "BLOCK 3"}
UNIT = {"concrete": "㎥", "lean": "㎥", "form_normal": "㎡", "form_simple": "㎡", "shoring": "㎥", "scaffold": "㎡", "spacer_wall": "㎡",
        "spacer_slab": "㎡", "joint_clean": "㎡", "swell": "m", "waterstop": "m", "sealant": "m", "styrofoam": "㎡", "rain_wall": "㎥",
        "dowel": "EA", "waterproof": "㎡", "curing": "㎡", "contraction": "m", "pvc": "m", "fabric": "㎡"}
NAME = {"concrete": "구조물 콘크리트", "lean": "버림 콘크리트", "form_normal": "유로폼(보통)", "form_simple": "유로폼(간단)", "shoring": "시스템동바리",
        "scaffold": "시스템비계", "spacer_wall": "스페이서(벽체)", "spacer_slab": "스페이서(슬래브)", "joint_clean": "시공이음 면정리", "swell": "수팽창 지수제",
        "waterstop": "지수판", "sealant": "실런트", "styrofoam": "스티로폼", "rain_wall": "우수유입방지벽", "dowel": "다웰바", "waterproof": "아스팔트 방수",
        "curing": "콘크리트 양생", "contraction": "수축이음", "pvc": "PVC 배수관", "fabric": "부직포"}


def qty_row(model: Dict[str, Any], key: str, scopes: List[str], label: str = "") -> Row:
    totals = model["scope_totals"].get(key, {})
    value = round(sum(totals.get(s, 0.0) for s in scopes), 3)
    code = {"B1": "B1", "B2": "B2", "B3": "B3", "WW-시점좌": "SL", "WW-시점우": "SR", "WW-종점좌": "EL", "WW-종점우": "ER"}
    if set(scopes) == {"B1", "B2", "B3"}:
        prefix = "BODY"
    elif len(scopes) == 4:
        prefix = "WING"
    else:
        prefix = "+".join(code[s] for s in scopes)
    ref = f"{prefix}.{key}"
    number = f"{value:.0f}" if key == "dowel" else f"{value:,.3f}"
    return (label or NAME[key], number, UNIT[key], ref)


def rebar_rows(model: Dict[str, Any], scopes: List[str]) -> List[Row]:
    records = [r for r in model["rebar"]["records"] if r["scope"] in scopes]
    rows: List[Row] = []
    for dia in sorted({r["dia"] for r in records}, key=lambda d: -int(d[1:])):
        sel = [r for r in records if r["dia"] == dia]
        rate = int(round(sel[0]["rate"] * 100))
        rows.append((f"철근 {dia} NET", f"{sum(r['net_t'] for r in sel):,.3f}", "t", f"REBAR.{dia}"))
        rows.append((f"철근 {dia} 재료(+{rate}%)", f"{sum(r['gross_t'] for r in sel):,.3f}", "t", f"REBAR.{dia}"))
    rows.append(("철근 재료 합계", f"{sum(r['gross_t'] for r in records):,.3f}", "t", "REBAR.TOTAL"))
    return rows


def rows_for_sheet(key: str, sheet: Dict[str, Any], model: Dict[str, Any], cad: Dict[str, Any]) -> Tuple[str, List[Row]]:
    role = sheet["role"]
    if key == "일반도 (1)":
        sec = cad["section"]
        body = ["B1", "B2", "B3"]
        spec = f"B {sec['total_width_mm'] / 1000:.3f} × H {sec['total_height_mm'] / 1000:.3f}"
        rows: List[Row] = [("외곽 제원(실측)", spec, "m", "CAD.section"), ("상부 헌치(실측)", f"{sec['haunch_w_mm']:.0f}×{sec['haunch_h_mm']:.0f}, {sec['haunch_count_top']}개소", "mm", "CAD.section")]
        rows += [qty_row(model, k, body, f"본체 {NAME[k]}") for k in ("concrete", "lean", "form_normal", "waterproof")]
        rows += [qty_row(model, k, ["B2", "B3"]) for k in ("dowel", "waterstop", "sealant", "styrofoam")]
        return "본체 3개 블록 합계", rows
    if key == "일반도 (2)":
        wing = [f"WW-{loc}" for loc in ("시점좌", "시점우", "종점좌", "종점우")]
        rows = [qty_row(model, k, wing) for k in ("concrete", "form_normal", "shoring", "scaffold", "spacer_wall", "waterproof", "fabric")]
        pvc = qty_row(model, "pvc", wing)
        rows.append((f"PVC 배수관 Φ{model['pvc_dia_mm']:.0f}", pvc[1], pvc[2], pvc[3]))
        return "날개벽 4개소 합계", rows
    if sheet["block"] == "WW":
        scopes = [f"WW-{loc}" for loc in re.findall(r"(시점좌|시점우|종점좌|종점우)", sheet["title_attr"])]
        rows = [qty_row(model, k, scopes) for k in ("concrete", "form_normal", "spacer_wall")] + rebar_rows(model, scopes)
        return "날개벽 " + "·".join(s[3:] for s in scopes), rows
    scope = sheet["block"]
    title = SCOPE_NAME[scope]
    if "철근 상세·재료표" in role:
        return title + " 철근", rebar_rows(model, [scope])
    if "표준단면" in role:
        return title, [qty_row(model, k, [scope]) for k in ("concrete", "lean", "form_normal", "shoring", "scaffold", "waterproof")]
    rows = [qty_row(model, k, [scope]) for k in ("spacer_wall", "spacer_slab")]
    return title + " 배근", rows + rebar_rows(model, [scope])


def occupied_boxes(doc: Any, frame: List[float]) -> List[Rect]:
    """모델공간 객체의 실제 범위(블록 내부 포함). 도곽 전체를 덮는 도곽 블록 자체는 제외한다."""
    x0, x1, y0, y1 = frame
    frame_area = (x1 - x0) * (y1 - y0)
    boxes: List[Rect] = []
    for box in ezbbox.multi_recursive(doc.modelspace()):
        if not box.has_data:
            continue
        rect = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
        if rect[2] < x0 or rect[0] > x1 or rect[3] < y0 or rect[1] > y1:
            continue
        if (rect[2] - rect[0]) * (rect[3] - rect[1]) > 0.25 * frame_area:
            continue
        boxes.append(rect)
    return boxes


def find_free_rect(boxes: List[Rect], frame: List[float], width: float, height: float, cell: float = 100.0) -> Optional[Tuple[float, float]]:
    """도곽 안에서 width×height 빈 사각형을 찾아 좌하단 좌표를 돌려준다. 우하단(표제란 위쪽)을 우선한다."""
    x0, x1, y0, y1 = frame
    margin = 400.0
    nx, ny = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    grid = [[0] * (nx + 1) for _ in range(ny + 1)]  # 2차원 차분 → 누적합
    for bx0, by0, bx1, by1 in boxes:
        i0, i1 = max(0, int((bx0 - x0) / cell)), min(nx - 1, int((bx1 - x0) / cell))
        j0, j1 = max(0, int((by0 - y0) / cell)), min(ny - 1, int((by1 - y0) / cell))
        if i0 > i1 or j0 > j1:
            continue
        grid[j0][i0] += 1
        grid[j0][i1 + 1] -= 1
        grid[j1 + 1][i0] -= 1
        grid[j1 + 1][i1 + 1] += 1
    summed = [[0] * (nx + 1) for _ in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            grid[j][i] += (grid[j - 1][i] if j else 0) + (grid[j][i - 1] if i else 0) - (grid[j - 1][i - 1] if i and j else 0)
            summed[j + 1][i + 1] = summed[j][i + 1] + summed[j + 1][i] - summed[j][i] + (1 if grid[j][i] > 0 else 0)
    w_cells, h_cells = int(width / cell) + 2, int(height / cell) + 2
    m = int(margin / cell) + 1
    best: Optional[Tuple[float, float]] = None
    best_score = -1e18
    for j in range(m, ny - h_cells - m):
        for i in range(m, nx - w_cells - m):
            used = summed[j + h_cells][i + w_cells] - summed[j][i + w_cells] - summed[j + h_cells][i] + summed[j][i]
            if used == 0:
                score = i - j * 0.5  # 오른쪽·아래쪽 선호
                if score > best_score:
                    best_score = score
                    best = (x0 + (i + 1) * cell, y0 + (j + 1) * cell)
    return best


def hangul_style(doc: Any) -> str:
    """원본에서 한글 문자에 실제 쓰인 글꼴 스타일을 재사용한다."""
    counts: Dict[str, int] = {}
    for ent in doc.modelspace().query("TEXT"):
        if re.search("[가-힣]", ent.dxf.text):
            counts[ent.dxf.style] = counts.get(ent.dxf.style, 0) + 1
    if not counts:
        raise RuntimeError("한글 TEXT 스타일을 찾지 못함")
    return max(counts, key=lambda k: counts[k])


def draw_table(msp: Any, style: str, x: float, y: float, title: str, rows: List[Row], text_h: float) -> Rect:
    """좌하단 (x, y) 기준 연계표. 범위를 돌려준다."""
    row_h = text_h * 2.0
    widths = [text_h * 15, text_h * 13, text_h * 3.5, text_h * 15]
    width = sum(widths)
    height = row_h * (len(rows) + 3)
    attrs = {"layer": LAYER, "style": style}

    def put(tx: float, ty: float, value: str) -> None:
        msp.add_text(value, height=text_h, dxfattribs={**attrs, "insert": (tx, ty)})

    top = y + height
    for n in range(len(rows) + 4):
        yy = top - n * row_h
        msp.add_line((x, yy), (x + width, yy), dxfattribs={"layer": LAYER})
    xx = x
    msp.add_line((x, y), (x, top), dxfattribs={"layer": LAYER})
    for n, w in enumerate(widths):
        xx += w
        msp.add_line((xx, y), (xx, top - (row_h if n < len(widths) - 1 else 0)), dxfattribs={"layer": LAYER})
    pad = text_h * 0.5
    put(x + pad, top - row_h + pad, f"수량 연계표 - {title}")
    cols = [x, x + widths[0], x + widths[0] + widths[1], x + widths[0] + widths[1] + widths[2]]
    for cx, head in zip(cols, ("항목", "대안 수량", "단위", "산출 행 ID")):
        put(cx + pad, top - 2 * row_h + pad, head)
    for n, row in enumerate(rows):
        yy = top - (n + 3) * row_h + pad
        for cx, value in zip(cols, row):
            put(cx + pad, yy, value)
    put(x + pad, y + pad, "정본 alternative_boq.xlsx / 행 ID 앞자리로 추적")
    return (x, y, x + width, top)


def section_tags(msp: Any, style: str, cad: Dict[str, Any]) -> int:
    """일반도(1) 표준단면에 부재 ID 라벨. 위치는 실측 선형에서 계산한다."""
    sec = cad["section"]
    box, lv = sec["section_box"], sec["levels"]
    h = 110.0
    cx = (box["x0"] + box["x1"]) / 2
    tags = [
        ("SLAB-TOP", cx - 350, (box["y1"] + lv["y_soffit"]) / 2 - h / 2),
        ("SLAB-BOT", cx - 350, (lv["y_floor"] + box["y0"]) / 2 - h / 2),
        ("HAUNCH-L", lv["wall_l"] + 40, lv["y_soffit"] + 15),
        ("HAUNCH-R", lv["wall_r"] - 760, lv["y_soffit"] + 15),
    ]
    for name, x, y in tags:
        msp.add_text(f"[Bn-{name}]", height=h, dxfattribs={"layer": LAYER, "style": style, "insert": (x, y)})
    for name, x in (("WALL-L", (box["x0"] + lv["wall_l"]) / 2), ("WALL-R", (box["x1"] + lv["wall_r"]) / 2)):
        msp.add_text(f"[Bn-{name}]", height=h, dxfattribs={"layer": LAYER, "style": style, "insert": (x + h / 2, (lv["y_soffit"] + lv["y_floor"]) / 2 - 300), "rotation": 90})
    return len(tags) + 2


def attach_rebar_xdata(doc: Any, sched: Dict[str, Any], model: Dict[str, Any]) -> int:
    msp = doc.modelspace()
    doc.appids.new(APPID) if APPID not in doc.appids else None
    scopes = [f"WW-{loc}" for loc in sched.get("wing_locations", [])] or [sched["block"]]
    texts = list(msp.query('TEXT[layer=="CS-TABL-TEX2"]'))
    linked = 0
    for bar in sched["bars"]:
        hit = next((t for t in texts if t.dxf.text == bar["mark"] and abs(t.dxf.insert.x - bar["text_x"]) < 0.01 and abs(t.dxf.insert.y - bar["text_y"]) < 0.01), None)
        if hit is None:
            raise RuntimeError(f"재료표 기호 미검출: {sched['sheet']} {bar['mark']}")
        record = next(r for r in model["rebar"]["records"] if r["scope"] == scopes[0] and r["dia"] == bar["dia"])
        hit.set_xdata(APPID, [(1000, f"sheet={sched['sheet']}"), (1000, f"scope={'+'.join(scopes)}"), (1000, f"dia={bar['dia']}"), (1040, bar["length_m"]), (1070, bar["count"]), (1000, f"boq=REBAR.{bar['dia']}"), (1040, record["rate"])])
        linked += 1
    return linked


def generate_alternative_dxfs(cad_path: str = "data/cad_extracted.json", model_path: str = "data/quantity_model.json",
                              input_dir: str = "docs", output_dir: str = "output/alternative_drawings") -> Dict[str, Any]:
    with open(cad_path, encoding="utf-8") as f:
        cad = json.load(f)
    with open(model_path, encoding="utf-8") as f:
        model = json.load(f)
    os.makedirs(output_dir, exist_ok=True)
    report: Dict[str, Any] = {}
    for path in sorted(glob.glob(os.path.join(input_dir, "*.dxf"))):
        key = next(k for k, v in cad["sheets"].items() if v["file"] == os.path.basename(path))
        sheet = cad["sheets"][key]
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        frame = sheet["frame"]
        boxes = occupied_boxes(doc, frame)
        style = hangul_style(doc)
        title, rows = rows_for_sheet(key, sheet, model, cad)
        text_h = 220.0 if key.startswith("일반도") else 130.0
        width, height, placed = 0.0, 0.0, None
        while text_h >= 80 and placed is None:
            width = text_h * (15 + 13 + 3.5 + 15)
            height = text_h * 2.0 * (len(rows) + 3)
            placed = find_free_rect(boxes, frame, width, height)
            if placed is None:
                text_h -= 10
        if placed is None:
            raise RuntimeError(f"{key}: 연계표 빈 영역({width:.0f}×{height:.0f}) 없음")
        doc.layers.add(LAYER, color=1)
        rect = draw_table(msp, style, placed[0], placed[1], f"{key} / {title}", rows, text_h)
        tags = section_tags(msp, style, cad) if key == "일반도 (1)" else 0
        linked = attach_rebar_xdata(doc, cad["rebar"][key], model) if key in cad["rebar"] else 0
        out = os.path.join(output_dir, f"대안_{os.path.basename(path)}")
        doc.saveas(out)
        report[key] = {"file": os.path.basename(out), "table_rect": rect, "text_height": text_h, "style": style, "rows": len(rows), "tags": tags, "xdata_links": linked, "title": title, "role": sheet["role"], "block": sheet["block"], "frame": frame, "table_rows": rows}
    with open(os.path.join(output_dir, "drawing_link_report.json"), "w", encoding="utf-8") as out_f:
        json.dump(report, out_f, ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    result = generate_alternative_dxfs()
    for sheet_name, rec in result.items():
        print(sheet_name, rec["style"], "h", rec["text_height"], "rect", [round(v) for v in rec["table_rect"]], "rows", rec["rows"], "tags", rec["tags"], "xdata", rec["xdata_links"])
