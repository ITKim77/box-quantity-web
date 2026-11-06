"""웹 화면과 계산 코드를 site/ 폴더에 모은다. GitHub Pages가 이 폴더를 그대로 제공한다."""
from __future__ import annotations

import os
import shutil
import zipfile

SKIP = {"workflow_orchestrator.py", "qa_reporter_agent.py", "dxf_alternative_generator.py"}


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
    print("site/", sorted(os.listdir("site")), os.path.getsize("site/app.zip"), "bytes")


if __name__ == "__main__":
    main()
