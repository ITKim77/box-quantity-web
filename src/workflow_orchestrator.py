"""
Workflow Orchestrator
파싱 → 수량 모델 → 도면 검사와 원본 비교 → 산출서 생성 → 독립 검증 → 보고 순서로 실행한다.
도면 입력은 필수이고 원본 수량산출서 PDF는 선택이다. 원본이 있으면 비교 결과를, 없으면 도면 산출만 보여 준다.
    python src/workflow_orchestrator.py                  docs/의 PDF가 있으면 비교
    python src/workflow_orchestrator.py --boq 경로.pdf    지정한 PDF와 비교
    python src/workflow_orchestrator.py --no-boq         원본 없이 도면만으로 산출
    python src/workflow_orchestrator.py --docs 폴더 --assumptions 가정값.json   다른 도면으로 산출
도면이 지원하는 양식이 아니면 이유를 알려 주고 멈춘다(종료 코드 2). 원본 PDF만 읽지 못하면 도면 산출은 계속하고 이유를 보여 준다.
도면 자체 검사가 실패하거나 독립 검증이 실패하면 성공으로 표시하지 않는다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auditor.cross_auditor_agent import CrossAuditorAgent  # noqa: E402
from src.generator.alternative_synthesizer import AlternativeSynthesizerAgent  # noqa: E402
from src.generator.dxf_alternative_generator import generate_alternative_dxfs  # noqa: E402
from src.generator.readable_boq import ReadableBoqAgent  # noqa: E402
from src.model.quantity_model import ASSUMPTION_FIELDS, REFERENCE_ASSUMPTIONS, QuantityModelAgent  # noqa: E402
from src.parsers.boq_agent import BoQParserAgent  # noqa: E402
from src.parsers.cad_agent import CadParseError, CadParserAgent  # noqa: E402
from src.reporting.qa_reporter_agent import QaReporterAgent  # noqa: E402


BOQ_JSON = "data/boq_extracted.json"


def parse_original(pdf_path: Optional[str]) -> str:
    """원본 PDF를 읽는다. 없으면 이전 실행의 추출값이 비교에 섞이지 않게 지운다. 읽지 못하면 사유를 돌려준다."""
    if os.path.exists(BOQ_JSON):
        os.remove(BOQ_JSON)
    if not pdf_path:
        return ""
    try:
        BoQParserAgent(pdf_path=pdf_path).run()
    except Exception as exc:  # noqa: BLE001 - 어떤 PDF가 와도 도면 산출은 계속한다
        if os.path.exists(BOQ_JSON):
            os.remove(BOQ_JSON)
        return f"{os.path.basename(pdf_path)}를 읽지 못했다 ({type(exc).__name__}: {exc})"
    return ""


def input_error(message: str) -> Dict[str, Any]:
    """입력이 지원 범위 밖일 때: 틀린 수량을 내지 않고 이유를 남긴다."""
    os.makedirs("reports", exist_ok=True)
    with open("reports/input_check.json", "w", encoding="utf-8") as out:
        json.dump({"ok": False, "message": message}, out, ensure_ascii=False, indent=1)
    print(f"[입력 오류] {message}", file=sys.stderr)
    return {"status": "input_error", "message": message}


def execute(pdf_path: Optional[str] = None, docs_dir: str = "docs", assumptions: str = "") -> Dict[str, Any]:
    start = time.time()
    reference = docs_dir == "docs" and not assumptions and os.path.exists(REFERENCE_ASSUMPTIONS) and os.path.exists("tests/verify_deliverables.py")
    if not reference and not assumptions:
        return input_error("이 도면의 가정값이 필요합니다. --assumptions 로 다음 값을 담은 JSON을 주세요: " + "; ".join(f"{k} = {v}" for k, v in ASSUMPTION_FIELDS.items()))
    if os.path.exists("reports/input_check.json"):
        os.remove("reports/input_check.json")
    print("[1/6] 파싱 (DXF" + (", 원본 PDF" if pdf_path else ", 원본 없음") + ")")
    with ThreadPoolExecutor(max_workers=2) as pool:
        cad_future = pool.submit(CadParserAgent(docs_dir=docs_dir).run)
        boq_future = pool.submit(parse_original, pdf_path)
        original_note = boq_future.result()
        try:
            cad = cad_future.result()
        except CadParseError as exc:
            return input_error(str(exc))
        except (KeyError, IndexError, StopIteration, TypeError, AttributeError, ValueError) as exc:
            return input_error(f"통로암거 도면 양식으로 해석하지 못했습니다 ({type(exc).__name__}: {exc})")
    print(f"  도면 {len(cad['sheets'])}종, 재료표 {sum(len(v['bars']) for v in cad['rebar'].values())}행" + (f", 원본 해석 실패: {original_note}" if original_note else ""))

    print("[2/6] 수량 모델")
    try:
        model = QuantityModelAgent(assumptions_path=assumptions).run()
    except (ValueError, OSError) as exc:
        return input_error(str(exc))
    print(f"  산출 {len(model['lines'])}행, 철근 NET {model['rebar']['net_total_t']} t, 재료 {model['rebar']['gross_total_t']} t")

    print("[3/6] 도면 검사와 원본 비교")
    audit = CrossAuditorAgent(original_note=original_note).run()
    states: Dict[str, int] = {}
    for item in audit["comparison"]:
        states[item["label"]] = states.get(item["label"], 0) + 1
    print(f"  원본 {audit['original_status']}, 판정 {states}, 미규명 {audit['unexplained_differences']}건, 도면 검사 {audit['pipeline_gate']}")
    if audit["pipeline_gate"] != "OPEN":
        failed = [c["check"] for c in audit["contract_on_original_boq"]["0_ground_truth"]["checks"] if not c["pass"]]
        return input_error("도면 치수끼리 맞지 않아 산출하지 않습니다: " + ("; ".join(failed) or "철근 재료표의 합계가 행 합과 다릅니다"))

    print("[4/6] 대안 생성 (DXF, 수량산출서 병렬)")
    # 보고서에는 이전 실행의 검증 결과를 싣지 않는다.
    if os.path.exists("reports/verification_result.json"):
        os.remove("reports/verification_result.json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        dxf_future = pool.submit(generate_alternative_dxfs, input_dir=docs_dir)
        syn_future = pool.submit(AlternativeSynthesizerAgent().run)
        links = dxf_future.result()
        syn = syn_future.result()
    readable = ReadableBoqAgent().run()
    print(f"  DXF {len(links)}종, 산출 {syn['lines']}행, 쉬운 산출서 카드 {readable['cards']}개")
    QaReporterAgent().run()

    if not reference:
        QaReporterAgent().run()
        print("[완료] 기준 과업 회귀 시험은 이 도면에 적용하지 않습니다. 도면 자체 검사는 통과했습니다." + f" {time.time() - start:.1f}초")
        return {"status": "success", "defects": audit["total_defects_found"]}

    print("[5/6] 독립 검증")
    parametric = subprocess.run([sys.executable, "tests/test_parametric.py"], check=False)
    modes = subprocess.run([sys.executable, "tests/test_modes.py"], check=False)
    verify = subprocess.run([sys.executable, "tests/verify_deliverables.py"], check=False)

    print("[6/6] 보고서 확정")
    QaReporterAgent().run()
    verified = verify.returncode == 0 and parametric.returncode == 0 and modes.returncode == 0
    print(("[완료]" if verified else "[실패] 독립 검증 FAIL") + f" {time.time() - start:.1f}초")
    return {"status": "success" if verified else "verification_failed", "defects": audit["total_defects_found"]}


def main() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description="도면에서 수량을 산출하고 원본 수량산출서와 비교한다")
    parser.add_argument("--boq", help="비교할 원본 수량산출서 PDF")
    parser.add_argument("--no-boq", action="store_true", help="원본 없이 도면만으로 산출")
    parser.add_argument("--docs", default="docs", help="DXF 도면 폴더")
    parser.add_argument("--assumptions", default="", help="도면에 없는 가정값 JSON (--docs 로 다른 도면을 줄 때 필수)")
    args = parser.parse_args()
    if args.no_boq:
        return execute(None, args.docs, args.assumptions)
    if args.boq:
        return execute(args.boq, args.docs, args.assumptions)
    found = glob.glob(os.path.join(args.docs, "*.pdf"))
    return execute(found[0] if len(found) == 1 else None, args.docs, args.assumptions)


if __name__ == "__main__":
    result = main()
    sys.exit({"success": 0, "input_error": 2}.get(result["status"], 1))
