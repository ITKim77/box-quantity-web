"""웹 화면과 계산 코드를 site/ 폴더에 모은다. GitHub Pages가 이 폴더를 그대로 제공한다."""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile

SKIP = {"workflow_orchestrator.py", "qa_reporter_agent.py", "dxf_alternative_generator.py"}


def stamp(path: str, old: str, new: str) -> None:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.count(old) != 1:
        raise RuntimeError(f"{path}에서 버전을 붙일 곳을 찾지 못했습니다: {old}")
    with open(path, "w", encoding="utf-8") as out:
        out.write(text.replace(old, new))


def main() -> None:
    shutil.rmtree("site", ignore_errors=True)
    shutil.copytree("web", "site")
    open("site/.nojekyll", "w").close()
    with zipfile.ZipFile("site/app.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for folder, _, files in os.walk("src"):
            for name in files:
                if name.endswith(".py") and name not in SKIP:
                    path = os.path.join(folder, name)
                    bundle.write(path, path.replace(os.sep, "/"))
    # GitHub Pages 캐시 때문에 배포 직후 이전 코드가 돌지 않도록 파일 주소에 내용 해시를 붙인다
    with open("site/app.zip", "rb") as bundle_file, open("site/worker.js", "rb") as worker_file:
        version = hashlib.sha256(bundle_file.read() + worker_file.read()).hexdigest()[:12]
    stamp("site/worker.js", 'new URL("app.zip"', f'new URL("app.zip?v={version}"')
    stamp("site/index.html", "new Worker('worker.js')", f"new Worker('worker.js?v={version}')")
    print("site/", sorted(os.listdir("site")), os.path.getsize("site/app.zip"), "bytes")


if __name__ == "__main__":
    main()
