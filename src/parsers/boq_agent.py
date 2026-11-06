"""
Agent BoQ Parser
수량산출서 PDF를 단어 좌표 단위로 읽어 집계표와 산식 전 행을 추출하고, 각 산식을 그 자리에서 재계산한다.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

Word = Dict[str, Any]

CIRCLED = "①②③④⑤⑥⑦⑧⑨"
SUMMARY_KEYS: List[Tuple[str, str]] = [
    ("concrete", "25-30-15"), ("lean", "40-15-8"), ("pump", "펌프카타설"), ("plain_pour", "VIB제외"),
    ("form_normal", "보통"), ("form_simple", "간단"), ("shoring", "시스템동바리"), ("scaffold", "시스템비계"),
    ("spacer_wall", "벽체용"), ("spacer_slab", "슬래브 및 기초용"), ("dowel", "H32"),
    ("joint_clean", "시공이음 면정리"), ("swell", "수팽창성 지수제"), ("waterstop", "230 x 9.5"),
    ("sealant", "20 x 25"), ("styrofoam", "20mm"), ("rain_wall", "fck = 30MPa"), ("waterproof", "2회"),
    ("pvc", "φ"), ("fabric", "300 x 300mm"), ("rubble", "잡석채움"),
    ("D10", "D10이하"), ("D13", "D13("), ("D16_25", "D16~25"), ("D29_51", "D29~51"),
    ("H10", "H10이하"), ("H13", "H13("), ("H16_25", "H16~25"), ("H29_51", "H29~51"),
    ("curing", "콘크리트 양생"), ("contraction", "수축이음"),
]


class BoqParseError(RuntimeError):
    """산출서 구조를 해석하지 못한 경우."""


def rows_of(words: List[Word], tol: float = 4.0) -> List[Tuple[float, List[Word]]]:
    """y 좌표가 가까운 단어를 한 행으로 묶는다(폰트별 top 편차 흡수)."""
    rows: List[Tuple[float, List[Word]]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and abs(rows[-1][0] - w["top"]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append((w["top"], [w]))
    return [(y, sorted(r, key=lambda w: w["x0"])) for y, r in rows]


def to_num(text: str) -> Optional[float]:
    text = text.strip().replace(",", "")
    return float(text) if re.fullmatch(r"\d+(\.\d+)?", text) else None


def normalise_formula(text: str) -> str:
    s = text.replace("x", "*").replace("{", "(").replace("}", ")").replace("²", "**2").replace(" ", "")
    s = s.replace("√", "sqrt")
    s = re.sub(r"\bsin\(([\d.]+)\)", r"sin(radians(\1))", s)
    s = re.sub(r"\bcos\(([\d.]+)\)", r"cos(radians(\1))", s)
    return s


def evaluate(formula: str) -> float:
    allowed = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "radians": math.radians}
    return float(eval(normalise_formula(formula), {"__builtins__": {}}, allowed))  # noqa: S307 - 숫자·허용 함수만


def is_formula_text(text: str) -> bool:
    return not re.search(r"[가-힣※\[\]~]", text) and bool(re.search(r"\d", text))


def parse_calc_pages(pdf: Any, pages: List[int]) -> List[Dict[str, Any]]:
    """산출 근거 페이지를 항목·행 구조로 변환한다."""
    items: List[Dict[str, Any]] = []
    item: Optional[Dict[str, Any]] = None
    sub = ""
    tag = ""
    buf: List[str] = []
    for page_no in pages:
        words = pdf.pages[page_no - 1].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
        rows = rows_of(words)
        # 쪽 머리: 공사명 줄과 '공 종' 머리글 줄까지 건너뛴다. 공사명은 과업마다 다르다.
        heads = [i for i, (_, r) in enumerate(rows[:4]) if r[0]["text"].strip().startswith("공")]
        for _, row in rows[heads[0] + 1 if heads else 0:]:
            first = row[0]["text"].strip()
            if first.startswith("공"):
                continue
            label = " ".join(w["text"].strip() for w in row if w["x0"] < 138)
            equal = [w for w in row if w["text"].strip() == "=" and 405 <= w["x0"] < 440]
            body = [w for w in row if 138 <= w["x0"] < 417 and w["text"].strip() != "="]
            value_w = [w for w in row if 440 <= w["x0"] < 497]
            sub_w = [w for w in row if 497 <= w["x0"] < 535]

            head = re.match(r"(\d+)\.\s*([^\d\s].*)", label)
            if head:
                name = head.group(2).strip()
                if not item or item["no"] != int(head.group(1)) or item["name"] != name:
                    item = {"no": int(head.group(1)), "name": name, "page": page_no, "lines": [], "subtotals": []}
                    items.append(item)
                    sub = ""
                buf = []
            elif label and item:
                item.setdefault("labels", []).append(label)
            if item is None:
                continue

            text = " ".join(w["text"].strip() for w in body).strip()
            if text and text[0] in CIRCLED:
                tag = text[0]
                text = text[1:].strip()
            if text and not is_formula_text(text):
                if not equal:
                    sub = text
                    buf = []
                    text = ""
            if text:
                buf.append(text)
            if equal:
                raw_value = value_w[0]["text"].strip() if value_w else ""
                formula = " ".join(buf).strip()
                record: Dict[str, Any] = {"page": page_no, "sub": sub, "tag": tag, "formula": formula, "printed": to_num(raw_value), "printed_raw": raw_value}
                if formula and is_formula_text(formula):
                    try:
                        record["calc"] = round(evaluate(formula) + 1e-9, 3)
                    except Exception as exc:  # 산식 해석 실패는 숨기지 않고 기록한다
                        record["eval_error"] = str(exc)
                item["lines"].append(record)
                buf = []
                tag = ""
            for w in sub_w:
                num = to_num(w["text"])
                if num is not None:
                    item["subtotals"].append({"sub": sub, "value": num, "page": page_no})
    return items


def parse_summary(pdf: Any, page_no: int, columns: List[str]) -> Dict[str, Any]:
    words = pdf.pages[page_no - 1].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    rows = rows_of(words, tol=2.5)
    header_x: Dict[str, float] = {}
    unit_x = 0.0
    for w in words:
        label = w["text"].strip()
        if label == "단위":
            unit_x = (w["x0"] + w["x1"]) / 2
        for col in columns:
            if label == col or (col == "일체식날개벽" and label == "일체식날개"):
                header_x[col] = (w["x0"] + w["x1"]) / 2
    if len(header_x) != len(columns) or not unit_x:
        raise BoqParseError(f"p.{page_no} 머리글 해석 실패: {header_x}")

    out: Dict[str, Any] = {}
    for key, needle in SUMMARY_KEYS:
        match = None
        for _, row in rows:
            label = " ".join(w["text"].strip() for w in row if w["x1"] < unit_x - 8)
            if needle in label:
                has_value = any((w["x0"] + w["x1"]) / 2 > unit_x + 12 for w in row)
                if has_value:
                    match = (label, row)
                    break
        if match is None:
            raise BoqParseError(f"p.{page_no} 항목 미검출: {key}/{needle}")
        label, row = match
        values: Dict[str, Optional[float]] = {}
        for w in row:
            cx = (w["x0"] + w["x1"]) / 2
            if cx <= unit_x + 12:
                continue
            col = min(columns, key=lambda c: abs(header_x[c] - cx))
            if abs(header_x[col] - cx) < 26:
                values[col] = to_num(w["text"])
        unit = next((w["text"].strip() for w in row if abs((w["x0"] + w["x1"]) / 2 - unit_x) <= 8), None)
        out[key] = {"label": label, "unit": unit, "values": values}
    return out


def parse_rebar_table(pdf: Any, page_no: int, columns: List[Tuple[str, float, float]]) -> Dict[str, Any]:
    """NET/ADD 2단 구조의 철근 집계표. columns=(이름, NET x, ADD x)."""
    words = pdf.pages[page_no - 1].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    labels = [(w["top"], w["text"].strip()) for w in words if re.fullmatch(r"S\d+|TOTAL", w["text"].strip())]
    out: Dict[str, Any] = {}
    for y, dia in labels:
        rec: Dict[str, Any] = {"net": {}, "gross": {}, "rate_note": None}
        for w in words:
            if not -13 <= w["top"] - y <= 14:
                continue
            num = to_num(w["text"])
            if num is None:
                if w["text"].strip().startswith("ADD"):
                    rec["rate_note"] = w["text"].strip()
                continue
            for name, net_x, add_x in columns:
                if abs(w["x0"] - net_x) < 8:
                    rec["net"][name] = num
                if abs(w["x0"] - add_x) < 8:
                    rec["gross"][name] = num
        out[dia] = rec
    return out


TITLES = {"total": ("총괄집계표",), "rebar_all": ("통로암거철근수량집계표",), "blocks": ("통로암거일반수량집계표",), "rebar_body": ("본체철근수량집계표",),
          "wing": ("날개벽집계표",), "rebar_wing": ("날개벽철근수량집계표",)}
TITLE_NAMES = {"total": "일반수량 총괄집계표", "rebar_all": "철근수량 집계표", "blocks": "일반수량 집계표", "rebar_body": "본체 철근수량 집계표", "wing": "일체식 날개벽 집계표", "rebar_wing": "일체식 날개벽 철근수량 집계표"}


def locate_pages(pdf: Any) -> Dict[str, Any]:
    """표와 산출근거의 위치를 쪽 번호가 아니라 제목으로 찾는다. 못 찾으면 무엇이 없는지 알려 준다."""
    tops: List[str] = []
    for page in pdf.pages:
        tops.append("".join((page.extract_text() or "").split("\n")[:2]).replace(" ", ""))
    where: Dict[str, Any] = {}
    for key, needles in TITLES.items():
        found = [i + 1 for i, top in enumerate(tops) if any(n in top for n in needles)]
        if found:
            where[key] = found[0]
    absent = [TITLE_NAMES[k] for k in TITLES if k not in where]
    if absent:
        raise BoqParseError("통로암거 수량산출서 양식이 아닙니다. 찾지 못한 표: " + ", ".join(absent))
    # 산출근거: '※단면도'(본체)와 '※정면도'(날개벽) 표지 다음 쪽부터 다음 표지 또는 다음 표까지가 한 묶음이다.
    full = [(page.extract_text() or "").replace(" ", "") for page in pdf.pages]
    table_pages = set(where[k] for k in TITLES)
    marks = [(i + 1, "wing" if "※정면도" in t[:80] else "body") for i, t in enumerate(full) if "※단면도" in t[:80] or "※정면도" in t[:80]]
    groups: Dict[str, List[List[int]]] = {"body": [], "wing": []}
    for n, (page_no, kind) in enumerate(marks):
        stop = marks[n + 1][0] if n + 1 < len(marks) else len(full) + 1
        stops = [p for p in table_pages if page_no < p < stop]
        stop = min(stops) if stops else stop
        groups[kind].append(list(range(page_no + 1, stop)))
    if len(groups["body"]) != 3 or len(groups["wing"]) != 4:
        raise BoqParseError(f"산출근거 묶음을 해석하지 못했습니다 (본체 {len(groups['body'])}개, 날개벽 {len(groups['wing'])}개. 본체 3개, 날개벽 4개 필요)")
    where["calc"] = {"B1": groups["body"][0], "B2": groups["body"][1], "B3": groups["body"][2],
                     "WW-시점좌": groups["wing"][0], "WW-시점우": groups["wing"][1], "WW-종점좌": groups["wing"][2], "WW-종점우": groups["wing"][3]}
    return where


class BoQParserAgent:
    def __init__(self, docs_dir: str = "docs", output_path: str = "data/boq_extracted.json", pdf_path: str = "") -> None:
        self.docs_dir = docs_dir
        self.pdf_path = pdf_path
        self.output_path = output_path

    def run(self) -> Dict[str, Any]:
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        pdfs = [self.pdf_path] if self.pdf_path else glob.glob(os.path.join(self.docs_dir, "*.pdf"))
        if len(pdfs) != 1:
            raise BoqParseError(f"PDF 1종 필요, 실제 {len(pdfs)}종")
        with pdfplumber.open(pdfs[0]) as pdf:
            page_count = len(pdf.pages)
            where = locate_pages(pdf)
            summary_total = parse_summary(pdf, where["total"], ["암거1", "계"])
            summary_block = parse_summary(pdf, where["blocks"], ["Block1", "Block2", "Block3", "일체식날개벽", "계"])
            wing_table = parse_wing_table(pdf, where["wing"])
            rebar_all = parse_rebar_table(pdf, where["rebar_all"], [("본체", 83, 119), ("날개벽", 156, 191), ("계", 436, 471)])
            rebar_body = parse_rebar_table(pdf, where["rebar_body"], rebar_body_columns(pdf, where["rebar_body"]))
            rebar_wing = parse_rebar_table(pdf, where["rebar_wing"], [("시점좌", 86, 121), ("시점우", 156, 192), ("종점좌", 227, 262), ("종점우", 297, 333), ("계", 436, 472)])
            scopes = {name: parse_calc_pages(pdf, pages) for name, pages in where["calc"].items()}
        result = {
            "source_file": os.path.basename(pdfs[0]), "page_count": page_count, "pages": {k: v for k, v in where.items() if k != "calc"},
            "summary_p2": summary_total, "summary_p4": summary_block, "wing_p21": wing_table,
            "rebar_p3": rebar_all, "rebar_p5": rebar_body, "rebar_p22": rebar_wing, "calc": scopes,
        }
        with open(self.output_path, "w", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=1)
        return result


def rebar_body_columns(pdf: Any, page_no: int) -> List[Tuple[str, float, float]]:
    """본체 철근표 열 좌표를 'S16' 행 값에서 직접 읽는다."""
    words = pdf.pages[page_no - 1].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    y = next(w["top"] for w in words if w["text"].strip() == "S16")
    net = sorted(w["x0"] for w in words if -13 <= w["top"] - y < 0 and to_num(w["text"]) is not None)
    add = sorted(w["x0"] for w in words if 0 <= w["top"] - y <= 14 and to_num(w["text"]) is not None)
    if len(net) != 4 or len(add) != 4:
        raise BoqParseError(f"p.5 열 해석 실패: {net} {add}")
    names = ["B1", "B2", "B3", "계"]
    return [(names[i], net[i], add[i]) for i in range(4)]


def parse_wing_table(pdf: Any, page_no: int) -> Dict[str, Any]:
    """p.21 일체식 날개벽 집계표."""
    words = pdf.pages[page_no - 1].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    rows = rows_of(words, tol=3.0)
    columns = ["시점좌", "시점우", "종점좌", "종점우", "계"]
    target = {"concrete": "25-30-15", "form_normal": "보통", "shoring": "시스템동바리", "scaffold": "시스템비계",
              "spacer_wall": "벽체용", "waterproof": "2회", "pvc": "φ", "fabric": "300 x 300mm", "H16_25": "H16~25"}
    out: Dict[str, Any] = {}
    for key, needle in target.items():
        for _, row in rows:
            label = " ".join(w["text"].strip() for w in row if to_num(w["text"]) is None)
            nums = [to_num(w["text"]) for w in row if to_num(w["text"]) is not None]
            if needle in label and len(nums) >= 5:
                out[key] = {"label": label, "values": dict(zip(columns, nums[-5:]))}
                break
        if key not in out:
            raise BoqParseError(f"p.21 항목 미검출: {key}")
    return out


if __name__ == "__main__":
    data = BoQParserAgent().run()
    print("pages", data["page_count"])
    print({k: (v["label"], v["unit"], v["values"].get("계")) for k, v in data["summary_p2"].items()})
    print({k: v["values"] for k, v in list(data["summary_p4"].items())[:3]})
    print(data["summary_p4"]["pvc"], data["summary_p4"]["fabric"])
    print(data["rebar_p3"]["S22"], data["rebar_p3"]["TOTAL"])
    print(data["rebar_p5"]["S16"], data["rebar_p22"]["S22"])
    print(data["wing_p21"]["pvc"], data["wing_p21"]["fabric"])
    total = bad = err = 0
    for scope, items in data["calc"].items():
        print("==", scope, [(i["no"], i["name"], len(i["lines"]), [s["value"] for s in i["subtotals"]][-2:]) for i in items])
        for item in items:
            for line in item["lines"]:
                total += 1
                if "eval_error" in line:
                    err += 1
                    print("  ERR", item["name"], line)
                elif "calc" in line and line["printed"] is not None and abs(line["calc"] - line["printed"]) > 0.0015:
                    bad += 1
                    print("  DIFF", item["name"], line["formula"], line["calc"], line["printed"], "p", line["page"])
                elif "calc" not in line and line["printed_raw"] not in ("-", ""):
                    print("  NOCALC", item["name"], line["formula"], line["printed_raw"], line["sub"])
    print("lines", total, "diff", bad, "err", err)
