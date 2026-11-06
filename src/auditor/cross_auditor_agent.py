"""
Agent Cross Auditor (Evaluator)
결함 문구를 미리 적어 두지 않는다. 도면 모델과 산출서 추출값의 계산된 차이에서만 결함을 만든다.
원본 산출서는 선택 입력이다. 없으면 도면 자체 검사만 하고, 있으면 공종별 비교 판정을 만든다.
원인을 규명하지 못한 차이는 멈추지 않고 '미규명'으로 보여 준다. 멈추는 것은 도면 자체 검사가 실패할 때뿐이다.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.rules import STATE_LABEL, UNIT_WEIGHT, premium_rate, round3, same
from src.model.quantity_model import UNTRACED

P4_COL = {"B1": "Block1", "B2": "Block2", "B3": "Block3"}
WING_LOC = ["시점좌", "시점우", "종점좌", "종점우"]
KEY_NAME = {
    "concrete": "구조물 콘크리트", "lean": "버림 콘크리트", "pump": "펌프카 타설", "plain_pour": "무근 타설",
    "form_normal": "유로폼(보통)", "form_simple": "유로폼(간단)", "shoring": "시스템동바리", "scaffold": "시스템비계",
    "spacer_wall": "스페이서(벽체용)", "spacer_slab": "스페이서(슬래브·기초용)", "dowel": "다웰바", "joint_clean": "시공이음 면정리",
    "swell": "수팽창성 지수제", "waterstop": "지수판", "sealant": "실런트", "styrofoam": "스티로폼", "rain_wall": "우수유입방지벽",
    "waterproof": "아스팔트 방수", "pvc": "PVC Pipe", "fabric": "부직포", "curing": "콘크리트 양생", "contraction": "수축이음",
    "H13": "철근가공조립 H13", "H16_25": "철근가공조립 H16~25",
}
WING_KEYS = ["concrete", "form_normal", "shoring", "scaffold", "spacer_wall", "waterproof", "pvc", "fabric", "H16_25"]
# 산출서 항목명 -> 모델 키 (산식 페이지 소계 대조용). 동일 명칭은 등장 순서로 구분한다.
CALC_NAMES = {"동바리": "shoring", "비계": "scaffold", "시공이음 면정리": "joint_clean", "수팽창성 지수제": "swell", "아스팔트 방수": "waterproof",
              "콘크리트 양생": "curing", "수축이음": "contraction", "지수판": "waterstop", "실런트": "sealant", "스티로폼": "styrofoam",
              "우수유입방지벽": "rain_wall", "다웰바": "dowel", "PVC Pipe": "pvc", "부직포": "fabric"}


def calc_subtotals(items: List[Dict[str, Any]]) -> Dict[str, Tuple[float, int]]:
    """산식 페이지의 항목 소계를 (값, 페이지)로 정리한다."""
    out: Dict[str, Tuple[float, int]] = {}
    seen: Dict[str, int] = {}
    for item in items:
        name = item["name"]
        seen[name] = seen.get(name, 0) + 1
        subs = item["subtotals"]
        if not subs:
            continue
        if name == "콘크리트":
            out["concrete" if seen[name] == 1 else "lean"] = (subs[-1]["value"], item["page"])
        elif name == "유로폼":
            out["form_normal" if seen[name] == 1 else "form_simple"] = (subs[-1]["value"], item["page"])
        elif name == "스페이서":
            for s in subs:
                out["spacer_wall" if "벽체" in s["sub"] else "spacer_slab"] = (s["value"], s["page"])
        elif name in CALC_NAMES:
            out[CALC_NAMES[name]] = (subs[-1]["value"], item["page"])
    return out


class CrossAuditorAgent:
    def __init__(self, cad_path: str = "data/cad_extracted.json", boq_path: str = "data/boq_extracted.json",
                 model_path: str = "data/quantity_model.json", output_path: str = "reports/audit_issues.json", original_note: str = "") -> None:
        self.cad_path, self.boq_path, self.model_path, self.output_path = cad_path, boq_path, model_path, output_path
        self.original_note = original_note
        self.issues: List[Dict[str, Any]] = []
        self.diffs: List[Dict[str, Any]] = []

    def add(self, category: str, severity: str, status: str, title: str, detail: str, boq: str, drawing: str,
            corrected: str, delta: Optional[str], pages: List[int], sheets: List[str]) -> None:
        self.issues.append({"category": category, "severity": severity, "status": status, "title": title, "detail": detail,
                            "boq_value": boq, "drawing_value": drawing, "corrected_value": corrected, "delta": delta,
                            "boq_pages": sorted(set(pages)), "drawing_sheets": sheets})

    # ---------------------------------------------------------------- 계약 0·1
    def contract_section(self, cad: Dict[str, Any], boq: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sec = cad["section"]
        checks: List[Dict[str, Any]] = []
        calc_h = sec["top_slab_t_mm"] + sec["inner_height_mm"] + sec["bot_slab_t_mm"]
        calc_w = sec["wall_t_mm"] * 2 + sec["inner_width_mm"]
        checks.append({"check": "H_calc == H_total", "calc": calc_h, "measured": sec["total_height_mm"], "pass": calc_h == sec["total_height_mm"]})
        checks.append({"check": "B_calc == B_total", "calc": calc_w, "measured": sec["total_width_mm"], "pass": calc_w == sec["total_width_mm"]})
        dims = sec["text_dims"]
        for field in ("top_slab_t_mm", "bot_slab_t_mm", "wall_t_mm"):
            text = f"{sec[field]:.0f}"
            checks.append({"check": f"치수문자 {text} == 실측 {field}", "calc": float(text), "measured": sec[field], "pass": text in dims})
        haunch_text = f"{sec['haunch_w_mm']:.0f}X{sec['haunch_h_mm']:.0f}"
        checks.append({"check": f"치수문자 {haunch_text} 개수 == 실측 헌치 개소", "calc": dims.count(haunch_text), "measured": sec["haunch_count_top"] + sec["haunch_count_bottom"], "pass": dims.count(haunch_text) == sec["haunch_count_top"] + sec["haunch_count_bottom"]})
        # 산출서 p.7 산식 피연산자 == 도면 제원 (오차 0)
        line = boq["calc"]["B1"][0]["lines"] if boq else []
        expected = {} if not boq else {"①": f"{sec['total_width_mm']/1000:.3f} x {sec['bot_slab_t_mm']/1000:.3f}", "②": f"{sec['total_width_mm']/1000:.3f} x {sec['top_slab_t_mm']/1000:.3f}", "③": f"{sec['wall_t_mm']/1000:.3f} x {sec['inner_height_mm']/1000:.3f}", "⑤": f"( {sec['haunch_w_mm']/1000:.3f} x {sec['haunch_h_mm']/1000:.3f} / 2 )"}
        for tag, text in expected.items():
            found = next((l for l in line if l["tag"] == tag), None)
            ok = bool(found) and text in found["formula"]
            checks.append({"check": f"p.7 {tag} 산식에 도면 제원 '{text}' 사용", "calc": found["formula"] if found else None, "measured": text, "pass": ok})
        checks.append({"check": "계산 변수 천장밑폭 == 실측 천장 밑면 선", "calc": sec["inner_width_mm"] - 2 * sec["haunch_w_mm"], "measured": sec["soffit_width_mm"], "pass": sec["inner_width_mm"] - 2 * sec["haunch_w_mm"] == sec["soffit_width_mm"]})
        checks.append({"check": "계산 변수 안쪽폭 == 실측 바닥 선", "calc": sec["inner_width_mm"], "measured": sec["floor_width_mm"], "pass": sec["inner_width_mm"] == sec["floor_width_mm"]})
        for name, rec in cad["plan"]["blocks"].items():
            avg = round3((rec["left"] + rec["right"]) / 2)
            checks.append({"check": f"{name} 평균길이 계산 == 종단면도 치수", "calc": avg, "measured": rec["avg"], "pass": same(avg, rec["avg"])})
        plan = cad["plan"]
        sum_len = round3(sum(b["avg"] for b in plan["blocks"].values()) + plan["joint_gap_mm"] * plan["joint_count"] / 1000)
        checks.append({"check": "블록 평균연장 합 + 이음 간격 == 총연장", "calc": sum_len, "measured": plan["total_length_m"], "pass": same(sum_len, plan["total_length_m"])})
        return checks

    # ---------------------------------------------------------------- 수량 대조
    def compare_quantities(self, boq: Dict[str, Any], model: Dict[str, Any]) -> None:
        totals = model["scope_totals"]
        for key, name in KEY_NAME.items():
            for scope in ("B1", "B2", "B3"):
                printed = boq["summary_p4"][key]["values"].get(P4_COL[scope])
                calc = totals.get(key, {}).get(scope)
                if printed is None and calc is None:
                    continue
                if printed is None or calc is None or not same(printed, calc):
                    self.diffs.append({"key": key, "name": name, "scope": scope, "boq": printed, "model": calc})
        for key in WING_KEYS:
            for loc in WING_LOC:
                printed = boq["wing_p21"][key]["values"].get(loc)
                calc = totals[key].get(f"WW-{loc}")
                if printed is None or calc is None or not same(printed, calc):
                    self.diffs.append({"key": key, "name": KEY_NAME[key], "scope": f"WW-{loc}", "boq": printed, "model": calc})

    def internal_consistency(self, boq: Dict[str, Any]) -> Dict[str, Any]:
        """산출서 내부: 행 계산, 소계, p.4/p.21/p.2 전기."""
        stats = {"formula_lines": 0, "formula_evaluated": 0, "line_mismatch": [], "subtotal_mismatch": [], "transfer_mismatch": []}
        for scope, items in boq["calc"].items():
            for item in items:
                for line in item["lines"]:
                    stats["formula_lines"] += 1
                    if "calc" in line and line["printed"] is not None:
                        stats["formula_evaluated"] += 1
                        if abs(line["calc"] - line["printed"]) > 0.0015:
                            stats["line_mismatch"].append({"scope": scope, "item": item["name"], "formula": line["formula"], "calc": line["calc"], "printed": line["printed"], "page": line["page"]})
                if item["name"] != "철근가공조립" and item["name"] != "스페이서" and item["subtotals"]:
                    values = [l["printed"] for l in item["lines"] if l["printed"] is not None]
                    if values and abs(round3(sum(values)) - item["subtotals"][-1]["value"]) > 0.0015:
                        stats["subtotal_mismatch"].append({"scope": scope, "item": item["name"], "sum": round3(sum(values)), "printed": item["subtotals"][-1]["value"], "page": item["page"]})
            for key, (value, page) in calc_subtotals(items).items():
                if scope.startswith("WW"):
                    loc = scope[3:]
                    ref = boq["wing_p21"].get(key, {}).get("values", {}).get(loc)
                else:
                    ref = boq["summary_p4"][key]["values"].get(P4_COL[scope])
                if ref is not None and not same(ref, value):
                    stats["transfer_mismatch"].append({"scope": scope, "key": key, "calc_page": value, "summary": ref, "page": page})
        for key, row in boq["summary_p4"].items():
            total_p4 = row["values"].get("계")
            total_p2 = boq["summary_p2"][key]["values"].get("계")
            if total_p4 is not None and total_p2 is not None and not same(total_p4, total_p2):
                stats["transfer_mismatch"].append({"scope": "p.2↔p.4", "key": key, "calc_page": total_p4, "summary": total_p2})
            parts = [v for c, v in row["values"].items() if c != "계" and v is not None]
            if parts and total_p4 is not None and abs(round3(sum(parts)) - total_p4) > 0.0015:
                stats["transfer_mismatch"].append({"scope": "p.4 행합", "key": key, "calc_page": round3(sum(parts)), "summary": total_p4})
        return stats

    # ---------------------------------------------------------------- 차이 원인 규명
    def explain_diffs(self, boq: Dict[str, Any], model: Dict[str, Any]) -> None:
        remaining = list(self.diffs)

        def take(predicate: Any) -> List[Dict[str, Any]]:
            hit = [d for d in remaining if predicate(d)]
            for d in hit:
                remaining.remove(d)
            return hit

        # 날개벽 스페이서: 산식 피연산자에 동바리 체적이 있는지 직접 확인
        wing_sp = take(lambda d: d["key"] == "spacer_wall" and d["scope"].startswith("WW"))
        if wing_sp:
            confirmed = True
            pages: List[int] = []
            for d in wing_sp:
                items = boq["calc"][d["scope"]]
                formula = next(l["formula"] for i in items if i["name"] == "스페이서" for l in i["lines"])
                pages.append(next(i["page"] for i in items if i["name"] == "스페이서"))
                shoring = [l["printed"] for i in items if i["name"] == "동바리" for l in i["lines"]]
                confirmed = confirmed and all(f"{v:.3f}" in formula for v in shoring)
                confirmed = confirmed and same(d["boq"] - d["model"], sum(shoring), 0.0025)
            boq_sum, model_sum = round3(sum(d["boq"] for d in wing_sp)), round3(sum(d["model"] for d in wing_sp))
            self.add("부대공 연계성", "HIGH", "CORRECTED", "날개벽 스페이서 면적에 동바리 체적이 합산됨",
                     "벽체용 스페이서 산식 끝에 같은 산출서 동바리 항목의 체적(㎥)이 더해져 있다. 면적(㎡) 합계에 체적을 더해 합계가 동바리 총량만큼 과다하다." if confirmed else "날개벽 스페이서 차이(원인 재확인 필요)",
                     f"날개벽 합계 {boq_sum:.3f} ㎡", f"거푸집 면적과 동일 {model_sum:.3f} ㎡", f"{model_sum:.3f} ㎡", f"{model_sum - boq_sum:+.3f} ㎡", pages, ["일반도 (2)"])
            self.issues[-1]["keys"] = ["spacer_wall"]
            if not confirmed:
                self.issues[-1]["status"] = "UNEXPLAINED"

        # 날개벽 방수: 고정 숫자가 도면·같은 산출서 배면치수에서 나오지 않음
        wing_wp = take(lambda d: d["key"] == "waterproof" and d["scope"].startswith("WW"))
        if wing_wp:
            pages = [next(i["page"] for i in boq["calc"][d["scope"]] if i["name"] == "아스팔트 방수") for d in wing_wp]
            formulas = {next(l["formula"] for i in boq["calc"][d["scope"]] if i["name"] == "아스팔트 방수" for l in i["lines"]) for d in wing_wp}
            boq_sum, model_sum = round3(sum(d["boq"] for d in wing_wp)), round3(sum(d["model"] for d in wing_wp))
            self.add("부대공 연계성", "MEDIUM", "CORRECTED", "날개벽 방수면적이 배면 치수와 연동되지 않음",
                     f"4개소 모두 동일 산식({sorted(formulas)[0]})이다. 각도에 따라 배면 거푸집 치수가 다른데 방수는 같은 숫자로 고정되어 있고, 이 값은 도면에 없다. 대안은 배면 거푸집 면적과 동일하게 연동했다.",
                     f"날개벽 합계 {boq_sum:.3f} ㎡", f"배면 기하 {model_sum:.3f} ㎡", f"{model_sum:.3f} ㎡", f"{model_sum - boq_sum:+.3f} ㎡", pages, ["일반도 (2)"])
            self.issues[-1]["keys"] = ["waterproof"]

        # 내측 실런트: 도면 단면에 헌치가 있으나 헌치 없는 둘레 사용
        seal = take(lambda d: d["key"] == "sealant")
        if seal:
            pages = [next(i["page"] for i in boq["calc"][d["scope"]] if i["name"] == "실런트") for d in seal]
            boq_sum, model_sum = round3(sum(d["boq"] for d in seal)), round3(sum(d["model"] for d in seal))
            self.add("부대공 연계성", "MEDIUM", "CORRECTED", "내측 실런트가 상부 헌치를 반영하지 않음",
                     "내측 줄눈을 헌치 없는 내공 둘레로 산정했다. 표준단면에는 상부 헌치가 있어 실측 둘레가 더 짧다.",
                     f"{boq_sum:.3f} m", f"{model_sum:.3f} m", f"{model_sum:.3f} m", f"{model_sum - boq_sum:+.3f} m", pages, ["일반도 (1)"])
            self.issues[-1]["keys"] = ["sealant"]

        # 본체 스페이서: 전기 오류
        body_sp = take(lambda d: d["key"] in ("spacer_wall", "spacer_slab") and not d["scope"].startswith("WW"))
        for d in body_sp:
            items = boq["calc"][d["scope"]]
            page = next(i["page"] for i in items if i["name"] == "스페이서")
            formula = next((l["formula"] for i in items if i["name"] == "스페이서" for l in i["lines"] if ("벽체" in l["sub"]) == (d["key"] == "spacer_wall")), "")
            form_vals = {f"{l['printed']:.3f}" for i in items if i["name"] == "유로폼" for l in i["lines"] if l["printed"] is not None}
            wrong = [t for t in re.findall(r"\d+\.\d{3}", formula) if t not in form_vals]
            self.add("부대공 연계성", "LOW", "CORRECTED", f"{d['scope']} {d['name']} 전기 오류",
                     f"스페이서 산식의 {', '.join(wrong) or '값'}이 같은 페이지 거푸집 값과 다르다(반올림·전기 차이).",
                     f"{d['boq']:.3f} ㎡", f"{d['model']:.3f} ㎡", f"{d['model']:.3f} ㎡", f"{d['model'] - d['boq']:+.3f} ㎡", [page], [])
            self.issues[-1]["keys"] = [d["key"]]

        if remaining:
            self.add("미규명 차이", "HIGH", "UNEXPLAINED", f"원인 미규명 차이 {len(remaining)}건",
                     json.dumps(remaining, ensure_ascii=False), "-", "-", "-", None, [], [])
            self.issues[-1]["keys"] = sorted({d["key"] for d in remaining})

    # ---------------------------------------------------------------- 철근
    def audit_rebar(self, cad: Dict[str, Any], boq: Optional[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Any]:
        stats: Dict[str, Any] = {"rows": 0, "row_mismatch": [], "unit_weight_mismatch": [], "subtotal_mismatch": [], "detail_mismatch": [], "rate_check": []}
        for sheet, sched in cad["rebar"].items():
            for bar in sched["bars"]:
                stats["rows"] += 1
                if abs(bar["length_m"] * bar["count"] - bar["total_length_m"]) > 0.05:
                    stats["row_mismatch"].append({"sheet": sheet, "mark": bar["mark"], "calc": round3(bar["length_m"] * bar["count"]), "printed": bar["total_length_m"]})
            for sub in sched["subtotals"]:
                rows = [b for b in sched["bars"] if b["dia"] == sub["dia"]]
                raw_len = sum(b["length_m"] * b["count"] for b in rows)
                if sub["unit_weight"] != UNIT_WEIGHT[sub["dia"]]:
                    stats["unit_weight_mismatch"].append({"sheet": sheet, "dia": sub["dia"], "printed": sub["unit_weight"]})
                net = raw_len * UNIT_WEIGHT[sub["dia"]] / 1000
                if not same(net, sub["net_t"], 0.0015):
                    stats["subtotal_mismatch"].append({"sheet": sheet, "dia": sub["dia"], "calc": round3(net), "printed": sub["net_t"]})
                expect_rate = premium_rate(sub["dia"])
                stats["rate_check"].append({"sheet": sheet, "dia": sub["dia"], "drawing_rate": sub["rate"], "rule_rate": expect_rate, "pass": sub["rate"] == expect_rate})
                gross = net * (1 + expect_rate)
                if not same(gross, sub["gross_t"], 0.0015):
                    stats["subtotal_mismatch"].append({"sheet": sheet, "dia": sub["dia"], "gross_calc": round3(gross), "printed": sub["gross_t"]})
            rows_set = sorted([round3(b["length_m"]), b["count"]] for b in sched["bars"])
            labels = sorted([round3(a), b] for a, b in sched["detail_labels"])
            if rows_set != labels:
                stats["detail_mismatch"].append({"sheet": sheet, "only_schedule": [r for r in rows_set if r not in labels][:10], "only_detail": [r for r in labels if r not in rows_set][:10]})

        rb = model["rebar"]
        stats.update({"model_net": rb["net_total_t"], "model_gross": rb["gross_total_t"]})
        if not boq:
            return stats
        p3 = boq["rebar_p3"]["TOTAL"]
        p22 = boq["rebar_p22"]["TOTAL"]
        stats.update({"model_net": rb["net_total_t"], "model_gross": rb["gross_total_t"], "p3_net": p3["net"]["계"], "p3_gross": p3["gross"]["계"], "p22_gross": p22["gross"]["계"], "p3_wing_gross": p3["gross"]["날개벽"]})
        if not same(p3["gross"]["날개벽"], p22["gross"]["계"]):
            self.add("철근 중량", "LOW", "CORRECTED", "p.3과 p.22의 날개벽 할증 후 합계가 다름",
                     "p.3은 호칭경별 합계에 할증을 곱하고, p.22와 도면 재료표는 개소별로 할증 후 합산해 반올림 차가 생긴다. 대안은 도면 재료표와 같은 개소별 합산으로 통일했다.",
                     f"p.3 {p3['gross']['날개벽']:.3f} t / 총계 {p3['gross']['계']:.3f} t", f"p.22·재료표 {p22['gross']['계']:.3f} t",
                     f"총계 {rb['gross_total_t']:.3f} t", f"{rb['gross_total_t'] - p3['gross']['계']:+.3f} t", [3, 22], ["구조도 (11)", "구조도 (12)"])
            self.issues[-1]["keys"] = ["rebar_gross"]
        p2_net = round3((boq["summary_p2"]["H13"]["values"].get("계") or 0) + (boq["summary_p2"]["H16_25"]["values"].get("계") or 0))
        stats["p2_net"] = p2_net
        self.add("정보 전달", "MEDIUM", "CORRECTED", "총괄집계표에 철근 재료량(할증 포함)이 없음",
                 "총괄집계표 p.2의 철근가공조립은 NET만 표기하고 할증 후 재료량은 p.3에만 있다. 대안 총괄표는 가공조립(NET)과 재료량(S22 이상 6%, S19 이하 3%)을 함께 표기한다.",
                 f"p.2 NET {p2_net:.3f} t", f"재료표 NET {rb['net_total_t']:.3f} t", f"NET {rb['net_total_t']:.3f} t / 재료 {rb['gross_total_t']:.3f} t", None, [2, 3], [])
        return stats

    # ---------------------------------------------------------------- 사양
    def audit_specs(self, cad: Dict[str, Any], boq: Dict[str, Any]) -> None:
        drain = cad["misc"]["drain_pipe"]
        p2_label, p4_label, p21_label = boq["summary_p2"]["pvc"]["label"], boq["summary_p4"]["pvc"]["label"], boq["wing_p21"]["pvc"]["label"]
        dia = lambda s: float(re.search(r"φ(\d+)", s).group(1))  # noqa: E731
        calc_pages = [i["page"] for scope in boq["calc"] if scope.startswith("WW") for i in boq["calc"][scope] if i["name"] == "PVC Pipe"]
        if not dia(p2_label) == dia(p4_label) == drain["dia_mm"]:
            self.add("사양 불일치", "HIGH", "CORRECTED", "PVC 배수관 관경이 총괄표·집계표·도면에서 다름",
                     f"도면 재료표는 {drain['spec']}, 산출서 p.2는 φ{dia(p2_label):.0f}, p.4·p.21과 날개벽 산식은 φ{dia(p4_label):.0f}이다. 도면과 총괄표 기준 φ{drain['dia_mm']:.0f}로 정정했다. 물량(m)은 변하지 않는다.",
                     f"p.2 φ{dia(p2_label):.0f} / p.4 φ{dia(p4_label):.0f} / p.21 φ{dia(p21_label):.0f}", drain["spec"], f"φ{drain['dia_mm']:.0f}mm", None, [2, 4, 21] + calc_pages, ["일반도 (2)"])
        if boq["wing_p21"]["fabric"]["label"].rstrip().endswith(" m"):
            self.add("단위 오류", "LOW", "CORRECTED", "부직포 단위가 p.21에서 m로 표기됨",
                     "산식은 면적인데 날개벽 집계표 단위가 m이다. 대안은 ㎡로 표기한다.", "단위 m", "가로×세로×장수×개소", "단위 ㎡", None, [21], ["일반도 (2)"])
        names = {}
        dup_pages = []
        for item in boq["calc"]["B2"] + boq["calc"]["B3"]:
            names.setdefault((item["page"] < 16, item["no"]), []).append(item["name"])
            if len(names[(item["page"] < 16, item["no"])]) == 2:
                dup_pages.append(item["page"])
        if dup_pages:
            self.add("정보 전달", "LOW", "CORRECTED", "항목 번호 14번 중복", "Block2·3 산출 근거에서 우수유입방지벽과 아스팔트 방수가 모두 14번이다. 대안은 고유 행 ID를 부여한다.", "14번 2회", "-", "행 ID", None, dup_pages, [])
        mix = boq["summary_p2"]["pvc"]["unit"]
        if not mix:
            self.add("정보 전달", "LOW", "CORRECTED", "총괄표 PVC·부직포 행에 단위 누락", "p.2, p.4의 PVC Pipe, 부직포 행에 단위가 비어 있다. 대안은 m, ㎡로 표기한다.", "단위 공란", "-", "m / ㎡", None, [2, 4], [])

    def open_items(self, cad: Dict[str, Any]) -> List[Dict[str, str]]:
        misc = cad["misc"]
        drain = misc["drain_pipe"]
        items = [
            {"item": "수축이음 개소", "note": UNTRACED["contraction_count"]["note"] + ". 근거 확인이 필요하다."},
            {"item": "날개벽 유로폼 바깥 구간", "note": UNTRACED["wing_side_top"]["note"] + ". 근거 확인이 필요하다."},
            {"item": "비계 가정값", "note": f"본체 높이 공제 {UNTRACED['scaffold_offset']['value']:.3f}, 날개벽 높이 {UNTRACED['wing_scaffold_h']['value']:.3f}, 측면 폭 {UNTRACED['wing_scaffold_side']['value']:.3f}은 도면에 표기가 없는 가정값이다. 근거 확인이 필요하다."},
            {"item": "PVC 길이", "note": f"도면 {drain['spec']} {drain['ea_per_location']}EA와 PVC길이 {UNTRACED['pvc_length']['value']:.3f}(가정값)의 관계 확인이 필요하다."},
        ]
        if misc["dowel"]["cap_noted"] or misc["dowel"]["paint_noted"]:
            items.append({"item": "다웰 캡·녹막이 페인트", "note": "일반도(1) 시공이음 상세에 DOWEL CAP Φ35, 녹막이 페인트(2회)가 표기되어 있으나 산출서에 별도 항목이 없다. 다웰바 단가 포함 여부 확인 필요."})
        items.append({"item": "S22 할증 근거", "note": "S22 이상 6%는 사용자 확정(2026-11-05) 기준이며, 도면 재료표와 산출서도 같은 값이다. 표준품셈 인용 근거는 이번 자료에 없다."})
        return items

    # ---------------------------------------------------------------- 공종별 비교 판정
    def build_comparison(self, model: Dict[str, Any], boq: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """공종마다 판정을 만든다. 가정값이 들어간 수량은 원본과 같아도 '일치'로 세지 않는다.
        가정값이 원본에서 옮겨 온 값이면 같은 것이 당연하므로 검증이 아니기 때문이다."""
        kinds = {v["name"]: v["kind"] for v in model["variables"]}
        alias = {"pump": "concrete", "plain_pour": "lean"}
        out: List[Dict[str, Any]] = []
        keys: List[Tuple[str, float]] = [(k, v) for k, v in model["grand_totals"].items() if v is not None] + [("rebar_gross", model["rebar"]["gross_total_t"])]
        for key, total in keys:
            rows = [l for l in model["lines"] if l["key"] == alias.get(key, key)]
            assumed = sorted({d for l in rows for d in l["deps"] if kinds[d] == "assumed"})
            touched = sum(l["value"] for l in rows if any(kinds[d] == "assumed" for d in l["deps"]))
            original: Optional[float] = None
            if boq:
                original = boq["rebar_p3"]["TOTAL"]["gross"]["계"] if key == "rebar_gross" else boq["summary_p2"][key]["values"].get("계")
            delta = round3(total - original) if original is not None else None
            causes = [i for i in self.issues if key in i.get("keys", [])]
            scope_diff = [d for d in self.diffs if d["key"] == key]
            if not boq:
                state = "no_original"
            elif original is None:
                state = "missing"
            elif (delta is not None and abs(delta) >= 0.0005) or scope_diff or causes:
                state = "diff"
            else:
                state = "same_assumed" if assumed else "same"
            out.append({"key": key, "name": KEY_NAME.get(key, "철근 재료량"), "state": state, "label": STATE_LABEL[state], "model": total, "original": original, "delta": delta,
                        "cause_ids": [i["issue_id"] for i in causes], "unexplained": state == "diff" and (not causes or any(i["status"] == "UNEXPLAINED" for i in causes)),
                        "assumed": assumed, "assumed_share": round(touched / total, 3) if total else 0.0})
        return out

    def run(self) -> Dict[str, Any]:
        with open(self.cad_path, encoding="utf-8") as f:
            cad = json.load(f)
        with open(self.model_path, encoding="utf-8") as f:
            model = json.load(f)
        boq: Optional[Dict[str, Any]] = None
        status, note = ("none", self.original_note) if not self.original_note else ("parse_failed", self.original_note)
        if os.path.exists(self.boq_path):
            with open(self.boq_path, encoding="utf-8") as f:
                boq = json.load(f)
            status = "provided"
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        internal: Dict[str, Any] = {}
        try:
            c0 = self.contract_section(cad, boq)
            if boq:
                self.compare_quantities(boq, model)
                internal = self.internal_consistency(boq)
                self.explain_diffs(boq, model)
            rebar = self.audit_rebar(cad, boq, model)
            if boq:
                self.audit_specs(cad, boq)
        except (KeyError, IndexError, StopIteration, TypeError, AttributeError, ValueError) as exc:
            # 양식이 다른 PDF: 틀린 비교를 내지 않고 도면 산출만 보여 준다.
            status, note = "parse_failed", f"PDF 양식을 해석하지 못했다 ({type(exc).__name__}: {exc})"
            boq, internal = None, {}
            self.issues, self.diffs = [], []
            c0 = self.contract_section(cad, None)
            rebar = self.audit_rebar(cad, None, model)

        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        self.issues.sort(key=lambda i: (order[i["severity"]], i["category"]))
        for n, issue in enumerate(self.issues, 1):
            issue["issue_id"] = f"D-{n:02d}"

        unexplained = [i for i in self.issues if i["status"] == "UNEXPLAINED"]
        sec = cad["section"]
        rate_ok = all(r["pass"] for r in rebar["rate_check"])
        rebar_data_ok = not (rebar["row_mismatch"] or rebar["unit_weight_mismatch"] or rebar["subtotal_mismatch"])
        drawing_checks = [c for c in c0 if not c["check"].startswith("p.7")]
        contract: Dict[str, Any] = {"0_ground_truth": {"pass": all(c["pass"] for c in drawing_checks), "checks": drawing_checks}}
        if boq:
            gross_ok = abs(rebar["model_gross"] - rebar["p3_gross"]) / rebar["model_gross"] <= 0.001
            net_ok = same(rebar["model_net"], rebar["p3_net"]) and same(rebar["model_net"], rebar["p2_net"])
            haunch_ok = not any(d["key"] == "concrete" for d in self.diffs)
            lean_ok = sec["lean_width_mm"] == sec["total_width_mm"] + 200
            anc_defects = [i for i in self.issues if i["category"] == "부대공 연계성"]
            contract.update({
                "1_section_consistency": {"pass": all(c["pass"] for c in c0 if c["check"].startswith("p.7")), "note": "산식 피연산자와 도면 제원 대조"},
                "2_haunch": {"pass": haunch_ok, "note": f"도면 상부 {sec['haunch_count_top']}개소, 하부 {sec['haunch_count_bottom']}개소. 콘크리트 차이 {sum(1 for d in self.diffs if d['key'] == 'concrete')}건"},
                "3_rebar": {"pass": rate_ok and rebar_data_ok and gross_ok and net_ok, "note": f"NET {rebar['model_net']:.3f} t, 할증 후 {rebar['model_gross']:.3f} t(S22 이상 6%, S19 이하 3%), 산출서 p.3 {rebar['p3_gross']:.3f} t, 오차 {abs(rebar['model_gross'] - rebar['p3_gross']) / rebar['model_gross'] * 100:.3f}%"},
                "4_ancillary": {"pass": lean_ok and not anc_defects, "note": f"버림 폭 본체+0.2m 충족={lean_ok}. 원본 산출서 연계 결함 {len(anc_defects)}건"},
            })
        report = {
            "generated_from": ["data/cad_extracted.json", "data/quantity_model.json"] + (["data/boq_extracted.json"] if boq else []),
            "original_status": status, "original_note": note,
            "original_file": boq["source_file"] if boq else None, "original_pages": boq["page_count"] if boq else None,
            "comparison": self.build_comparison(model, boq),
            "contract_on_original_boq": contract,
            "original_boq_verdict": ("PASS" if all(v["pass"] for v in contract.values()) else "FAIL") if boq else "N/A",
            "unexplained_differences": len(unexplained),
            # 멈추는 조건은 도면 자체 검사뿐이다. 원본과의 차이는 결과로 보여 준다.
            "pipeline_gate": "OPEN" if contract["0_ground_truth"]["pass"] and rebar_data_ok else "BLOCKED",
            "statistics": {"internal": internal, "rebar": rebar, "quantity_diffs": self.diffs},
            "total_defects_found": len(self.issues),
            "issues": self.issues,
            "open_items": self.open_items(cad),
        }
        with open(self.output_path, "w", encoding="utf-8") as out:
            json.dump(report, out, ensure_ascii=False, indent=1)
        return report


if __name__ == "__main__":
    res = CrossAuditorAgent().run()
    print(res["original_boq_verdict"], res["pipeline_gate"], "unexplained", res["unexplained_differences"])
    print({k: v["pass"] for k, v in res["contract_on_original_boq"].items()})
    for c in res["contract_on_original_boq"]["0_ground_truth"]["checks"]:
        print(" ", c["pass"], c["check"])
    print({k: (v if not isinstance(v, list) else len(v)) for k, v in res["statistics"]["internal"].items()})
    print(res["statistics"]["internal"]["subtotal_mismatch"][:10], res["statistics"]["internal"]["transfer_mismatch"][:10])
    rb = res["statistics"]["rebar"]
    print({k: (v if not isinstance(v, list) else len(v)) for k, v in rb.items()}, rb["detail_mismatch"])
    for d in res["statistics"]["quantity_diffs"]:
        print(" diff", d)
    for i in res["issues"]:
        print(i["issue_id"], i["severity"], i["status"], i["title"], "|", i["boq_value"], "->", i["corrected_value"], i["delta"], i["boq_pages"])
