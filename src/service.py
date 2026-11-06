"""
웹 서비스 진입점. 스레드와 하위 프로세스를 쓰지 않아 브라우저 안의 Python(Pyodide)에서도 돈다.
현재 폴더에 결과를 쓴다. 호출하는 쪽이 요청마다 빈 작업 폴더를 준다.
대안 DXF와 보고서는 만들지 않는다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from src.auditor.cross_auditor_agent import CrossAuditorAgent
from src.generator.alternative_synthesizer import AlternativeSynthesizerAgent
from src.generator.readable_boq import ReadableBoqAgent
from src.model.quantity_model import ASSUMPTION_FIELDS, QuantityModelAgent
from src.parsers.boq_agent import BoqParseError, BoQParserAgent
from src.parsers.cad_agent import CadParseError, CadParserAgent

BAD_INPUT = (KeyError, IndexError, StopIteration, TypeError, AttributeError, ValueError)


def fail(message: str) -> Dict[str, Any]:
    return {"status": "input_error", "message": message}


def run(docs_dir: str, pdf_path: Optional[str], assumptions: Dict[str, Any]) -> Dict[str, Any]:
    """도면을 읽어 산출서를 만든다. 틀린 수량 대신 이유를 돌려주므로 입력 문제로 예외를 던지지 않는다."""
    absent = [v for k, v in ASSUMPTION_FIELDS.items() if k not in assumptions]
    if absent:
        return fail("가정값이 필요합니다: " + ", ".join(absent))
    for folder in ("data", "output", "reports"):
        os.makedirs(folder, exist_ok=True)
    with open("data/assumptions.json", "w", encoding="utf-8") as out:
        json.dump(assumptions, out, ensure_ascii=False)
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

    model = QuantityModelAgent(assumptions_path="data/assumptions.json").run()
    audit = CrossAuditorAgent(original_note=note).run()
    if audit["pipeline_gate"] != "OPEN":
        failed = [c["check"] for c in audit["contract_on_original_boq"]["0_ground_truth"]["checks"] if not c["pass"]]
        return fail("도면 치수끼리 맞지 않아 산출하지 않습니다: " + ("; ".join(failed) or "철근 재료표의 합계가 행 합과 다릅니다"))
    AlternativeSynthesizerAgent().run()
    page = ReadableBoqAgent().run()
    items = [{k: c[k] for k in ("key", "name", "state", "label", "model", "original", "delta", "unexplained")} for c in audit["comparison"]]
    return {"status": "success", "html": page["path"], "xlsx": "output/alternative_boq.xlsx", "json": "output/alternative_boq.json",
            "original_status": audit["original_status"], "original_note": audit["original_note"], "comparison": items,
            "totals": model["grand_totals"], "rebar_gross": model["rebar"]["gross_total_t"]}
