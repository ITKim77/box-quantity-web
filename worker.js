// 브라우저 안에서 Python을 돌린다. 도면과 산출서는 이 탭 밖으로 나가지 않는다. 내려받는 것은 프로그램뿐이다.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js");

const WHEELS = ["ezdxf==1.4.1", "openpyxl==3.1.5", "et_xmlfile==2.0.0", "pdfminer.six==20250506", "pdfplumber==0.11.7", "typing_extensions"];
let ready = null;

function say(type, text) { postMessage({ type, text }); }

async function boot() {
  say("progress", "프로그램을 내려받는 중입니다 (처음 한 번은 1~2분 걸립니다)");
  const py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/" });
  await py.loadPackage(["micropip", "numpy", "pillow", "cryptography", "pyparsing", "fonttools", "charset-normalizer"]);
  py.globals.set("WHEELS", py.toPy(WHEELS));
  await py.runPythonAsync(`
import micropip, sys, types
await micropip.install(list(WHEELS), deps=False)
sys.modules["pypdfium2"] = types.ModuleType("pypdfium2")  # PDF 그림 변환에만 쓰인다. 글자 읽기에는 필요 없다.
`);
  const zip = await (await fetch(new URL("app.zip?v=da824de7295c", self.location.href))).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.runPython(`import sys; sys.path.insert(0, "/app")`);
  return py;
}

function clean(py, path) {
  py.globals.set("WORK", path);
  py.runPython(`
import os, shutil
os.chdir("/")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK + "/docs")
os.chdir(WORK)
`);
}

async function runAll(dxfs, pdf, py) {
  clean(py, "/work");
  dxfs.forEach((f) => py.FS.writeFile(`/work/docs/${f.name}`, new Uint8Array(f.data)));
  if (pdf) py.FS.writeFile("/work/original.pdf", new Uint8Array(pdf.data));
  say("progress", "도면을 읽고 수량을 계산하는 중입니다");
  py.globals.set("PDF", pdf ? "/work/original.pdf" : null);
  const text = await py.runPythonAsync(`
import json
from src.service import run
json.dumps(run("docs", PDF), ensure_ascii=False)
`);
  const result = JSON.parse(text);
  if (result.status === "success") result.htmlText = py.FS.readFile(`/work/${result.html}`, { encoding: "utf8" });
  postMessage({ type: "done", result });
}

async function exportFiles(inputs, bars, py) {
  py.globals.set("EDITS", JSON.stringify({ inputs, bars }));
  const text = await py.runPythonAsync(`
import json
from src.service import export
_edits = json.loads(EDITS)
json.dumps(export(_edits["inputs"], _edits["bars"]), ensure_ascii=False)
`);
  const paths = JSON.parse(text);
  postMessage({ type: "exported", files: { html: py.FS.readFile(`/work/${paths.html}`, { encoding: "utf8" }), xlsx: py.FS.readFile(`/work/${paths.xlsx}`) } });
}

self.onmessage = async (event) => {
  const { cmd, dxfs, pdf, inputs, bars } = event.data;
  try {
    ready = ready || boot();
    const py = await ready;
    if (cmd === "export") await exportFiles(inputs, bars, py);
    else await runAll(dxfs, pdf, py);
  } catch (error) {
    postMessage({ type: "crash", text: String(error && error.message ? error.message : error).slice(-1500) });
  }
};
