"""Extra installed-package contract check; uses synthetic bytes, never a provider.

Run after verify_release.py. HTTP admission/download/restart uses its launcher
fixture; a package interpreter writes synthetic content and corrects metadata.
Real HTTP upload transport and decoded clips are covered by browser acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from verify_release import isolated_env, run_python, served, unpack


def verify(package):
    with tempfile.TemporaryDirectory(prefix="kdog-mp4-package-") as temporary:
        root = Path(temporary)
        app = root / "통합 MP4 설치"
        manifest = unpack(package, app)
        env = isolated_env(root, root / "data")
        if manifest["variant"] == "online":
            env["PATH"] = os.environ["PATH"]
            subprocess.run([str(app / "Install.cmd"), "-SkipAccounts"], cwd=app, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=600)
            python, working = app / "backend/.venv/Scripts/python.exe", app / "backend"
            env.pop("PYTHONHOME", None)
            env.pop("PYTHONPATH", None)
        else:
            python, working = app / "runtime/python/python.exe", app
        run_python(python, working, env, "-c", "from pathlib import Path; import os\n"
            "from app.storage import Store\nfrom app.auth import create_user\nfrom app.input_models import UserCreate\n"
            "with Store(Path(os.environ['KDOG_DATA_DIR'])).connect(write=True) as db:\n"
            " create_user(db,UserCreate(username='pilot',role='operator',password='Synthetic-install-only-42'))\n")
        expected = json.dumps("synthetic external MP4").encode()
        case_id = upload_id = None
        for attempt in range(2):
            with served([str(python), "-X", "utf8", "-m", "app.launcher"], working, env, python=python) as clients:
                request = clients()
                request("/api/auth/login", {"username": "pilot", "password": "Synthetic-install-only-42"})
                if attempt == 0:
                    case = request("/api/cases", {"event_id": "MP03-INSTALL", "participant_id": "SYNTHETIC", "dog_name": "설치 합성견"})
                    case_id = case["case_id"]
                    receipt = request("/api/uploads", {"request_id": "prepared-install", "filename": "synthetic.mp4",
                        "expected_size": len(expected), "source_kind": "external_360_mp4", "external_processing": {}})
                    upload_id = receipt["upload_id"]
                    run_python(python, working, env, "-c", "import asyncio,os,json\nfrom pathlib import Path\n"
                        "from app.storage import Store\nfrom app import uploads\n"
                        "from app.domain.media_v4 import UploadLinkV4,ExternalProcessingEditV4,ExternalProcessingV4\n"
                        "store=Store(Path(os.environ['KDOG_DATA_DIR']))\n"
                        "async def chunks():\n yield json.dumps('synthetic external MP4').encode()\n"
                        f"asyncio.run(uploads.receive(store,{upload_id!r},'prepared-install',chunks(),'pilot'))\n"
                        f"linked=uploads.link_receipt(store,{upload_id!r},UploadLinkV4(case_id={case_id!r},"
                        f"session_id={case['selected_session_id']!r},expected_revision={case['input_revision']},camera_id='EXT360'),'pilot')\n"
                        f"uploads.update_external_processing(store,{case_id!r},linked.video_id,ExternalProcessingEditV4("
                        f"session_id={case['selected_session_id']!r},expected_revision=linked.linked_revision,"
                        "external_processing=ExternalProcessingV4(projection='flat',timeline='preserved')),'pilot')\n")
                current = request("/api/cases/" + case_id)
                video = current["manifest"]["sessions"][0]["videos"][0]
                receipt = request("/api/uploads/" + upload_id)
                assert len(request("/api/uploads")) == 1
                assert (video["source_kind"], video["camera_id"], video["parents"], video["source_original_number"]) == ("external_360_mp4", "EXT360", [], None)
                assert video["external_processing"]["projection"] == "flat" and video["external_processing"]["timeline"] == "preserved"
                assert receipt["external_processing"]["projection"] == "unknown" and receipt["analysis_ready"] is False
                assert video["sha256"] == receipt["sha256"] == hashlib.sha256(expected).hexdigest()
                assert request("/api/uploads/" + upload_id + "/content") == "synthetic external MP4"
        return {"variant": manifest["variant"], "commit": manifest["commit"], "prepared_mp4_admission_restart_download": "passed",
                "metadata_revision_and_original_declaration": "passed", "synthetic_content_via_package_interpreter": True, "provider_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    print(json.dumps(verify(parser.parse_args().package), ensure_ascii=False))
