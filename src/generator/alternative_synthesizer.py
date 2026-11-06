"""
Agent Alternative Synthesizer
수량 모델로 대안 수량산출서(json, xlsx)와 단면 SVG, 부재 연계표를 생성한다.
xlsx는 수식과 연결 없이 값만 담는다. 입력값 수정은 웹 화면에서만 한다.
읽는 사람용 문서는 readable_boq.py가 만든다.
수량 숫자를 이 파일에 직접 적지 않는다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as col

SCOPES = ["B1", "B2", "B3", "WW-시점좌", "WW-시점우", "WW-종점좌", "WW-종점우"]
GROUPS = {"Block 1": ["B1"], "Block 2": ["B2"], "Block 3": ["B3"], "날개벽": ["WW-시점좌", "WW-시점우", "WW-종점좌", "WW-종점우"]}
# (키, 공종, 규격, 단위) 산출서 총괄표 순서를 따른다.
ROWS: List[List[str]] = [
    ["concrete", "구조물 콘크리트", "25-30-15", "㎥"], ["lean", "버림 콘크리트", "40-15-8", "㎥"],
    ["pump", "콘크리트 타설", "펌프카 0~15m", "㎥"], ["plain_pour", "콘크리트 타설", "무근 VIB 제외", "㎥"],
    ["form_normal", "유로폼", "보통 0~7m", "㎡"], ["form_simple", "유로폼", "간단 0~7m", "㎡"],
    ["shoring", "동바리", "시스템동바리", "㎥"], ["scaffold", "비계", "시스템비계", "㎡"],
    ["spacer_wall", "스페이서", "벽체용", "㎡"], ["spacer_slab", "스페이서", "슬래브 및 기초용", "㎡"],
    ["dowel", "다웰바", "H32, L=1000mm", "EA"], ["joint_clean", "시공이음 면정리", "-", "㎡"],
    ["swell", "수팽창성 지수제", "-", "m"], ["waterstop", "지수판", "230×9.5", "m"], ["sealant", "실런트", "20×25", "m"],
    ["styrofoam", "스티로폼", "20mm", "㎡"], ["rain_wall", "우수유입방지벽", "fck=30MPa", "㎥"], ["waterproof", "아스팔트 방수", "2회", "㎡"],
    ["pvc", "PVC Pipe", "PVC_SPEC", "m"], ["fabric", "부직포", "300×300mm", "㎡"],
    ["H13", "철근가공조립(NET)", "H13(고강)", "t"], ["H16_25", "철근가공조립(NET)", "H16~25(고강)", "t"],
    ["curing", "콘크리트 양생", "-", "㎡"], ["contraction", "수축이음", "-", "m"],
]
# 도면에서 읽지 않는 재료 규격. 나머지 규격 칸은 공종을 구분하는 이름이다.
UNREAD_SPECS = {"25-30-15", "40-15-8", "230×9.5", "20×25", "20mm", "fck=30MPa", "2회"}
THIN = Side(style="thin", color="999999")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD = PatternFill("solid", fgColor="1F4E78")
INPUT = PatternFill("solid", fgColor="F2F2F2")
# 글자색: 붉은색 도면 입력, 검은색 가정·규칙, 파란색 계산
RED, BLACK, BLUE = "C8102E", "000000", "0F5C94"
KIND_COLOR = {"drawing": RED, "assumed": BLACK, "rule": BLACK, "derived": BLUE}
NUM3 = "#,##0.000"


def style_header(ws: Any, row: int, width: int) -> None:
    for c in range(1, width + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX


def sheet_table(ws: Any, headers: List[str], rows: List[List[Any]], widths: List[int]) -> None:
    ws.append(headers)
    style_header(ws, ws.max_row, len(headers))
    for row in rows:
        ws.append(row)
        for c in range(1, len(headers) + 1):
            ws.cell(row=ws.max_row, column=c).border = BOX
            ws.cell(row=ws.max_row, column=c).alignment = Alignment(vertical="center", wrap_text=True)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[col(i)].width = w
    ws.freeze_panes = "A2"


class AlternativeSynthesizerAgent:
    def __init__(self, cad_path: str = "data/cad_extracted.json", boq_path: str = "data/boq_extracted.json", model_path: str = "data/quantity_model.json",
                 issues_path: str = "reports/audit_issues.json", output_dir: str = "output", xlsx_name: str = "alternative_boq.xlsx") -> None:
        self.cad_path, self.boq_path, self.model_path, self.issues_path, self.output_dir, self.xlsx_name = cad_path, boq_path, model_path, issues_path, output_dir, xlsx_name

    def summary(self, cad: Dict[str, Any], boq: Any, model: Dict[str, Any], audit: Dict[str, Any]) -> List[Dict[str, Any]]:
        pvc = f"φ{model['pvc_dia_mm']:.0f}mm"
        out: List[Dict[str, Any]] = []
        for key, work, spec, unit in ROWS:
            totals = model["scope_totals"].get(key, {})
            groups = {g: (round(sum(totals[s] for s in ss if s in totals), 3) if any(s in totals for s in ss) else None) for g, ss in GROUPS.items()}
            total = model["grand_totals"].get(key)
            original = boq["summary_p2"][key]["values"].get("계") if boq else None
            delta = round(total - original, 3) if total is not None and original is not None else None
            result = next((c for c in audit["comparison"] if c["key"] == key), {})
            misc = cad["misc"]
            shown = {"PVC_SPEC": pvc, "H32, L=1000mm": f"{misc['dowel']['dia']}, L={misc['dowel']['length_mm']:.0f}mm", "300×300mm": f"{misc['filter_fabric']['w_mm']:.0f}×{misc['filter_fabric']['h_mm']:.0f}mm"}.get(spec, spec)
            # 재료 규격은 아직 도면에서 읽지 않는다. 다른 도면에 이 과업의 규격을 보여 주면 안 된다.
            if not model.get("reference") and spec in UNREAD_SPECS:
                shown = "-"
            out.append({"key": key, "work": work, "spec": shown, "unit": unit, "groups": groups, "total": total, "original": original, "delta": delta, "changed": bool(delta),
                        "state": result.get("state"), "state_label": result.get("label"), "cause_ids": result.get("cause_ids", []), "unexplained": result.get("unexplained", False), "assumed": result.get("assumed", []), "assumed_share": result.get("assumed_share", 0.0)})
        _ = cad, audit
        return out

    def write_xlsx(self, path: str, summary: List[Dict[str, Any]], cad: Dict[str, Any], model: Dict[str, Any]) -> None:
        """모든 칸이 값이다. 수식, 이름 정의, 시트 간 연결을 쓰지 않는다."""
        wb = Workbook()
        ws = wb.active
        ws.title = "총괄집계"
        varsheet = wb.create_sheet("변수")
        calc = wb.create_sheet("산출근거")
        rebar = wb.create_sheet("철근집계")
        bars = wb.create_sheet("철근재료표")

        # 변수: 도면에서 읽은 값(입력)과 그 값으로 계산한 값
        kind_label = {"drawing": "도면 입력", "assumed": "가정값", "rule": "규칙", "derived": "계산"}
        sheet_table(varsheet, ["구분", "변수 이름", "값", "단위", "뜻", "도면 어디서 / 계산식"], [], [12, 24, 12, 7, 38, 62])
        for v in sorted(model["variables"], key=lambda x: ("drawing", "assumed", "rule", "derived").index(x["kind"])):
            r = varsheet.max_row + 1
            varsheet.append([kind_label[v["kind"]], v["name"], v["value"], v["unit"], v["label"], v["formula"] or v["source"]])
            for c in range(1, 7):
                varsheet.cell(row=r, column=c).border = BOX
            cell = varsheet.cell(row=r, column=3)
            cell.number_format = "0" if v["digits"] == 0 else ("0.0000" if v["digits"] in (4, -4) else "0.000")
            if not v["formula"]:
                cell.fill = INPUT
            for c in (2, 3):
                varsheet.cell(row=r, column=c).font = Font(color=KIND_COLOR[v["kind"]])
        for n, (text, color) in enumerate((("붉은색: 도면에서 읽어 입력한 값", RED), ("검은색: 도면에 없는 가정값·규칙", BLACK), ("파란색: 인용·계산한 값", BLUE)), 1):
            varsheet.cell(row=n, column=8, value=text).font = Font(bold=True, color=color)
        varsheet.column_dimensions["H"].width = 30

        # 산출근거
        work = {item["key"]: item["work"] for item in summary}
        rows = [[line["id"], line["scope"], work.get(line["key"], line["key"]), line["element"], line["desc"], line["value"], ", ".join(line["sheets"]), line["formula"].replace("*", "×").replace("/", "÷"), line["expr"].replace("*", "×").replace("/", "÷")] for line in model["lines"]]
        sheet_table(calc, ["행 ID", "구분", "공종", "부재 ID", "내용", "수량", "연계 도면", "변수식", "값을 넣은 식"], rows, [24, 12, 18, 15, 28, 12, 30, 58, 58])
        for r in range(2, calc.max_row + 1):
            calc.cell(row=r, column=6).number_format = NUM3
            calc.cell(row=r, column=6).font = Font(color=BLUE)

        # 철근재료표
        bar_rows = [[sheet, b["mark"], b["dia"], b["length_m"], b["count"], round(b["length_m"] * b["count"], 3)] for sheet, sched in cad["rebar"].items() for b in sched["bars"]]
        sheet_table(bars, ["도면", "기호", "직경", "길이(m)", "개수", "총길이(m)"], bar_rows, [14, 10, 8, 10, 8, 12])
        for r in range(2, bars.max_row + 1):
            bars.cell(row=r, column=6).number_format = NUM3
            bars.cell(row=r, column=6).font = Font(color=BLUE)
            for c in (4, 5):
                bars.cell(row=r, column=c).font = Font(color=RED)

        # 철근집계: 개소(scope)·호칭경별
        sheet_table(rebar, ["구분", "도면", "직경", "총길이(m)", "단위중량(kg/m)", "NET(t)", "할증률", "재료량(t)"], [], [14, 14, 8, 12, 14, 12, 9, 12])
        for rec in model["rebar"]["records"]:
            r = rebar.max_row + 1
            rebar.append([rec["scope"], rec["sheet"], rec["dia"], rec["length_m"], rec["unit_weight"], rec["net_t"], rec["rate"], rec["gross_t"]])
            for c in range(1, 9):
                rebar.cell(row=r, column=c).border = BOX
            for c in (4, 6, 8):
                rebar.cell(row=r, column=c).number_format = NUM3
                rebar.cell(row=r, column=c).font = Font(color=BLUE)
            rebar.cell(row=r, column=7).number_format = "0%"
        rebar.append(["합계", None, None, None, None, model["rebar"]["net_total_t"], None, model["rebar"]["gross_total_t"]])
        total_row = rebar.max_row
        for c in range(1, 9):
            rebar.cell(row=total_row, column=c).font = Font(bold=True)
            rebar.cell(row=total_row, column=c).border = BOX
        rebar.cell(row=total_row, column=6).number_format = NUM3
        rebar.cell(row=total_row, column=8).number_format = NUM3

        # 총괄집계
        heads = ["공종", "규격", "단위", "Block 1", "Block 2", "Block 3", "날개벽", "합계"]
        title = f"{cad['project']['station']} 통로암거 수량 총괄집계표" if cad["project"]["station"] else "통로암거 수량 총괄집계표"
        ws.append([title])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append(heads)
        style_header(ws, 2, len(heads))
        table = [[item["work"], item["spec"], item["unit"]] + [item["groups"][g] if item["groups"][g] is not None else "-" for g in GROUPS] + [item["total"]] for item in summary]
        table.append(["철근 재료량", "할증 포함", "t", "-", "-", "-", "-", model["rebar"]["gross_total_t"]])
        keys = [item["key"] for item in summary] + ["rebar_gross"]
        for key, row in zip(keys, table):
            ws.append(row)
            r = ws.max_row
            for c in range(1, len(heads) + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = BOX
                if c >= 4:
                    cell.number_format = "#,##0" if key == "dowel" else NUM3
                    cell.alignment = Alignment(horizontal="right")
                    cell.font = Font(color=BLUE)
        for i, w in enumerate([18, 22, 6, 12, 12, 12, 12, 13], 1):
            ws.column_dimensions[col(i)].width = w
        ws.freeze_panes = "D3"
        wb.save(path)

    def svg(self, cad: Dict[str, Any]) -> str:
        """표준단면 실측 선형으로 그린 부재 ID 단면도."""
        s = cad["section"]
        scale = 0.075
        ox, oy = 110.0, 70.0
        w, h = s["total_width_mm"] * scale, s["total_height_mm"] * scale
        t, b, wall, hw = s["top_slab_t_mm"] * scale, s["bot_slab_t_mm"] * scale, s["wall_t_mm"] * scale, s["haunch_w_mm"] * scale
        lm = (s["lean_width_mm"] - s["total_width_mm"]) / 2 * scale
        lean = s["lean_t_mm"] * scale
        inner = [(ox + wall + hw, oy + t), (ox + w - wall - hw, oy + t), (ox + w - wall, oy + t + hw), (ox + w - wall, oy + h - b), (ox + wall, oy + h - b), (ox + wall, oy + t + hw)]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in inner)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 590" font-family="Malgun Gothic,sans-serif" font-size="12">
<title>통로암거 표준단면 부재 ID</title><rect width="640" height="590" fill="#fff"/>
<text x="320" y="30" text-anchor="middle" font-size="16" font-weight="bold">표준단면 부재 ID (일반도(1) 실측)</text>
<rect x="{ox:.1f}" y="{oy:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#c9c9c9" stroke="#222"/>
<polygon points="{pts}" fill="#fff" stroke="#222"/>
<rect x="{ox - lm:.1f}" y="{oy + h:.1f}" width="{w + 2 * lm:.1f}" height="{lean:.1f}" fill="#8f8f8f" stroke="#222"/>
<text x="{ox + w / 2:.1f}" y="{oy + t / 2 + 4:.1f}" text-anchor="middle">Bn-SLAB-TOP t={s['top_slab_t_mm'] / 1000:.3f}</text>
<text x="{ox + w / 2:.1f}" y="{oy + h - b / 2 + 4:.1f}" text-anchor="middle">Bn-SLAB-BOT t={s['bot_slab_t_mm'] / 1000:.3f}</text>
<text x="{ox - 8:.1f}" y="{oy + h / 2:.1f}" text-anchor="end">Bn-WALL-L</text><text x="{ox - 8:.1f}" y="{oy + h / 2 + 15:.1f}" text-anchor="end">t={s['wall_t_mm'] / 1000:.3f}</text>
<text x="{ox + w + 8:.1f}" y="{oy + h / 2:.1f}">Bn-WALL-R</text><text x="{ox + w + 8:.1f}" y="{oy + h / 2 + 15:.1f}">t={s['wall_t_mm'] / 1000:.3f}</text>
<text x="{ox + w / 2:.1f}" y="{oy + t + hw + 26:.1f}" text-anchor="middle">상부 헌치 {s['haunch_w_mm']:.0f}×{s['haunch_h_mm']:.0f} ({s['haunch_count_top']}개소): Bn-HAUNCH-L, Bn-HAUNCH-R</text>
<text x="{ox + w / 2:.1f}" y="{oy + h / 2 + 20:.1f}" text-anchor="middle">내공 {s['inner_width_mm'] / 1000:.3f} × {s['inner_height_mm'] / 1000:.3f}</text>
<text x="{ox + w / 2:.1f}" y="{oy + h + lean + 22:.1f}" text-anchor="middle">외곽 폭 {s['total_width_mm'] / 1000:.3f} / 외곽 높이 {s['total_height_mm'] / 1000:.3f} / 버림 폭 {s['lean_width_mm'] / 1000:.3f}</text>
</svg>
"""

    def run(self) -> Dict[str, Any]:
        with open(self.cad_path, encoding="utf-8") as f:
            cad = json.load(f)
        with open(self.model_path, encoding="utf-8") as f:
            model = json.load(f)
        with open(self.issues_path, encoding="utf-8") as f:
            audit = json.load(f)
        boq = None
        if audit["original_status"] == "provided":
            with open(self.boq_path, encoding="utf-8") as f:
                boq = json.load(f)
        drawings = os.path.join(self.output_dir, "alternative_drawings")
        os.makedirs(drawings, exist_ok=True)

        summary = self.summary(cad, boq, model, audit)
        element_map: Dict[str, Dict[str, Any]] = {}
        for line in model["lines"]:
            rec = element_map.setdefault(line["element"], {"element": line["element"], "scope": line["scope"], "keys": [], "lines": 0, "sheets": line["sheets"], "line_ids": []})
            rec["lines"] += 1
            rec["line_ids"].append(line["id"])
            if line["key"] not in rec["keys"]:
                rec["keys"].append(line["key"])
        elements = list(element_map.values())

        boq_json = {
            "title": f"{cad['project']['station']} 통로암거 수량산출서", "basis": "DXF 실측 모델(data/quantity_model.json)",
            "rebar_premium_rule": "S22 이상 6%, S19 이하 3%", "pvc_spec": f"φ{model['pvc_dia_mm']:.0f}mm",
            "dimensions": {k: v for k, v in cad["section"].items() if k.endswith("_mm") or k.startswith("haunch_count")},
            "total_length_m": cad["plan"]["total_length_m"], "summary": summary,
            "rebar": {"net_total_t": model["rebar"]["net_total_t"], "gross_total_t": model["rebar"]["gross_total_t"], "by_dia": model["rebar"]["by_dia"], "records": model["rebar"]["records"]},
            "variables": model["variables"], "lines": model["lines"], "elements": elements, "reference": bool(model.get("reference")), "issues": [i["issue_id"] for i in audit["issues"]], "open_items": audit["open_items"],
        }
        with open(os.path.join(self.output_dir, "alternative_boq.json"), "w", encoding="utf-8") as out:
            json.dump(boq_json, out, ensure_ascii=False, indent=1)
        with open(os.path.join(drawings, "element_map.json"), "w", encoding="utf-8") as out:
            json.dump(elements, out, ensure_ascii=False, indent=1)
        self.write_xlsx(os.path.join(self.output_dir, self.xlsx_name), summary, cad, model)
        with open(os.path.join(drawings, "alternative_culvert_section.svg"), "w", encoding="utf-8") as out:
            out.write(self.svg(cad))
        return {"status": "success", "rows": len(summary), "lines": len(model["lines"]), "elements": len(elements)}


if __name__ == "__main__":
    print(AlternativeSynthesizerAgent().run())
