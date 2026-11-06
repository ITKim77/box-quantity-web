"""
웹 서비스 진입점. 스레드와 하위 프로세스를 쓰지 않아 브라우저 안의 Python(Pyodide)에서도 돈다.
현재 폴더에 결과를 쓴다. 호출하는 쪽이 요청마다 빈 작업 폴더를 준다.
run은 웹 화면용 산출서를 만들고, export는 화면에 반영된 입력값으로 내려받을 파일을 만든다.
대안 DXF와 보고서는 만들지 않는다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from src.auditor.cross_auditor_agent import CrossAuditorAgent
from src.generator.alternative_synthesizer import AlternativeSynthesizerAgent
from src.generator.readable_boq import ReadableBoqAgent
from src.model.quantity_model import QuantityModelAgent, build_model
from src.parsers.boq_agent import BoqParseError, BoQParserAgent
from src.parsers.cad_agent import CadParseError, CadParserAgent

EXPORT_DIR = "output/export"
EXPORT_HTML, EXPORT_XLSX = "수량산출서.html", "수량산출서.xlsx"
BAD_INPUT = (KeyError, IndexError, StopIteration, TypeError, AttributeError, ValueError)


def fail(message: str) -> Dict[str, Any]:
    return {"status": "input_error", "message": message}


def run(docs_dir: str, pdf_path: Optional[str]) -> Dict[str, Any]:
    """도면을 읽어 산출서를 만든다. 틀린 수량 대신 이유를 돌려주므로 입력 문제로 예외를 던지지 않는다."""
    for folder in ("data", "output", "reports"):
        os.makedirs(folder, exist_ok=True)
    try:
        CadParserAgent(docs_dir=docs_dir).run()
    except CadParseError as exc:
        return fail(str(exc))
    except BAD_INPUT as exc:
        return fail(f"통로암거 도면 양식으로 해석하지 못했습니다 ({type(exc).__name__}: {exc})")

    note = ""
    if pdf_path:
        try:
            BoQParserAgent(pdf_path=pdf_path).run()
        except Exception as exc:  # noqa: BLE001 - 어떤 PDF가 와도 도면 산출은 계속한다
            if os.path.exists("data/boq_extracted.json"):
                os.remove("data/boq_extracted.json")
            note = str(exc) if isinstance(exc, BoqParseError) else f"{os.path.basename(pdf_path)}를 읽지 못했습니다 ({type(exc).__name__})"

    model = QuantityModelAgent().run()
    audit = CrossAuditorAgent(original_note=note).run()
    if audit["pipeline_gate"] != "OPEN":
        failed = [c["check"] for c in audit["contract_on_original_boq"]["0_ground_truth"]["checks"] if not c["pass"]]
        return fail("도면 치수끼리 맞지 않아 산출하지 않습니다: " + ("; ".join(failed) or "철근 재료표의 합계가 행 합과 다릅니다"))
    AlternativeSynthesizerAgent().run()
    page = ReadableBoqAgent().run()
    items = [{k: c[k] for k in ("key", "name", "state", "label", "model", "original", "delta", "unexplained")} for c in audit["comparison"]]
    return {"status": "success", "html": page["path"],
            "original_status": audit["original_status"], "original_note": audit["original_note"], "comparison": items,
            "totals": model["grand_totals"], "rebar_gross": model["rebar"]["gross_total_t"]}


def export(inputs: Optional[Dict[str, float]] = None, bars: Optional[List[Dict[str, Any]]] = None, reference: bool = False) -> Dict[str, str]:
    """화면에 반영된 입력값으로 내려받을 파일을 만든다. html은 입력칸과 스크립트가 없고 xlsx는 값만 담는다.
    bars는 고친 철근 재료표 행이다: {"i": 재료표 전체에서의 순번, "L": 1개 길이, "N": 개수}"""
    with open("data/cad_extracted.json", encoding="utf-8") as f:
        cad = json.load(f)
    edits = {b["i"]: b for b in bars or []}
    row = 0
    for sched in cad["rebar"].values():
        for bar in sched["bars"]:
            if row in edits:
                bar["length_m"], bar["count"] = edits[row]["L"], edits[row]["N"]
            row += 1
    model = build_model(cad, inputs or {})
    model["reference"] = reference
    os.makedirs(EXPORT_DIR, exist_ok=True)
    cad_path, model_path = os.path.join(EXPORT_DIR, "cad.json"), os.path.join(EXPORT_DIR, "model.json")
    for path, content in ((cad_path, cad), (model_path, model)):
        with open(path, "w", encoding="utf-8") as out:
            json.dump(content, out, ensure_ascii=False)
    AlternativeSynthesizerAgent(cad_path=cad_path, model_path=model_path, output_dir=EXPORT_DIR, xlsx_name=EXPORT_XLSX).run()
    html_path = os.path.join(EXPORT_DIR, EXPORT_HTML)
    ReadableBoqAgent(cad_path=cad_path, model_path=model_path, alt_path=os.path.join(EXPORT_DIR, "alternative_boq.json"), output_path=html_path, frozen=True).run()
    return {"html": html_path, "xlsx": os.path.join(EXPORT_DIR, EXPORT_XLSX)}
