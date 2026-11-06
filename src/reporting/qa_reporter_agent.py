"""
Agent QA Reporter
감사 결과·대안 산출서·도면 연계 기록을 읽어 최종 보고서와 도면 변경대비표를 작성한다.
수량과 판정은 입력 파일에서 읽고, 이 파일에 직접 적지 않는다.
검증 결과(reports/verification_result.json)가 있으면 그 결과를 그대로 싣는다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class QaReporterAgent:
    def __init__(self, issues_path: str = "reports/audit_issues.json", alt_boq_path: str = "output/alternative_boq.json", cad_path: str = "data/cad_extracted.json",
                 link_path: str = "output/alternative_drawings/drawing_link_report.json", report_path: str = "reports/FINAL_AUDIT_REPORT.md",
                 matrix_path: str = "output/도면_변경대비표_14종.md", verify_path: str = "reports/verification_result.json") -> None:
        self.issues_path, self.alt_boq_path, self.cad_path, self.link_path = issues_path, alt_boq_path, cad_path, link_path
        self.report_path, self.matrix_path, self.verify_path = report_path, matrix_path, verify_path

    def matrix(self, links: Dict[str, Any], cad: Dict[str, Any], audit: Dict[str, Any]) -> str:
        out = ["# 원본 도면 대비 대안 도면 변경대비표 (14종)", "",
               "대안 도면은 원본 형상과 치수를 바꾸지 않는다. 감사 결과 정정 대상은 모두 산출서 쪽이기 때문이다. 대안 도면에 더한 것은 도면과 수량을 잇는 정보이다.", "",
               "- **레이어** `QTO-LINK`(빨강)를 도면 층 표에 정의했다. 끄면 원본과 같은 화면이 된다.",
               "- **수량 연계표**를 각 도면의 도곽 안 빈 영역에 넣었다. 값과 행 ID는 `output/alternative_boq.xlsx`와 같다.",
               "- **XDATA** `QTO_LINK`를 철근 재료표 기호 문자에 달았다. 도면, 구분, 직경, 길이, 개수, 할증률이 들어 있다.",
               "- **부재 ID 라벨**은 일반도(1) 표준단면에 넣었다. `Bn`은 블록 번호(B1~B3)이다.", "",
               "| 도면 | 실제 내용 | 소속 | 연계표 위치(X, Y) | 연계표 행 | 부재 라벨 | XDATA 연결 |", "| :--- | :--- | :---: | :--- | ---: | ---: | ---: |"]
        def order(key: str) -> tuple:
            return (not key.startswith("일반도"), int(key.split("(")[1].rstrip(")")))

        for key in sorted(links, key=order):
            rec = links[key]
            rect = rec["table_rect"]
            out.append(f"| {rec['file'].replace('.dxf', '')} | {rec['role']} | {rec['block'] or '공통'} | {rect[0]:,.0f}, {rect[1]:,.0f} | {rec['rows']} | {rec['tags']} | {rec['xdata_links']} |")
        _ = cad
        pvc = next((i for i in audit["issues"] if "PVC" in i["title"]), None)
        if pvc:
            out += ["", "## 배수관", "", f"도면 표기({pvc['drawing_value']})를 기준으로 삼았다. 도면은 고치지 않았고 산출서 표기({pvc['boq_value']})를 {pvc['corrected_value']}로 맞췄다."]
        return "\n".join(out) + "\n"

    def comparison_lines(self, audit: Dict[str, Any]) -> List[str]:
        """공종별 판정 요약. 가정값이 들어간 수량은 일치로 세지 않는다."""
        items = audit["comparison"]
        count = {s: sum(1 for c in items if c["state"] == s) for s in ("same", "same_assumed", "diff", "missing")}
        unexplained = sum(1 for c in items if c["unexplained"])
        out = [f"공종 {len(items)}개 중 도면 근거로 일치 {count['same']}개, 가정값에 의존해 일치 {count['same_assumed']}개, 차이 {count['diff']}개(원인 미규명 {unexplained}개), 원본에 없음 {count['missing']}개이다.", ""]
        if count["same_assumed"]:
            out += ["**가정값 의존 일치는 검증이 아니다.** 도면에 없는 입력이 들어 있다. 원본 값을 옮겨 넣었다면 같은 것이 당연하다.", "",
                    "| 공종 | 수량 | 들어간 가정값 | 가정값이 닿는 수량 비율 |", "| :--- | ---: | :--- | ---: |"]
            out += [f"| {c['name']} | {c['model']:,.3f} | {', '.join(c['assumed'])} | {'1% 미만' if c['assumed_share'] < 0.01 else format(c['assumed_share'], '.0%')} |" for c in items if c["state"] == "same_assumed"]
            out.append("")
        return out

    def report_without_original(self, audit: Dict[str, Any], alt: Dict[str, Any], verify: Optional[Dict[str, Any]]) -> str:
        reason = audit["original_note"] or "원본 수량산출서가 제공되지 않았다"
        lines = ["# 통로암거 도면 수량 산출 보고서", "", "## 1. 결론", "", f"{reason}. 그래서 원본과 비교하지 않고 도면에서 읽은 값으로만 산출했다.", "",
                 "## 2. 산출 수량", "", "| 공종 | 규격 | 단위 | 수량 | 가정값 사용 |", "| :--- | :--- | :---: | ---: | :--- |"]
        lines += [f"| {s['work']} | {s['spec']} | {s['unit']} | {s['total']:,.3f} | {', '.join(s['assumed']) or '-'} |" for s in alt["summary"] if s["total"] is not None]
        rb = alt["rebar"]
        lines += [f"| 철근 재료량 | 할증 포함 | t | {rb['gross_total_t']:,.3f} | - |", "", "## 3. 확인 요청", "", "| 항목 | 내용 |", "| :--- | :--- |"]
        lines += [f"| {o['item']} | {o['note']} |" for o in audit["open_items"]]
        lines += ["", "## 4. 검증 상태", "", f"독립 검증: **{verify['verdict']}**, {verify['passed']}/{verify['total']} 항목 통과." if verify else "독립 검증 전이다.", ""]
        return "\n".join(lines)

    def report(self, audit: Dict[str, Any], alt: Dict[str, Any], cad: Dict[str, Any], links: Dict[str, Any], verify: Optional[Dict[str, Any]]) -> str:
        if audit["original_status"] != "provided":
            return self.report_without_original(audit, alt, verify)
        sec = cad["section"]
        stats = audit["statistics"]
        internal, rebar = stats["internal"], stats["rebar"]
        contract = audit["contract_on_original_boq"]
        changed = [s for s in alt["summary"] if s["changed"]]
        same_count = len(alt["summary"]) - len(changed)
        dim_total = sum(s.get("dimension_entities", 0) for s in cad["sheets"].values())
        text_dim_total = sum(len(s["dims"]) for s in cad["sheets"].values())
        page_count = audit["original_pages"]
        status = {"CORRECTED": "정정", "CORRECTED_CONFIRM": "정정·확인", "UNEXPLAINED": "미규명"}

        lines: List[str] = [f"# 통로암거 Sta.{cad['project']['station']} 도면-수량산출서 교차 감사 보고서", ""]
        high = [i for i in audit["issues"] if i["severity"] == "HIGH"]
        lines += ["## 1. 결론", "",
                  f"결함 {audit['total_defects_found']}건을 확인했다." + (f" 수량 영향이 가장 큰 항목은 {high[0]['issue_id']} {high[0]['title']}({high[0]['delta']})이다." if high else ""), ""]
        lines += self.comparison_lines(audit)
        lines += ["Sprint Contract 판정: " + ", ".join(f"{k.split('_')[0]}항 {'PASS' if v['pass'] else 'FAIL'}" for k, v in contract.items()) + f". 미규명 차이는 {audit['unexplained_differences']}건이다.", ""]
        if high:
            lines += ["**우선 조치**", ""] + [f"- {i['issue_id']} {i['title']}: {i['boq_value']} → {i['corrected_value']}" for i in high] + [""]
        lines += ["## 2. 검토 대상과 방법", "",
                  "- **도면:** DXF 14종(일반도 2, 구조도 12). 치수 문자와 콘크리트 선형을 함께 읽었다.",
                  f"- **산출서:** PDF {page_count}쪽. 집계표와 산식 {internal['formula_lines']}행을 추출해 숫자 산식 {internal['formula_evaluated']}행을 다시 계산했다.",
                  f"- **철근:** 도면 재료표 {rebar['rows']}행을 길이×개수×단위중량으로 다시 계산했다.",
                  f"- **수량 모델:** 도면에서 읽은 변수 {sum(1 for v in alt['variables'] if v['kind'] == 'drawing')}개로 {len(alt['lines'])}개 행을 독립 계산해 산출서와 공종·구역별로 대조했다. 도면에 없는 값 {sum(1 for v in alt['variables'] if v['kind'] == 'assumed')}개는 가정으로 표시했다.", ""]
        sec_ok = "일치" if contract["1_section_consistency"]["pass"] else "불일치 (4절)"
        lines += ["## 3. 도면 실측 제원", "", "| 항목 | 실측 | 산출서 |", "| :--- | ---: | :---: |",
                  f"| 내공 폭 × 높이 | {sec['inner_width_mm']:.0f} × {sec['inner_height_mm']:.0f} mm | {sec_ok} |",
                  f"| 외곽 폭 | {sec['total_width_mm']:.0f} mm | {sec_ok} |", f"| 외곽 높이 | {sec['total_height_mm']:.0f} mm | {sec_ok} |",
                  f"| 상부·하부 슬래브 | {sec['top_slab_t_mm']:.0f} / {sec['bot_slab_t_mm']:.0f} mm | {sec_ok} |", f"| 측벽 | {sec['wall_t_mm']:.0f} mm | {sec_ok} |",
                  f"| 헌치 | {sec['haunch_w_mm']:.0f}×{sec['haunch_h_mm']:.0f} mm, 상부 {sec['haunch_count_top']}개소, 하부 {sec['haunch_count_bottom']}개소 | {sec_ok} |",
                  f"| 버림 콘크리트 | 폭 {sec['lean_width_mm']:.0f}, 두께 {sec['lean_t_mm']:.0f} mm | - |", ""]
        names = {"0_ground_truth": "0. 실측 무결성", "1_section_consistency": "1. 단면 치수", "2_haunch": "2. 헌치 체적", "3_rebar": "3. 철근 중량·할증", "4_ancillary": "4. 부대공 연계"}
        lines += ["## 4. Sprint Contract 판정 (원본 산출서)", "", "| 항목 | 판정 | 근거 |", "| :--- | :---: | :--- |"]
        for key, name in names.items():
            note = contract[key].get("note") or f"{sum(1 for c in contract[key].get('checks', []) if c['pass'])}/{len(contract[key].get('checks', []))} 검사 통과"
            lines.append(f"| {name} | {'PASS' if contract[key]['pass'] else 'FAIL'} | {note} |")
        lines += ["", "## 5. 결함 목록", "", "| ID | 심각도 | 상태 | 내용 | 원본 | 대안 | 증감 | 산출서 쪽 |", "| :--- | :---: | :---: | :--- | :--- | :--- | ---: | :--- |"]
        for i in audit["issues"]:
            lines.append(f"| {i['issue_id']} | {i['severity']} | {status[i['status']]} | {i['title']} | {i['boq_value']} | {i['corrected_value']} | {i['delta'] or '-'} | {', '.join(map(str, i['boq_pages']))} |")
        lines += ["", "**상세**", ""]
        lines += [f"- **{i['issue_id']}** {i['detail']}" for i in audit["issues"] if i["severity"] != "LOW"]
        lines += ["", "## 6. 수량 비교", "", f"총괄 {len(alt['summary'])}개 행 중 {same_count}개 행은 원본과 같다. 값이 달라진 행과 철근 재료량은 아래와 같다.", "",
                  "| 공종 | 규격 | 단위 | 원본 | 대안 | 증감 |", "| :--- | :--- | :---: | ---: | ---: | ---: |"]
        for s in changed:
            lines.append(f"| {s['work']} | {s['spec']} | {s['unit']} | {s['original']:,.3f} | {s['total']:,.3f} | {s['delta']:+,.3f} |")
        rb = alt["rebar"]
        lines.append(f"| 철근 재료량 | 할증 포함 | t | {rebar['p3_gross']:,.3f} | {rb['gross_total_t']:,.3f} | {rb['gross_total_t'] - rebar['p3_gross']:+,.3f} |")
        lines += ["", "도면 근거로 일치한 항목: " + ", ".join(f"{s['work']}({s['spec']}) {s['total']:,.3f}{s['unit']}" for s in alt["summary"] if s["state"] == "same") + ".", "",
                  "가정값에 의존해 일치한 항목(검증 아님): " + (", ".join(f"{s['work']}({s['spec']}) {s['total']:,.3f}{s['unit']}" for s in alt["summary"] if s["state"] == "same_assumed") or "없음") + ".", ""]
        lines += ["## 7. 정보 전달의 문제와 대안", "", "| 문제 | 근거 | 대안 |", "| :--- | :--- | :--- |",
                  f"| 도면 치수가 분해된 문자이다 | DIMENSION 객체 {dim_total}개, 치수 문자 값 {text_dim_total}종. 치수 변경이 형상이나 수량으로 전달되지 않는다 | 수량 모델이 선형 실측과 치수 문자를 함께 검사한다 |",
                  "| 산출서 행과 도면 부재를 잇는 식별자가 없다 | 산출서는 ①~⑦ 표기만 있고 도면에는 대응 기호가 없다 | 부재 ID와 행 ID를 부여하고 도면 연계표로 연결한다 |",
                  "| 같은 계산을 개소마다 복제한다 | 날개벽 개소마다 산식이 반복되고, 방수 산식은 각도가 달라도 같은 숫자로 복제되었다 | 산식 하나를 개소 제원으로 계산한다 |",
                  "| 값을 손으로 옮겨 적는다 | 거푸집 값과 스페이서 합산 값이 다르고, 동바리 체적이 스페이서에 섞였다 | 합계는 원본 행의 수식으로 집계한다 |",
                  "| 같은 사양이 여러 곳에 따로 적힌다 | PVC 관경이 표마다 다르다 | 사양을 한 곳에서 관리한다 |",
                  "| 총괄표가 철근 재료량을 보여 주지 않는다 | 총괄표는 NET만, 할증 후 값은 철근 집계표에만 있다 | 총괄표에 NET과 재료량을 함께 표기한다 |", ""]
        lines += ["## 8. 대안 성과물", "", "| 파일 | 내용 |", "| :--- | :--- |",
                  f"| `output/대안_수량산출서_Sta.{cad['project']['station']}.html` | 대안 수량산출서 본문. 산식을 변수로 쓰고 값은 도면에서 읽어 넣는다. 변수 값을 바꾸면 수량이 다시 계산된다 |",
                  f"| `output/alternative_boq.xlsx` | 계산 원본. `변수` 시트의 이름 정의를 산출 {len(alt['lines'])}행이 참조하고, 철근 {rebar['rows']}행과 함께 수식으로 총괄표까지 연결된다 |",
                  "| `output/alternative_boq.json` | 같은 내용의 기계 판독용 데이터 |",
                  f"| `output/alternative_drawings/대안_*.dxf` | {len(links)}종. 원본 객체 유지, 수량 연계표·부재 라벨·XDATA {sum(r['xdata_links'] for r in links.values())}건 추가 |",
                  "| `output/alternative_drawings/element_map.json`, `alternative_culvert_section.svg` | 부재 ID 연계표, 표준단면 부재도 |", "| `output/도면_변경대비표_14종.md` | 도면별 변경 내역 |", ""]
        lines += ["## 9. 설계자 확인 요청", "", "| 항목 | 내용 |", "| :--- | :--- |"] + [f"| {o['item']} | {o['note']} |" for o in audit["open_items"]] + [""]
        lines += ["## 10. 검증 상태와 한계", ""]
        if verify:
            lines.append(f"대안 성과물의 독립 검증(`tests/verify_deliverables.py`): **{verify['verdict']}**, {verify['passed']}/{verify['total']} 항목 통과. 원본 산출서에서 FAIL인 계약 4항의 연계 기하도 이 검증에 포함된다.")
            lines += [f"- 실패: {c['name']} — {c['detail']}" for c in verify["checks"] if not c["pass"]]
        else:
            lines.append("독립 검증 전이다.")
        lines += ["", "- AutoCAD로 대안 DXF를 열어 보지 못했다. ezdxf 읽기와 렌더링으로만 확인했다.",
                  "- Excel로 xlsx를 열어 보지 못했다. 수식은 별도 계산기로 재계산해 확인했으며, 값은 파일을 열 때 계산된다.",
                  "- 일부 입력은 도면에 치수가 없어 산출서 값을 그대로 썼다(9절). 이 값들의 타당성은 검증하지 못했다.",
                  "- 설계 계산의 적정성(구조 안전성, 배근 간격)은 범위 밖이다.", ""]
        # 이 과업에만 해당하는 서술은 공개 코드에 두지 않는다
        if os.path.exists("private/report_notes.md"):
            with open("private/report_notes.md", encoding="utf-8") as f:
                lines += [f.read()]
        return "\n".join(lines)

    def run(self) -> Dict[str, Any]:
        audit, alt, cad, links = load(self.issues_path), load(self.alt_boq_path), load(self.cad_path), load(self.link_path)
        verify = load(self.verify_path) if os.path.exists(self.verify_path) else None
        os.makedirs(os.path.dirname(self.report_path), exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write(self.report(audit, alt, cad, links, verify))
        with open(self.matrix_path, "w", encoding="utf-8") as f:
            f.write(self.matrix(links, cad, audit))
        return {"status": "success", "report": self.report_path, "matrix": self.matrix_path}


if __name__ == "__main__":
    print(QaReporterAgent().run())
