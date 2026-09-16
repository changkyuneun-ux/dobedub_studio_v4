from __future__ import annotations

import glob
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CutResult:
    path: Path
    cut_index: int
    width: int
    height: int
    flags: list[str]


@dataclass(frozen=True)
class RenderedUnitResult:
    page_number: int | None
    cuts: list[CutResult]
    debug_overlay_path: Path | None
    mode: str
    flags: list[str]


def page_count(pdf_path: Path) -> int:
    out = subprocess.check_output(["pdfinfo", str(pdf_path)], text=True)
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise RuntimeError(f"pdfinfo failed: {pdf_path}")


def process_pdf_page(
    pdf_path: Path,
    *,
    page_number: int,
    output_dir: Path,
    dpi: int = 300,
    split_mode: str = "print",
) -> RenderedUnitResult:
    tmpdir = Path(tempfile.mkdtemp(prefix="webtoon_pdf_page_"))
    try:
        rendered = _render_page(pdf_path, page_number, dpi=dpi, tmpdir=tmpdir)
        return process_image_file(rendered, output_dir=output_dir, page_number=page_number, split_mode=split_mode)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def process_image_file(
    image_path: Path,
    *,
    output_dir: Path,
    page_number: int | None = None,
    split_mode: str = "print",
) -> RenderedUnitResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    panel_tmp = Path(tempfile.mkdtemp(prefix="webtoon_panels_"))
    try:
        if split_mode == "dark-webtoon":
            from backend.app.services.webtoon_panel_engine.dark_bg_split import split_panels

            mode = "dark_bg"
        else:
            from backend.app.services.webtoon_panel_engine.batch_split import split_panels

            mode = "grid"

        saved = [Path(path) for path in split_panels(str(image_path), str(panel_tmp), debug=True)]
        flags: list[str] = []
        cuts: list[CutResult] = []
        debug_overlay = panel_tmp / "_debug_overlay.png"
        if not saved:
            flags.append("fullpage")
            target = output_dir / "fullpage-01.png"
            _fullpage_crop(image_path, target)
            width, height = _image_size(target)
            cuts.append(CutResult(path=target, cut_index=1, width=width, height=height, flags=["fullpage"]))
            return RenderedUnitResult(page_number=page_number, cuts=cuts, debug_overlay_path=None, mode="fullpage", flags=flags)

        page_width, page_height = _image_size(image_path)
        for index, source in enumerate(saved, start=1):
            target = output_dir / f"panel-{index:02d}.png"
            shutil.move(str(source), target)
            width, height = _image_size(target)
            cut_flags: list[str] = []
            if page_width and page_height and min(width / page_width, height / page_height) < 0.08:
                cut_flags.append("thin")
            if width and height and max(width / height, height / width) > 4.0:
                cut_flags.append("thin")
            cuts.append(CutResult(path=target, cut_index=index, width=width, height=height, flags=cut_flags))
        if len(cuts) >= 9:
            flags.append("many")
        debug_target = None
        if debug_overlay.exists():
            debug_target = output_dir / "_debug_overlay.png"
            shutil.copyfile(debug_overlay, debug_target)
        return RenderedUnitResult(
            page_number=page_number,
            cuts=cuts,
            debug_overlay_path=debug_target,
            mode=mode,
            flags=flags,
        )
    finally:
        shutil.rmtree(panel_tmp, ignore_errors=True)


def _render_page(pdf_path: Path, page_number: int, *, dpi: int, tmpdir: Path) -> Path:
    prefix = tmpdir / "page"
    subprocess.check_call(
        ["pdftoppm", "-r", str(dpi), "-png", "-f", str(page_number), "-l", str(page_number), str(pdf_path), str(prefix)]
    )
    candidates = glob.glob(str(prefix) + "*.png")
    if not candidates:
        raise RuntimeError(f"PDF page render failed: {pdf_path} page {page_number}")
    return Path(candidates[0])


def _fullpage_crop(image_path: Path, destination: Path, *, margin: float = 0.03) -> None:
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"image read failed: {image_path}")
    height, width = img.shape[:2]
    crop = img[int(height * margin): int(height * (1 - margin)), int(width * margin): int(width * (1 - margin))]
    cv2.imwrite(str(destination), crop)


def _image_size(image_path: Path) -> tuple[int, int]:
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        return 0, 0
    height, width = img.shape[:2]
    return width, height
