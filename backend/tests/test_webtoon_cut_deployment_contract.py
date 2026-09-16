from __future__ import annotations

from pathlib import Path


def test_webtoon_cut_docker_image_installs_korean_poppler_cmap_data():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    deployment_guide = Path("docs/ecr-webtoon-cut-deployment-guide.md").read_text(encoding="utf-8")

    assert "poppler-utils" in dockerfile
    assert "poppler-data" in dockerfile
    assert "poppler-data" in deployment_guide
