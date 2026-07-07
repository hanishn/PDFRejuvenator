from __future__ import annotations

import hashlib
import html
import importlib
import json
import platform
import re
import shutil
import subprocess
import sys
import zipfile
import csv
import copy
import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageStat


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def dependency_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pymupdf": fitz.version[0],
        "pillow": Image.__version__,
    }
    for name in ["pytesseract", "docx", "reportlab", "pypdf", "rapidocr_onnxruntime", "onnxruntime", "cv2"]:
        try:
            mod = importlib.import_module(name)
            versions[name] = getattr(mod, "__version__", "installed-version-unknown")
        except Exception as exc:
            versions[name] = f"unavailable: {type(exc).__name__}"
    try:
        proc = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        first = proc.stdout.splitlines()[0] if proc.stdout else proc.stderr.splitlines()[0]
        versions["tesseract_cli"] = first
    except Exception as exc:
        versions["tesseract_cli"] = f"unavailable: {type(exc).__name__}"
    return versions


@dataclass(frozen=True)
class Region:
    region_id: str
    bbox_points: tuple[float, float, float, float]
    text: str
    block_index: int
    lines: list[list[dict[str, Any]]]
    classification: str
    classification_reason: str
    alignment: str


def load_pdf(config: dict[str, Any]) -> tuple[Path, fitz.Document, int]:
    source_pdf = Path(config["source_pdf"])
    if not source_pdf.exists():
        raise FileNotFoundError(f"source_pdf not found: {source_pdf}")
    doc = fitz.open(source_pdf)
    page_number = int(config["selected_page_1based"])
    if page_number < 1 or page_number > len(doc):
        raise ValueError(f"selected_page_1based {page_number} outside 1..{len(doc)}")
    return source_pdf, doc, page_number


def clean_output(output_root: Path) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def render_page(page: fitz.Page, page_id: str, dpi: int, render_dir: Path) -> dict[str, Any]:
    render_dir.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    png_path = render_dir / f"{page_id}_page_render.png"
    tiff_path = render_dir / f"{page_id}_page_render.tiff"
    pix.save(str(png_path))
    with Image.open(png_path) as img:
        rgb = img.convert("RGB")
        rgb.save(tiff_path, compression="tiff_lzw")
        width, height = rgb.size
    return {
        "page_png": png_path,
        "page_tiff": tiff_path,
        "width_px": width,
        "height_px": height,
        "dpi": dpi,
    }


def _hidden_editable_text_layer(editable_text: str) -> ET.Element:
    svg_ns = "{http://www.w3.org/2000/svg}"
    inkscape_ns = "{http://www.inkscape.org/namespaces/inkscape}"
    editable_root = ET.fromstring(editable_text.encode("utf-8"))
    hidden_layer = ET.Element(
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "editable_text_overlay_hidden",
            "id": "editable_text_overlay_hidden",
            "style": "display:none",
        },
    )
    for element in editable_root.iter():
        if element.tag == f"{svg_ns}text":
            hidden_layer.append(copy.deepcopy(element))
    return hidden_layer


def _editable_text_layer(editable_text: str, *, hidden: bool) -> ET.Element:
    svg_ns = "{http://www.w3.org/2000/svg}"
    inkscape_ns = "{http://www.inkscape.org/namespaces/inkscape}"
    editable_root = ET.fromstring(editable_text.encode("utf-8"))
    attrs = {
        f"{inkscape_ns}groupmode": "layer",
        f"{inkscape_ns}label": "editable_text_overlay_hidden" if hidden else "visible_pdf_font_editable_text",
        "id": "editable_text_overlay_hidden" if hidden else "visible_pdf_font_editable_text",
    }
    if hidden:
        attrs["style"] = "display:none"
    layer = ET.Element(f"{svg_ns}g", attrs)
    for element in editable_root.iter():
        if element.tag == f"{svg_ns}text":
            layer.append(copy.deepcopy(element))
    return layer


def _editable_text_elements(editable_text: str) -> list[ET.Element]:
    svg_ns = "{http://www.w3.org/2000/svg}"
    editable_root = ET.fromstring(editable_text.encode("utf-8"))
    return [copy.deepcopy(element) for element in editable_root.iter() if element.tag == f"{svg_ns}text"]


def _strip_path_text_uses(element: ET.Element, svg_ns: str) -> int:
    removed = 0
    for child in list(element):
        if child.tag == f"{svg_ns}use" and "data-text" in child.attrib:
            element.remove(child)
            removed += 1
            continue
        removed += _strip_path_text_uses(child, svg_ns)
    return removed


def _strip_font_defs(root: ET.Element, svg_ns: str) -> int:
    removed = 0
    for defs in root.findall(f".//{svg_ns}defs"):
        for child in list(defs):
            if child.attrib.get("id", "").startswith("font_"):
                defs.remove(child)
                removed += 1
    return removed


def export_svg_artifacts(page: fitz.Page, page_id: str, svg_dir: Path, render_record: dict[str, Any]) -> dict[str, Any]:
    svg_dir.mkdir(parents=True, exist_ok=True)
    editable_svg = svg_dir / f"{page_id}_editable_text.svg"
    path_svg = svg_dir / f"{page_id}_path_fidelity.svg"
    layered_svg = svg_dir / f"{page_id}_inkscape_layered.svg"
    fidelity_svg = svg_dir / f"{page_id}_inkscape_fidelity.svg"
    segmented_svg = svg_dir / f"{page_id}_path_art_plus_editable_text.svg"
    single_layer_svg = svg_dir / f"{page_id}_single_editable_layer.svg"

    editable_text = page.get_svg_image(text_as_path=0)
    path_text = page.get_svg_image(text_as_path=1)
    write_text(editable_svg, editable_text)
    write_text(path_svg, path_text)

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
    svg_ns = "{http://www.w3.org/2000/svg}"
    inkscape_ns = "{http://www.inkscape.org/namespaces/inkscape}"
    xlink_ns = "{http://www.w3.org/1999/xlink}"
    visible_root = ET.fromstring(path_text.encode("utf-8"))
    visible_layer = ET.Element(
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "visible_path_fidelity",
            "id": "visible_path_fidelity",
        },
    )
    for child in list(visible_root):
        visible_root.remove(child)
        visible_layer.append(child)
    hidden_layer = _editable_text_layer(editable_text, hidden=True)
    visible_root.append(visible_layer)
    visible_root.append(hidden_layer)
    ET.ElementTree(visible_root).write(layered_svg, encoding="utf-8", xml_declaration=True)

    segmented_root = ET.fromstring(path_text.encode("utf-8"))
    removed_text_uses = _strip_path_text_uses(segmented_root, svg_ns)
    removed_font_defs = _strip_font_defs(segmented_root, svg_ns)
    path_art_layer = ET.Element(
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "path_art_without_text_uses",
            "id": "path_art_without_text_uses",
        },
    )
    for child in list(segmented_root):
        segmented_root.remove(child)
        path_art_layer.append(child)
    segmented_root.append(path_art_layer)
    segmented_root.append(_editable_text_layer(editable_text, hidden=False))
    ET.ElementTree(segmented_root).write(segmented_svg, encoding="utf-8", xml_declaration=True)

    single_root = ET.fromstring(path_text.encode("utf-8"))
    single_removed_text_uses = _strip_path_text_uses(single_root, svg_ns)
    single_removed_font_defs = _strip_font_defs(single_root, svg_ns)
    single_layer = ET.Element(
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "single_editable_layer",
            "id": "single_editable_layer",
            "data-pdfrejuvenator-layer-role": "path_art_and_pdf_font_editable_text",
        },
    )
    for child in list(single_root):
        single_root.remove(child)
        single_layer.append(child)
    for text_element in _editable_text_elements(editable_text):
        single_layer.append(text_element)
    single_root.append(single_layer)
    ET.ElementTree(single_root).write(single_layer_svg, encoding="utf-8", xml_declaration=True)

    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    fidelity_root = ET.Element(
        f"{svg_ns}svg",
        {
            "version": "1.1",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            "viewBox": f"0 0 {page_width:g} {page_height:g}",
        },
    )
    visible_image_layer = ET.SubElement(
        fidelity_root,
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "visible_source_render_fidelity",
            "id": "visible_source_render_fidelity",
        },
    )
    image_data = base64.b64encode(Path(render_record["page_png"]).read_bytes()).decode("ascii")
    ET.SubElement(
        visible_image_layer,
        f"{svg_ns}image",
        {
            "id": "source_page_render",
            "x": "0",
            "y": "0",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            f"{xlink_ns}href": f"data:image/png;base64,{image_data}",
        },
    )
    fidelity_root.append(_editable_text_layer(editable_text, hidden=True))
    ET.ElementTree(fidelity_root).write(fidelity_svg, encoding="utf-8", xml_declaration=True)

    return {
        "editable_text_svg": editable_svg,
        "path_fidelity_svg": path_svg,
        "inkscape_layered_svg": layered_svg,
        "inkscape_fidelity_svg": fidelity_svg,
        "path_art_plus_editable_text_svg": segmented_svg,
        "single_editable_layer_svg": single_layer_svg,
        "single_editable_layer_id": "single_editable_layer",
        "editable_text_count": len(hidden_layer),
        "path_text_uses_removed": removed_text_uses,
        "path_font_defs_removed": removed_font_defs,
        "single_layer_text_uses_removed": single_removed_text_uses,
        "single_layer_font_defs_removed": single_removed_font_defs,
    }


def classify_embedded_image(image_path: Path, bbox_points: list[float] | None, page_rect: fitz.Rect) -> dict[str, Any]:
    page_area = max(1.0, float(page_rect.width * page_rect.height))
    bbox_area_ratio = 0.0
    if bbox_points:
        bbox_area = max(0.0, float(bbox_points[2] - bbox_points[0])) * max(0.0, float(bbox_points[3] - bbox_points[1]))
        bbox_area_ratio = bbox_area / page_area
    with Image.open(image_path) as pil:
        rgba = pil.convert("RGBA")
        rgb = rgba.convert("RGB")
        rgb_stat = ImageStat.Stat(rgb)
        alpha_stat = ImageStat.Stat(rgba.getchannel("A"))
        mean_rgb = sum(rgb_stat.mean) / 3.0
        contrast = sum(rgb_stat.stddev) / 3.0
        alpha_mean = float(alpha_stat.mean[0])
    if bbox_area_ratio >= 0.85 and mean_rgb >= 215 and contrast <= 35:
        classification = "page_background"
        review_role = "paper_texture_or_background"
    elif mean_rgb >= 245 and contrast <= 8 and alpha_mean >= 250:
        classification = "near_blank_image"
        review_role = "low_information_resource"
    else:
        classification = "content_image"
        review_role = "visible_page_content"
    return {
        "classification": classification,
        "review_role": review_role,
        "bbox_area_ratio": round(bbox_area_ratio, 4),
        "mean_rgb": round(mean_rgb, 2),
        "contrast": round(contrast, 2),
        "alpha_mean": round(alpha_mean, 2),
    }


def extract_embedded_images(doc: fitz.Document, page: fitz.Page, page_id: str, image_dir: Path) -> list[dict[str, Any]]:
    image_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for order, img in enumerate(sorted(page.get_images(full=True), key=lambda item: (item[0], item[1]))):
        xref = int(img[0])
        if xref in seen:
            continue
        seen.add(xref)
        extracted = doc.extract_image(xref)
        ext = extracted.get("ext", "bin")
        data = extracted["image"]
        image_id = f"{page_id}_img_{order + 1:03d}_xref_{xref}"
        out_path = image_dir / f"{image_id}.{ext}"
        with out_path.open("wb") as handle:
            handle.write(data)
        try:
            with Image.open(out_path) as pil:
                width, height = pil.size
                mode = pil.mode
        except Exception:
            width = height = None
            mode = "unreadable"
        rects = page.get_image_rects(xref)
        bbox_points = None
        if rects:
            bbox_points = [round(float(v), 3) for v in rects[0]]
        appearance = classify_embedded_image(out_path, bbox_points, page.rect)
        records.append({
            "image_id": image_id,
            "xref": xref,
            "file": out_path,
            "width_px": width,
            "height_px": height,
            "mode": mode,
            "bbox_points": bbox_points,
            **appearance,
        })
    return records


def text_from_block(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for line in block.get("lines", []):
        spans = [span.get("text", "") for span in line.get("spans", [])]
        line_text = "".join(spans).strip()
        if line_text:
            parts.append(line_text)
    return "\n".join(parts).strip()


def color_to_hex(color: int | None) -> str:
    if color is None:
        return "000000"
    return f"{int(color) & 0xFFFFFF:06X}"


def span_is_bold(span: dict[str, Any]) -> bool:
    font = span.get("font", "").lower()
    flags = int(span.get("flags", 0))
    return "bold" in font or bool(flags & 16)


def span_is_italic(span: dict[str, Any]) -> bool:
    font = span.get("font", "").lower()
    flags = int(span.get("flags", 0))
    return "italic" in font or "oblique" in font or bool(flags & 2)


def span_is_underlined(span: dict[str, Any]) -> bool:
    font = span.get("font", "").lower()
    return "underline" in font


def normalized_span(span: dict[str, Any]) -> dict[str, Any]:
    record = {
        "text": span.get("text", ""),
        "font": span.get("font", "Arial"),
        "size_pt": round(float(span.get("size", 11.0)), 2),
        "bold": span_is_bold(span),
        "italic": span_is_italic(span),
        "underline": span_is_underlined(span),
        "color": color_to_hex(span.get("color")),
        "flags": int(span.get("flags", 0)),
    }
    if "bbox" in span:
        record["bbox_points"] = [round(float(v), 3) for v in span["bbox"]]
    return record


def lines_from_block(block: dict[str, Any]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for line in block.get("lines", []):
        spans = []
        for span in line.get("spans", []):
            text = span.get("text", "")
            if text:
                spans.append(normalized_span(span))
        if spans:
            lines.append(spans)
    return lines


def classify_text_region(lines: list[list[dict[str, Any]]]) -> tuple[str, str]:
    fonts = {span["font"].lower() for line in lines for span in line}
    text = "".join(span["text"] for line in lines for span in line).strip()
    stylized_tokens = ("symbol", "wingdings", "dingbat", "zapf")
    if text and fonts and all(any(token in font for token in stylized_tokens) for font in fonts):
        return "image_only_stylized_text", "all extracted spans use symbol/dingbat-style fonts"
    return "normal_editable_text", "extractable text spans use normal fonts; DOCX must contain editable text runs"


def estimate_alignment(bbox: tuple[float, float, float, float], page_width: float) -> str:
    left, _top, right, _bottom = bbox
    width = right - left
    center = left + width / 2
    if abs(center - page_width / 2) < page_width * 0.08:
        return "center"
    return "left"


def valid_region_bbox(bbox: tuple[float, float, float, float], page_rect: fitz.Rect, min_points: float = 0.01) -> bool:
    rect = fitz.Rect(bbox) & page_rect
    return rect.width > min_points and rect.height > min_points


def detect_text_regions(page: fitz.Page, page_id: str, max_regions: int, min_chars: int, strategy: str = "block") -> list[Region]:
    blocks = page.get_text("dict").get("blocks", [])
    regions: list[Region] = []
    for block_index, block in enumerate(blocks):
        if block.get("type") != 0:
            continue
        if strategy == "line":
            for line_index, line in enumerate(block.get("lines", [])):
                line_block = {"lines": [line], "bbox": line.get("bbox", block.get("bbox"))}
                text = text_from_block(line_block)
                if len(text.strip()) < min_chars:
                    continue
                bbox = tuple(float(x) for x in line_block["bbox"])
                if not valid_region_bbox(bbox, page.rect):
                    continue
                lines = lines_from_block(line_block)
                classification, reason = classify_text_region(lines)
                alignment = estimate_alignment(bbox, float(page.rect.width))
                region_id = f"{page_id}_line_{len(regions) + 1:04d}"
                regions.append(Region(
                    region_id=region_id,
                    bbox_points=bbox,
                    text=text,
                    block_index=block_index * 1000 + line_index,
                    lines=lines,
                    classification=classification,
                    classification_reason=reason,
                    alignment=alignment,
                ))
        else:
            text = text_from_block(block)
            if len(text.strip()) < min_chars:
                continue
            bbox = tuple(float(x) for x in block["bbox"])
            if not valid_region_bbox(bbox, page.rect):
                continue
            lines = lines_from_block(block)
            classification, reason = classify_text_region(lines)
            alignment = estimate_alignment(bbox, float(page.rect.width))
            region_id = f"{page_id}_txt_{len(regions) + 1:03d}"
            regions.append(Region(
                region_id=region_id,
                bbox_points=bbox,
                text=text,
                block_index=block_index,
                lines=lines,
                classification=classification,
                classification_reason=reason,
                alignment=alignment,
            ))
    regions.sort(key=lambda r: (round(r.bbox_points[1], 3), round(r.bbox_points[0], 3), r.region_id))
    return regions[:max_regions]


def horizontal_rule_segments(page: fitz.Page) -> list[tuple[float, float, float]]:
    segments: list[tuple[float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segments
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item:
                continue
            op = item[0]
            if op == "l" and len(item) >= 3:
                p1, p2 = item[1], item[2]
                x1, y1 = float(p1.x), float(p1.y)
                x2, y2 = float(p2.x), float(p2.y)
                if abs(y1 - y2) <= 0.75 and abs(x2 - x1) >= 2.0:
                    segments.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2.0))
            elif op == "re" and len(item) >= 2:
                rect = item[1]
                height = abs(float(rect.y1) - float(rect.y0))
                width = abs(float(rect.x1) - float(rect.x0))
                if height <= 1.5 and width >= 2.0:
                    segments.append((float(rect.x0), float(rect.x1), (float(rect.y0) + float(rect.y1)) / 2.0))
    return segments


def mark_underlined_spans(page: fitz.Page, regions: list[Region]) -> None:
    segments = horizontal_rule_segments(page)
    if not segments:
        return
    for region in regions:
        for line in region.lines:
            for span in line:
                bbox = span.get("bbox_points")
                if not bbox:
                    continue
                left, _top, right, bottom = [float(v) for v in bbox]
                width = max(0.1, right - left)
                for seg_left, seg_right, seg_y in segments:
                    overlap = max(0.0, min(right, seg_right) - max(left, seg_left))
                    if overlap / width >= 0.45 and bottom - 1.0 <= seg_y <= bottom + 3.0:
                        span["underline"] = True
                        break


def classify_layout_region(record: dict[str, Any], page_width: float) -> str:
    text = str(record.get("text", "")).strip()
    spans = [span for line in record.get("lines", []) for span in line]
    max_size = max((float(span.get("size_pt", 0)) for span in spans), default=0.0)
    left = float(record["bbox_points"][0])
    right = float(record["bbox_points"][2])
    width = right - left
    if max_size >= 18:
        return "heading"
    if "\t" in text or re_like_toc(text):
        return "table_or_toc_row"
    if width < page_width * 0.22 and text.replace(".", "").isdigit():
        return "table_or_toc_page_number"
    if max_size <= 8:
        return "caption_or_small_text"
    return "body_line"


def re_like_toc(text: str) -> bool:
    parts = text.strip().split()
    return bool(parts and parts[-1].isdigit() and len(parts) > 1)


def row_words_in_bbox(page: fitz.Page, bbox: tuple[float, float, float, float], row_tolerance: float) -> list[list[Any]]:
    left, top, right, bottom = bbox
    words = [
        word for word in page.get_text("words")
        if float(word[0]) >= left - 1.0
        and float(word[2]) <= right + 1.0
        and float(word[1]) >= top - 1.0
        and float(word[3]) <= bottom + 1.0
    ]
    rows: list[list[Any]] = []
    for word in sorted(words, key=lambda w: (round(float(w[1]) / row_tolerance), float(w[0]), int(w[5]), int(w[6]), int(w[7]))):
        y = float(word[1])
        for row in rows:
            if abs(row[0] - y) <= row_tolerance:
                row[1].append(word)
                row[0] = (row[0] + y) / 2.0
                break
        else:
            rows.append([y, [word]])
    return [sorted(row_words, key=lambda w: float(w[0])) for _y, row_words in sorted(rows, key=lambda item: item[0])]


def split_row_cells(row_words: list[Any], column_gap: float = 10.0) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    previous_right: float | None = None
    for word in row_words:
        gap = 0.0 if previous_right is None else float(word[0]) - previous_right
        if current and gap >= column_gap:
            cells.append(" ".join(current).strip())
            current = []
        current.append(str(word[4]))
        previous_right = float(word[2])
    if current:
        cells.append(" ".join(current).strip())
    return cells


def clean_table_rows(rows: list[list[Any]]) -> list[list[str]]:
    cleaned = [["" if cell is None else str(cell).strip() for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned:
        return []
    max_columns = max(len(row) for row in cleaned)
    padded = [row + [""] * (max_columns - len(row)) for row in cleaned]
    keep_columns = [
        index for index in range(max_columns)
        if any(row[index].strip() for row in padded)
    ]
    compact = [[row[index] for index in keep_columns] for row in padded]
    if len(compact) >= 2:
        first_nonempty = [index for index, cell in enumerate(compact[0]) if cell]
        second_nonempty = [index for index, cell in enumerate(compact[1]) if cell]
        if len(first_nonempty) == 1 and len(second_nonempty) >= 2:
            merged = compact[1][:]
            merged[first_nonempty[0]] = compact[0][first_nonempty[0]]
            compact = [merged] + compact[2:]
    return compact


def table_classification_from_rows(rows: list[list[str]], fallback: str = "structured_table") -> str:
    text = "\n".join(",".join(row) for row in rows).lower()
    if "avg." in text or "damage" in text or "$" in text:
        return "equipment_table"
    if "height" in text and "weight" in text:
        return "height_weight_table"
    if "bio-e" in text or "sdc" in text or "spd" in text:
        return "stat_table"
    if "speed:" in text or "tabletop inches" in text:
        return "movement_table"
    return fallback


def bbox_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return overlap / area


def excel_column_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def make_xlsx(output_path: Path, rows: list[list[str]], sheet_name: str = "Table") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    max_columns = max((len(row) for row in rows), default=1)
    normalized = [row + [""] * (max_columns - len(row)) for row in rows]
    sheet_rows = []
    for row_index, row in enumerate(normalized, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{excel_column_name(col_index)}{row_index}"
            safe = html.escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{safe}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    dimension = f"A1:{excel_column_name(max_columns)}{max(1, len(normalized))}"
    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<sheetData>'
        + "".join(sheet_rows)
        + '</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        f'<sheet name="{html.escape(sheet_name[:31])}" sheetId="1" r:id="rId1"/>'
        '</sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    def write_zip_text(zf: zipfile.ZipFile, arcname: str, text: str) -> None:
        info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, text.encode("utf-8"))

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        write_zip_text(zf, "[Content_Types].xml", content_types)
        write_zip_text(zf, "_rels/.rels", rels)
        write_zip_text(zf, "xl/workbook.xml", workbook_xml)
        write_zip_text(zf, "xl/_rels/workbook.xml.rels", workbook_rels)
        write_zip_text(zf, "xl/worksheets/sheet1.xml", worksheet_xml)


def table_block_score(text: str, csv_rows: list[list[str]]) -> tuple[str | None, float]:
    nonempty_rows = [row for row in csv_rows if any(cell.strip() for cell in row)]
    if len(nonempty_rows) < 3:
        return None, 0.0
    multi_col_rows = [row for row in nonempty_rows if len([cell for cell in row if cell.strip()]) >= 3]
    dense_ratio = len(multi_col_rows) / max(1, len(nonempty_rows))
    lower = text.lower()
    table_title = bool(re.search(r"\b(table|weapons|equipment|size|weight|bio-e|damage|avg\.|iq|ps|pe|spd|sdc)\b", lower))
    numeric_rows = sum(
        1 for row in nonempty_rows
        if len(row) >= 3 and sum(1 for cell in row if re.search(r"[\d$%]|yes|no|d\d", cell.lower())) >= 2
    )
    numeric_ratio = numeric_rows / max(1, len(nonempty_rows))
    max_columns = max(len(row) for row in nonempty_rows)
    if max_columns >= 4 and (dense_ratio >= 0.45 or numeric_ratio >= 0.35) and (table_title or numeric_ratio >= 0.5):
        if "avg." in lower or "damage" in lower or "$" in text:
            return "equipment_table", min(0.95, 0.55 + dense_ratio * 0.25 + numeric_ratio * 0.25)
        if "height" in lower and "weight" in lower:
            return "height_weight_table", min(0.95, 0.55 + dense_ratio * 0.25 + numeric_ratio * 0.25)
        if "bio-e" in lower or "sdc" in lower:
            return "stat_table", min(0.95, 0.55 + dense_ratio * 0.25 + numeric_ratio * 0.25)
        return "structured_table", min(0.9, 0.5 + dense_ratio * 0.25 + numeric_ratio * 0.25)
    return None, 0.0


def export_table_csvs(page: fitz.Page, page_id: str, table_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    table_dir.mkdir(parents=True, exist_ok=True)
    if not bool(config.get("tables", {}).get("enabled", True)):
        return []
    row_tolerance = float(config.get("tables", {}).get("row_tolerance_points", 4.0))
    records: list[dict[str, Any]] = []
    occupied_bboxes: list[tuple[float, float, float, float]] = []

    try:
        found_tables = page.find_tables().tables
    except Exception:
        found_tables = []
    for table in found_tables:
        rows = clean_table_rows(table.extract())
        if len(rows) < 2:
            continue
        max_columns = max(len(row) for row in rows)
        if max_columns < 2:
            continue
        classification = table_classification_from_rows(rows)
        table_id = f"{page_id}_table_{len(records) + 1:03d}_{classification}"
        out_path = table_dir / f"{table_id}.csv"
        xlsx_path = table_dir / f"{table_id}.xlsx"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
        make_xlsx(xlsx_path, rows, sheet_name=classification)
        bbox = tuple(float(v) for v in table.bbox)
        occupied_bboxes.append(bbox)
        records.append({
            "table_id": table_id,
            "classification": classification,
            "confidence": 0.98,
            "source": "pymupdf_find_tables",
            "bbox_points": [round(v, 3) for v in bbox],
            "file": out_path,
            "xlsx_file": xlsx_path,
            "rows": rows,
            "row_count": len(rows),
            "max_columns": max_columns,
        })

    for block_index, block in enumerate(page.get_text("dict").get("blocks", [])):
        if block.get("type") != 0:
            continue
        text = text_from_block(block)
        if not text.strip():
            continue
        bbox = tuple(float(v) for v in block["bbox"])
        if any(bbox_overlap(bbox, occupied) > 0.35 for occupied in occupied_bboxes):
            continue
        row_words = row_words_in_bbox(page, bbox, row_tolerance)
        csv_rows = clean_table_rows([split_row_cells(row) for row in row_words])
        classification, confidence = table_block_score(text, csv_rows)
        if not classification:
            continue
        max_columns = max(len(row) for row in csv_rows)
        normalized_rows = [row + [""] * (max_columns - len(row)) for row in csv_rows]
        table_id = f"{page_id}_table_{len(records) + 1:03d}_{classification}"
        out_path = table_dir / f"{table_id}.csv"
        xlsx_path = table_dir / f"{table_id}.xlsx"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(normalized_rows)
        make_xlsx(xlsx_path, normalized_rows, sheet_name=classification)
        records.append({
            "table_id": table_id,
            "classification": classification,
            "confidence": round(confidence, 3),
            "source": "pymupdf_text_block_word_columns",
            "block_index": block_index,
            "bbox_points": [round(v, 3) for v in bbox],
            "file": out_path,
            "xlsx_file": xlsx_path,
            "rows": normalized_rows,
            "row_count": len(normalized_rows),
            "max_columns": max_columns,
        })
    return records


def ocr_bbox(record: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = record.get("bbox_points")
    if not isinstance(bbox, list | tuple) or len(bbox) < 4:
        return None
    try:
        left, top, right, bottom = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def group_ocr_records_by_row(records: list[dict[str, Any]], row_tolerance: float) -> list[list[dict[str, Any]]]:
    rows: list[tuple[float, list[dict[str, Any]]]] = []
    for record in sorted(records, key=lambda item: ((ocr_bbox(item) or (0.0, 0.0, 0.0, 0.0))[1], (ocr_bbox(item) or (0.0, 0.0, 0.0, 0.0))[0])):
        bbox = ocr_bbox(record)
        if bbox is None:
            continue
        center_y = (bbox[1] + bbox[3]) / 2.0
        for index, (row_center, row_records) in enumerate(rows):
            if abs(center_y - row_center) <= row_tolerance:
                row_records.append(record)
                rows[index] = ((row_center * (len(row_records) - 1) + center_y) / len(row_records), row_records)
                break
        else:
            rows.append((center_y, [record]))
    return [
        sorted(row_records, key=lambda item: (ocr_bbox(item) or (0.0, 0.0, 0.0, 0.0))[0])
        for _center, row_records in sorted(rows, key=lambda item: item[0])
    ]


def ocr_row_text(row: list[dict[str, Any]]) -> str:
    return " ".join(str(record.get("text", "")).strip() for record in row if str(record.get("text", "")).strip())


def ocr_records_bbox(records: list[dict[str, Any]]) -> list[float]:
    bboxes = [bbox for record in records if (bbox := ocr_bbox(record)) is not None]
    if not bboxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(min(bbox[0] for bbox in bboxes), 3),
        round(min(bbox[1] for bbox in bboxes), 3),
        round(max(bbox[2] for bbox in bboxes), 3),
        round(max(bbox[3] for bbox in bboxes), 3),
    ]


def normalize_ocr_table_rows(rows: list[list[dict[str, Any]]]) -> list[list[str]]:
    text_rows = [[str(record.get("text", "")).strip() for record in row] for row in rows]
    text_rows = [[cell for cell in row if cell] for row in text_rows if any(cell for cell in row)]
    if not text_rows:
        return []
    max_columns = max(len(row) for row in text_rows)
    return [row + [""] * (max_columns - len(row)) for row in text_rows]


def table_title_like(text: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    return "table" in compact and any(term in compact for term in ("experience", "point", "damage", "roll", "weapon", "skill"))


def numeric_table_row_like(text: str) -> bool:
    return bool(re.match(r"^\s*(?:\d{1,4}(?:[-–]\d{1,4})?|\d+d\d+)\b", text.lower()))


def ocr_row_span_points(row: list[dict[str, Any]]) -> float:
    bboxes = [bbox for record in row if (bbox := ocr_bbox(record)) is not None]
    if not bboxes:
        return 0.0
    return max(bbox[2] for bbox in bboxes) - min(bbox[0] for bbox in bboxes)


def ocr_row_column_centers(row: list[dict[str, Any]]) -> list[float]:
    centers = []
    for record in row:
        bbox = ocr_bbox(record)
        if bbox is not None:
            centers.append((bbox[0] + bbox[2]) / 2.0)
    return centers


def ocr_table_structure_valid(
    candidate_rows: list[list[dict[str, Any]]],
    *,
    max_row_span_points: float = 360.0,
    min_data_rows: int = 3,
) -> bool:
    data_rows = [row for row in candidate_rows if len(row) >= 2]
    if len(data_rows) < min_data_rows:
        return False
    row_spans = [ocr_row_span_points(row) for row in data_rows]
    if not row_spans or max(row_spans) > max_row_span_points:
        return False

    first_centers: list[float] = []
    second_centers: list[float] = []
    for row in data_rows:
        centers = ocr_row_column_centers(row)
        if len(centers) < 2:
            continue
        first_centers.append(centers[0])
        second_centers.append(centers[1])
    if len(first_centers) < min_data_rows or len(second_centers) < min_data_rows:
        return False
    if max(first_centers) - min(first_centers) > 48.0:
        return False
    if max(second_centers) - min(second_centers) > 84.0:
        return False
    return True


def write_table_record(
    *,
    records: list[dict[str, Any]],
    rows: list[list[str]],
    table_dir: Path,
    page_id: str,
    table_number: int,
    classification: str,
    confidence: float,
) -> dict[str, Any]:
    table_id = f"{page_id}_table_{table_number:03d}_{classification}"
    out_path = table_dir / f"{table_id}.csv"
    xlsx_path = table_dir / f"{table_id}.xlsx"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    make_xlsx(xlsx_path, rows, sheet_name=classification)
    source_ids = [str(record.get("region_id", "")) for record in records if record.get("region_id")]
    return {
        "table_id": table_id,
        "classification": classification,
        "confidence": round(confidence, 3),
        "source": "ocr_table_reconstruction",
        "bbox_points": ocr_records_bbox(records),
        "file": out_path,
        "xlsx_file": xlsx_path,
        "rows": rows,
        "row_count": len(rows),
        "max_columns": max((len(row) for row in rows), default=0),
        "source_ocr_ids": source_ids,
    }


def export_ocr_table_csvs(
    ocr_records: list[dict[str, Any]] | None,
    page_id: str,
    table_dir: Path,
    config: dict[str, Any],
    existing_count: int = 0,
) -> list[dict[str, Any]]:
    if not ocr_records or not bool(config.get("tables", {}).get("ocr_reconstruction_enabled", True)):
        return []
    table_dir.mkdir(parents=True, exist_ok=True)
    row_tolerance = float(config.get("tables", {}).get("ocr_row_tolerance_points", 5.0))
    max_ocr_row_span = float(config.get("tables", {}).get("ocr_max_table_row_span_points", 360.0))
    max_title_table_height = float(config.get("tables", {}).get("ocr_max_title_table_height_points", 120.0))
    rows = group_ocr_records_by_row(ocr_records, row_tolerance)
    records: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for row_index, row in enumerate(rows):
        title_records = [record for record in row if table_title_like(str(record.get("text", "")))]
        if not title_records:
            continue
        title_bbox = ocr_records_bbox(title_records)
        left_limit = title_bbox[0] - 12.0
        right_limit = max(title_bbox[2] + 120.0, title_bbox[0] + 220.0)
        candidate_rows: list[list[dict[str, Any]]] = [title_records]
        blank_run = 0
        for following in rows[row_index + 1:]:
            following_bbox = ocr_records_bbox(following)
            if following_bbox[1] - title_bbox[3] > max_title_table_height:
                break
            cells = [
                record for record in following
                if (bbox := ocr_bbox(record)) is not None and left_limit <= bbox[0] <= right_limit
            ]
            if len(cells) >= 2 or (cells and len(candidate_rows) <= 2):
                candidate_rows.append(cells)
                blank_run = 0
            else:
                blank_run += 1
            if len(candidate_rows) >= 5 and blank_run >= 3:
                break
        data_rows = [candidate for candidate in candidate_rows[1:] if len(candidate) >= 2]
        if len(data_rows) < 3:
            continue
        source_records = [record for candidate in candidate_rows for record in candidate]
        source_key = {str(record.get("region_id", "")) for record in source_records}
        if used_ids.intersection(source_key):
            continue
        if not ocr_table_structure_valid(candidate_rows[1:], max_row_span_points=max_ocr_row_span):
            continue
        text_rows = normalize_ocr_table_rows(candidate_rows)
        classification = table_classification_from_rows(text_rows, fallback="ocr_reconstructed_table")
        if "experience" in " ".join(" ".join(row_text) for row_text in text_rows).lower():
            classification = "experience_points_table"
        records.append(write_table_record(
            records=source_records,
            rows=text_rows,
            table_dir=table_dir,
            page_id=page_id,
            table_number=existing_count + len(records) + 1,
            classification=classification,
            confidence=0.74,
        ))
        used_ids.update(source_key)

    def flush_numeric_rows() -> None:
        nonlocal numeric_rows
        if len(numeric_rows) < 3:
            numeric_rows = []
            return
        source_records = [record for candidate in numeric_rows for record in candidate]
        source_key = {str(record.get("region_id", "")) for record in source_records}
        if not used_ids.intersection(source_key) and ocr_table_structure_valid(
            numeric_rows,
            max_row_span_points=max_ocr_row_span,
        ):
            text_rows = []
            for candidate in numeric_rows:
                candidate_text = ocr_row_text(candidate)
                match = re.match(r"^\s*((?:\d{1,4}(?:[-–]\d{1,4})?|\d+d\d+))\s*(.*)$", candidate_text, re.IGNORECASE)
                text_rows.append([match.group(1), match.group(2).strip()] if match else [candidate_text])
            classification = table_classification_from_rows(text_rows, fallback="ocr_reconstructed_table")
            records.append(write_table_record(
                records=source_records,
                rows=text_rows,
                table_dir=table_dir,
                page_id=page_id,
                table_number=existing_count + len(records) + 1,
                classification=classification,
                confidence=0.68,
            ))
            used_ids.update(source_key)
        numeric_rows = []

    numeric_rows: list[list[dict[str, Any]]] = []
    for row in rows:
        text = ocr_row_text(row)
        if numeric_table_row_like(text):
            numeric_rows.append(row)
            continue
        flush_numeric_rows()
    flush_numeric_rows()
    return records


def export_region_images(
    page: fitz.Page,
    regions: list[Region],
    dpi: int,
    threshold: int,
    region_dir: Path,
) -> list[dict[str, Any]]:
    region_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    for region in regions:
        rect = fitz.Rect(region.bbox_points) & page.rect
        if rect.width <= 0.01 or rect.height <= 0.01:
            continue
        pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
        if pix.width <= 0 or pix.height <= 0:
            continue
        raw_path = region_dir / f"{region.region_id}_rgb.png"
        out_path = region_dir / f"{region.region_id}_gray_alpha.png"
        try:
            pix.save(str(raw_path))
        except Exception:
            continue
        with Image.open(raw_path) as img:
            gray = img.convert("L")
            alpha = gray.point(lambda p: 0 if p >= threshold else 255)
            la = Image.merge("LA", (gray, alpha))
            la.save(out_path)
            width, height = la.size
        raw_path.unlink(missing_ok=True)
        records.append({
            "region_id": region.region_id,
            "block_index": region.block_index,
            "bbox_points": [round(v, 3) for v in region.bbox_points],
            "text_length": len(region.text),
            "text": region.text,
            "lines": region.lines,
            "classification": region.classification,
            "classification_reason": region.classification_reason,
            "docx_handling": "editable_text_runs" if region.classification == "normal_editable_text" else "image_only",
            "layout_class": classify_layout_region({
                "text": region.text,
                "lines": region.lines,
                "bbox_points": [round(v, 3) for v in region.bbox_points],
            }, float(page.rect.width)),
            "alignment": region.alignment,
            "file": out_path,
            "mode": "LA",
            "width_px": width,
            "height_px": height,
        })
    return records


def rapidocr_text_for_image(ocr: Any, image_path: Path) -> tuple[str, float | None, list[dict[str, Any]]]:
    result, _elapsed = ocr(str(image_path))
    if result is None:
        return "", None, []
    texts: list[str] = []
    confidences: list[float] = []
    boxes: list[dict[str, Any]] = []
    for item in result:
        if len(item) < 3:
            continue
        box, text, confidence = item[0], str(item[1]), float(item[2])
        texts.append(text)
        confidences.append(confidence)
        boxes.append({"box": box, "text": text, "confidence": confidence})
    confidence_value = sum(confidences) / len(confidences) if confidences else None
    return "\n".join(texts).strip(), confidence_value, boxes


def rapidocr_records_for_image(image_path: Path, dpi: int) -> list[dict[str, Any]]:
    from rapidocr_onnxruntime import RapidOCR

    result, _elapsed = RapidOCR()(str(image_path))
    if result is None:
        return []
    scale = 72.0 / float(dpi)
    records: list[dict[str, Any]] = []
    for index, item in enumerate(result, start=1):
        if len(item) < 3:
            continue
        box, text, confidence = item[0], str(item[1]).strip(), float(item[2])
        if not text:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        bbox_points = [
            min(xs) * scale,
            min(ys) * scale,
            max(xs) * scale,
            max(ys) * scale,
        ]
        records.append({
            "region_id": f"ocr_{index:04d}",
            "engine": "rapidocr_onnxruntime",
            "fallback": False,
            "fallback_reason": None,
            "confidence": confidence,
            "boxes": [{"box": box, "text": text, "confidence": confidence}],
            "text": text,
            "bbox_points": [round(value, 3) for value in bbox_points],
        })
    return records


def write_ocr_editable_overlay_svg(
    path: Path,
    page: fitz.Page,
    page_id: str,
    render_record: dict[str, Any],
    ocr_records: list[dict[str, Any]],
) -> None:
    svg_ns = "{http://www.w3.org/2000/svg}"
    inkscape_ns = "{http://www.inkscape.org/namespaces/inkscape}"
    xlink_ns = "{http://www.w3.org/1999/xlink}"
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")

    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    root = ET.Element(
        f"{svg_ns}svg",
        {
            "version": "1.1",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            "viewBox": f"0 0 {page_width:g} {page_height:g}",
        },
    )
    image_layer = ET.SubElement(
        root,
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "visible_source_render_fidelity",
            "id": "visible_source_render_fidelity",
        },
    )
    image_data = base64.b64encode(Path(render_record["page_png"]).read_bytes()).decode("ascii")
    ET.SubElement(
        image_layer,
        f"{svg_ns}image",
        {
            "id": "source_page_render",
            "x": "0",
            "y": "0",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            f"{xlink_ns}href": f"data:image/png;base64,{image_data}",
        },
    )
    text_layer = ET.SubElement(
        root,
        f"{svg_ns}g",
        {
            f"{inkscape_ns}groupmode": "layer",
            f"{inkscape_ns}label": "ocr_editable_text_overlay",
            "id": "single_editable_layer",
            "data-pdfrejuvenator-layer-role": "ocr_editable_text_overlay",
        },
    )
    for index, record in enumerate(ocr_records, start=1):
        left, top, _right, bottom = [float(value) for value in record["bbox_points"]]
        height = max(3.0, bottom - top)
        font_size = max(4.0, min(18.0, height * 0.78))
        baseline = top + height * 0.82
        text = ET.SubElement(
            text_layer,
            f"{svg_ns}text",
            {
                "id": f"{page_id}_ocr_{index:04d}",
                "x": f"{left:.3f}",
                "y": f"{baseline:.3f}",
                "font-family": "Times New Roman",
                "font-size": f"{font_size:.3f}",
                "fill": "#000000",
                "fill-opacity": "0.82",
                "data-confidence": f"{float(record.get('confidence') or 0.0):.4f}",
            },
        )
        text.text = str(record.get("text", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def rtf_escape(text: str) -> str:
    chunks: list[str] = []
    for char in text:
        code = ord(char)
        if char in ("\\", "{", "}"):
            chunks.append("\\" + char)
        elif char == "\n":
            chunks.append("\\line ")
        elif char == "\t":
            chunks.append("\\tab ")
        elif 32 <= code <= 126:
            chunks.append(char)
        else:
            signed = code if code <= 32767 else code - 65536
            chunks.append(f"\\u{signed}?")
    return "".join(chunks)


def rtf_font_index(font: str, fonts: list[str]) -> int:
    try:
        return fonts.index(font)
    except ValueError:
        fonts.append(font)
        return len(fonts) - 1


def rtf_color_index(color: str, colors: list[str]) -> int:
    normalized = (color or "000000").strip().lstrip("#").upper()
    if len(normalized) != 6:
        normalized = "000000"
    try:
        return colors.index(normalized) + 1
    except ValueError:
        colors.append(normalized)
        return len(colors)


def rich_text_rtf(region_records: list[dict[str, Any]]) -> str:
    fonts = ["Times New Roman"]
    colors: list[str] = []
    body: list[str] = []
    for item in region_records:
        body.append(f"\\pard\\plain\\fs18\\b {rtf_escape(item['region_id'])}\\b0\\par\n")
        lines = item.get("lines", [])
        if not lines:
            body.append(rtf_escape(str(item.get("text", ""))) + "\\par\n")
            continue
        body.append("\\pard\\plain\n")
        for line_index, line in enumerate(lines):
            if line_index:
                body.append("\\line\n")
            for span in line:
                font = str(span.get("font", "Times New Roman"))
                font_id = rtf_font_index(font, fonts)
                color_id = rtf_color_index(str(span.get("color", "000000")), colors)
                size = max(2, int(round(float(span.get("size_pt", 11.0)) * 2)))
                style = [
                    f"\\f{font_id}",
                    f"\\fs{size}",
                    f"\\cf{color_id}",
                    "\\b" if span.get("bold") else "\\b0",
                    "\\i" if span.get("italic") else "\\i0",
                    "\\ul" if span.get("underline") else "\\ul0",
                ]
                body.append("{" + "".join(style) + " " + rtf_escape(str(span.get("text", ""))) + "}")
        body.append("\\ul0\\b0\\i0\\par\n")
    font_table = "{\\fonttbl" + "".join(
        f"{{\\f{index} {rtf_escape(font)};}}" for index, font in enumerate(fonts)
    ) + "}"
    color_table = "{\\colortbl;" + "".join(
        f"\\red{int(color[0:2], 16)}\\green{int(color[2:4], 16)}\\blue{int(color[4:6], 16)};"
        for color in colors
    ) + "}"
    return "{\\rtf1\\ansi\\deff0\\uc1\n" + font_table + "\n" + color_table + "\n" + "".join(body) + "}\n"


def run_ocr(
    region_records: list[dict[str, Any]],
    ocr_dir: Path,
    config: dict[str, Any],
    page_ocr_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ocr_dir.mkdir(parents=True, exist_ok=True)
    ocr_config = config.get("ocr", {})
    preferred = ocr_config.get("preferred_engine", "pymupdf_text_blocks")
    allow_fallback = bool(ocr_config.get("allow_fallback", True))
    if page_ocr_records is not None:
        text_lines = [
            f"## {record['region_id']}\n\n{record.get('text', '')}\n"
            for record in page_ocr_records
        ]
        ocr_json = ocr_dir / "ocr_regions.json"
        ocr_text = ocr_dir / "ocr_regions.txt"
        ocr_rtf = ocr_dir / "ocr_regions.rtf"
        write_json(ocr_json, {
            "engine": "rapidocr_onnxruntime",
            "preferred_engine": preferred,
            "allow_fallback": allow_fallback,
            "fallback_reason": None,
            "records": page_ocr_records,
        })
        write_text(ocr_text, "\n".join(text_lines))
        write_text(ocr_rtf, "{\\rtf1\\ansi\\deff0\n" + "\n".join(rtf_escape(line) + "\\par" for line in text_lines) + "\n}\n")
        return {
            "ocr_json": ocr_json,
            "ocr_text": ocr_text,
            "ocr_rtf": ocr_rtf,
            "records": page_ocr_records,
            "engine": "rapidocr_onnxruntime",
        }
    rapidocr = None
    engine = "pymupdf_text_blocks"
    fallback_reason = None
    if preferred == "rapidocr":
        try:
            from rapidocr_onnxruntime import RapidOCR
            rapidocr = RapidOCR()
            engine = "rapidocr_onnxruntime"
        except Exception as exc:
            if not allow_fallback:
                raise
            fallback_reason = f"rapidocr unavailable: {type(exc).__name__}: {exc}"
    records = []
    text_lines = []
    for item in region_records:
        text = item["text"]
        confidence = None
        boxes: list[dict[str, Any]] = []
        item_engine = "pymupdf_text_blocks"
        item_fallback = True
        item_fallback_reason = fallback_reason
        if rapidocr is not None:
            ocr_text, confidence, boxes = rapidocr_text_for_image(rapidocr, Path(item["file"]))
            if ocr_text:
                text = ocr_text
                item_engine = "rapidocr_onnxruntime"
                item_fallback = False
                item_fallback_reason = None
            elif allow_fallback:
                item_fallback_reason = "rapidocr returned no text; used PyMuPDF text block"
            else:
                text = ""
                item_engine = "rapidocr_onnxruntime"
                item_fallback = False
        records.append({
            "region_id": item["region_id"],
            "engine": item_engine,
            "fallback": item_fallback,
            "fallback_reason": item_fallback_reason,
            "confidence": confidence,
            "boxes": boxes,
            "text": text,
        })
        text_lines.append(f"## {item['region_id']}\n\n{text}\n")
    ocr_json = ocr_dir / "ocr_regions.json"
    ocr_text = ocr_dir / "ocr_regions.txt"
    ocr_rtf = ocr_dir / "ocr_regions.rtf"
    write_json(ocr_json, {
        "engine": engine,
        "preferred_engine": preferred,
        "allow_fallback": allow_fallback,
        "fallback_reason": fallback_reason,
        "records": records,
    })
    write_text(ocr_text, "\n".join(text_lines))
    write_text(ocr_rtf, rich_text_rtf(region_records))
    return {"ocr_json": ocr_json, "ocr_text": ocr_text, "ocr_rtf": ocr_rtf, "records": records, "engine": engine}


def html_document(page_id: str, render_record: dict[str, Any], region_records: list[dict[str, Any]], image_records: list[dict[str, Any]], root: Path) -> str:
    page_png_rel = html.escape("../" + stable_rel(render_record["page_png"], root))
    region_html = []
    for item in region_records:
        rel = html.escape("../" + stable_rel(item["file"], root))
        text = html.escape(item["text"])
        region_html.append(
            f"<section class=\"region\" id=\"{html.escape(item['region_id'])}\">"
            f"<h2>{html.escape(item['region_id'])}</h2>"
            f"<img src=\"{rel}\" alt=\"{html.escape(item['region_id'])} textbox image\">"
            f"<pre>{text}</pre>"
            "</section>"
        )
    image_html = []
    for item in image_records:
        rel = html.escape("../" + stable_rel(item["file"], root))
        image_html.append(
            f"<section class=\"region\" id=\"{html.escape(item['image_id'])}\">"
            f"<h2>{html.escape(item['image_id'])}</h2>"
            f"<img src=\"{rel}\" alt=\"{html.escape(item['image_id'])} embedded image resource\">"
            "</section>"
        )
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>{html.escape(page_id)} remaster test</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    .page-render {{ max-width: 900px; border: 1px solid #9aa8b4; }}
    .region {{ margin: 24px 0; padding-top: 12px; border-top: 1px solid #d4d7db; }}
    .region img {{ background: #f7f7f7; border: 1px solid #d4d7db; max-width: 100%; }}
    pre {{ white-space: pre-wrap; font-size: 13px; line-height: 1.35; }}
  </style>
</head>
<body>
  <h1>{html.escape(page_id)} remaster test</h1>
  <p>Page render, text regions, and embedded images are rebuilt from separate extracted resources.</p>
  <img class=\"page-render\" src=\"{page_png_rel}\" alt=\"full page render\">
  <h2>Extracted embedded/page images</h2>
  {''.join(image_html)}
  <h2>Extracted textbox regions</h2>
  {''.join(region_html)}
</body>
</html>
"""


def make_pdf(output_path: Path, page_id: str, render_record: dict[str, Any], region_records: list[dict[str, Any]], image_records: list[dict[str, Any]]) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_path), pagesize=letter, invariant=1, pageCompression=0)
    page_w, page_h = letter

    def draw_heading(text: str, x: float, y: float) -> float:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, text[:90])
        return y - 16

    def draw_image(path: Path, x: float, y: float, max_w: float, max_h: float) -> float:
        with Image.open(path) as img:
            width, height = img.size
        scale = min(max_w / max(1, width), max_h / max(1, height))
        draw_w = width * scale
        draw_h = height * scale
        c.drawImage(ImageReader(str(path)), x, y - draw_h, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
        return y - draw_h - 14

    def draw_text(text: str, x: float, y: float) -> float:
        c.setFont("Helvetica", 8)
        for raw_line in text.splitlines():
            line = raw_line.strip()
            while line:
                c.drawString(x, y, line[:105])
                line = line[105:]
                y -= 10
                if y < 54:
                    c.showPage()
                    y = page_h - 54
                    c.setFont("Helvetica", 8)
            if raw_line.strip() == "":
                y -= 6
        return y - 6

    y = page_h - 54
    y = draw_heading(f"{page_id} remaster test", 54, y)
    c.setFont("Helvetica", 9)
    c.drawString(54, y, "Rebuilt from separate page render, embedded image, textbox image, and OCR/text resources.")
    y -= 18
    y = draw_heading("Full page render", 54, y)
    y = draw_image(Path(render_record["page_png"]), 54, y, page_w - 108, page_h - 160)
    c.showPage()

    y = page_h - 54
    y = draw_heading("Extracted embedded/page images", 54, y)
    for item in image_records:
        if y < 220:
            c.showPage()
            y = page_h - 54
        y = draw_heading(item["image_id"], 54, y)
        y = draw_image(Path(item["file"]), 54, y, page_w - 108, 180)

    c.showPage()
    y = page_h - 54
    y = draw_heading("Extracted textbox regions and OCR text", 54, y)
    for item in region_records:
        if y < 240:
            c.showPage()
            y = page_h - 54
        y = draw_heading(item["region_id"], 54, y)
        y = draw_image(Path(item["file"]), 54, y, page_w - 108, 140)
        y = draw_text(item["text"], 54, y)
    c.save()


def _content_types_xml(image_names: list[str], embedded_package_count: int = 0) -> str:
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Default Extension="png" ContentType="image/png"/>',
    ]
    if embedded_package_count:
        defaults.append('<Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + "".join(defaults)
        + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        + "</Types>"
    )


def _rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )


def _document_rels_xml(image_count: int, embedded_package_count: int = 0) -> str:
    rels = []
    for index in range(1, image_count + 1):
        rels.append(
            f'<Relationship Id="rIdImg{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image{index}.png"/>'
        )
    for index in range(1, embedded_package_count + 1):
        rels.append(
            f'<Relationship Id="rIdXlsx{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/package" Target="embeddings/table{index}.xlsx"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )


def _points_to_twips(value: float) -> int:
    return int(round(value * 20))


def _points_to_emu(value: float) -> int:
    return int(round(value * 12700))


def _docpr_id(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:7], 16)


def _paragraph(text: str, style: dict[str, Any] | None = None, alignment: str = "left") -> str:
    safe = html.escape(text)
    return _styled_paragraph([[{**(style or {}), "text": text}]], alignment=alignment) if style else f"<w:p><w:pPr><w:jc w:val=\"{alignment}\"/></w:pPr><w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"


def _run_properties(span: dict[str, Any], hidden: bool = False) -> str:
    font = html.escape(str(span.get("font", "Arial")))
    size = max(1, int(round(float(span.get("size_pt", 11.0)) * 2)))
    color = html.escape(str(span.get("color", "000000")))
    bold = "<w:b/>" if span.get("bold") else ""
    italic = "<w:i/>" if span.get("italic") else ""
    underline = '<w:u w:val="single"/>' if span.get("underline") else ""
    vanish = "<w:vanish/>" if hidden else ""
    return (
        "<w:rPr>"
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>'
        f"<w:sz w:val=\"{size}\"/><w:szCs w:val=\"{size}\"/>"
        f"<w:color w:val=\"{color}\"/>"
        f"{bold}{italic}{underline}{vanish}"
        "</w:rPr>"
    )


def _styled_paragraph(lines: list[list[dict[str, Any]]], alignment: str = "left", hidden: bool = False) -> str:
    runs = []
    first_line = True
    for line in lines:
        if not first_line:
            runs.append("<w:r><w:br/></w:r>")
        first_line = False
        for span in line:
            text = html.escape(str(span.get("text", "")))
            if text:
                runs.append(f"<w:r>{_run_properties(span, hidden=hidden)}<w:t xml:space=\"preserve\">{text}</w:t></w:r>")
    return (
        "<w:p>"
        f"<w:pPr><w:jc w:val=\"{alignment}\"/><w:spacing w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>"
        + "".join(runs)
        + "</w:p>"
    )


def _textbox_paragraph(region: dict[str, Any], hidden: bool = False) -> str:
    left, top, right, bottom = [float(v) for v in region["bbox_points"]]
    width = max(18.0, right - left)
    height = max(12.0, bottom - top)
    shape_id = html.escape(region["region_id"])
    content = _styled_paragraph(region["lines"], alignment=region.get("alignment", "left"), hidden=hidden)
    docpr_id = _docpr_id(region["region_id"])
    return f"""
<w:p><w:r><w:drawing>
<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" simplePos="0" relativeHeight="200000" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
<wp:simplePos x="0" y="0"/>
<wp:positionH relativeFrom="page"><wp:posOffset>{_points_to_emu(left)}</wp:posOffset></wp:positionH>
<wp:positionV relativeFrom="page"><wp:posOffset>{_points_to_emu(top)}</wp:posOffset></wp:positionV>
<wp:extent cx="{_points_to_emu(width)}" cy="{_points_to_emu(height)}"/>
<wp:effectExtent l="0" t="0" r="0" b="0"/>
<wp:wrapNone/>
<wp:docPr id="{docpr_id}" name="{shape_id}"/>
<wp:cNvGraphicFramePr/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:wsp xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:cNvSpPr txBox="1"/>
<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_points_to_emu(width)}" cy="{_points_to_emu(height)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>
<wps:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"/>
<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>
</wps:wsp>
</a:graphicData>
</a:graphic>
</wp:anchor>
</w:drawing></w:r></w:p>
"""


def _image_paragraph(rel_id: str, name: str, width_px: int, height_px: int) -> str:
    max_width_emu = 5_200_000
    scale = min(1.0, max_width_emu / max(1, width_px * 9525))
    cx = int(width_px * 9525 * scale)
    cy = int(height_px * 9525 * scale)
    safe_name = html.escape(name)
    return f"""
<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">
<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="1" name="{safe_name}"/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="{safe_name}"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
"""


def _positioned_image_paragraph(
    rel_id: str,
    name: str,
    bbox_points: list[float] | None,
    width_px: int,
    height_px: int,
    *,
    behind_text: bool = False,
    relative_height: int = 1,
) -> str:
    if not bbox_points:
        return _image_paragraph(rel_id, name, width_px, height_px)
    left, top, right, bottom = [float(v) for v in bbox_points]
    width = max(18.0, right - left)
    height = max(12.0, bottom - top)
    cx = _points_to_twips(width) * 635
    cy = _points_to_twips(height) * 635
    safe_name = html.escape(name)
    behind = "1" if behind_text else "0"
    return f"""
<w:p><w:r><w:drawing><wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" simplePos="0" relativeHeight="{relative_height}" behindDoc="{behind}" locked="0" layoutInCell="1" allowOverlap="1">
<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>{_points_to_twips(left) * 635}</wp:posOffset></wp:positionH><wp:positionV relativeFrom="page"><wp:posOffset>{_points_to_twips(top) * 635}</wp:posOffset></wp:positionV>
<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/><wp:docPr id="1" name="{safe_name}"/><wp:cNvGraphicFramePr/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="{safe_name}"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p>
"""


def _table_cell(text: str, bold: bool = False, hidden: bool = False) -> str:
    safe = html.escape(str(text))
    run_properties = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:vanish/>" if hidden else "") + "</w:rPr>"
    return (
        "<w:tc><w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
        f"<w:p><w:r>{run_properties}<w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
        "</w:tc>"
    )


def _word_table(rows: list[list[str]], hidden: bool = False) -> str:
    if not rows:
        return ""
    max_columns = max(len(row) for row in rows)
    table_rows = []
    for row_index, row in enumerate(rows):
        padded = row + [""] * (max_columns - len(row))
        cells = "".join(_table_cell(cell, bold=(row_index == 0), hidden=hidden) for cell in padded)
        table_rows.append(f"<w:tr>{cells}</w:tr>")
    grid = "".join("<w:gridCol w:w=\"1200\"/>" for _ in range(max_columns))
    borders = (
        "<w:tblBorders><w:top w:val=\"nil\"/><w:left w:val=\"nil\"/><w:bottom w:val=\"nil\"/><w:right w:val=\"nil\"/><w:insideH w:val=\"nil\"/><w:insideV w:val=\"nil\"/></w:tblBorders>"
        if hidden else
        "<w:tblBorders><w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"808080\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"808080\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"808080\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"808080\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"C0C0C0\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"C0C0C0\"/></w:tblBorders>"
    )
    return (
        "<w:tbl>"
        "<w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/>"
        f"{borders}"
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        + "".join(table_rows)
        + "</w:tbl>"
    )


def _table_textbox_paragraph(table: dict[str, Any], hidden: bool = False) -> str:
    left, top, right, bottom = [float(v) for v in table["bbox_points"]]
    width = max(36.0, right - left)
    height = max(24.0, bottom - top)
    shape_id = html.escape(str(table["table_id"]))
    content = _word_table(table.get("rows", []), hidden=hidden)
    docpr_id = _docpr_id(str(table["table_id"]))
    return f"""
<w:p><w:r><w:drawing>
<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" simplePos="0" relativeHeight="300000" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">
<wp:simplePos x="0" y="0"/>
<wp:positionH relativeFrom="page"><wp:posOffset>{_points_to_emu(left)}</wp:posOffset></wp:positionH>
<wp:positionV relativeFrom="page"><wp:posOffset>{_points_to_emu(top)}</wp:posOffset></wp:positionV>
<wp:extent cx="{_points_to_emu(width)}" cy="{_points_to_emu(height)}"/>
<wp:effectExtent l="0" t="0" r="0" b="0"/>
<wp:wrapNone/>
<wp:docPr id="{docpr_id}" name="{shape_id}"/>
<wp:cNvGraphicFramePr/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:wsp xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:cNvSpPr txBox="1"/>
<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{_points_to_emu(width)}" cy="{_points_to_emu(height)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>
<wps:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"/>
<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>
</wps:wsp>
</a:graphicData>
</a:graphic>
</wp:anchor>
</w:drawing></w:r></w:p>
"""


def _drawing_run_from_paragraph(paragraph_xml: str) -> str:
    stripped = paragraph_xml.strip()
    if stripped.startswith("<w:p>") and stripped.endswith("</w:p>"):
        return stripped[len("<w:p>"):-len("</w:p>")]
    return stripped


def make_docx(
    output_path: Path,
    page_id: str,
    render_record: dict[str, Any],
    region_records: list[dict[str, Any]],
    image_records: list[dict[str, Any]],
    table_records: list[dict[str, Any]] | None = None,
    page_rect_points: list[float] | None = None,
    visual_fidelity_background: bool = False,
    hidden_editable_overlay: bool = False,
) -> None:
    table_records = table_records or []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_entries: list[tuple[Path, str, int, int, list[float] | None, str]] = []
    if visual_fidelity_background:
        page_bbox = page_rect_points or [0.0, 0.0, 612.0, 792.0]
        image_entries.append(
            (
                Path(render_record["page_png"]),
                f"{page_id}_full_page_render_background",
                int(render_record["width_px"]),
                int(render_record["height_px"]),
                page_bbox,
                "page_background",
            )
        )
    sorted_image_records = sorted(
        image_records,
        key=lambda item: (
            0 if item.get("classification") == "page_background" else 1,
            float(item.get("bbox_area_ratio", 0.0)),
        ),
        reverse=False,
    )
    image_entries.extend(
        (
            Path(item["file"]),
            item["image_id"],
            item["width_px"],
            item["height_px"],
            item.get("bbox_points"),
            item.get("classification", "content_image"),
        )
        for item in sorted_image_records
        if not visual_fidelity_background
    )
    image_entries.extend(
        (Path(item["file"]), item["region_id"], item["width_px"], item["height_px"], item.get("bbox_points"), "textbox_region_image")
        for item in region_records
        if item["classification"] != "normal_editable_text"
    )
    images: list[Path] = [entry[0] for entry in image_entries]
    body: list[str] = []
    for offset, (_path, name, width, height, bbox_points, classification) in enumerate(image_entries, start=1):
        is_background = classification == "page_background"
        body.append(
            _positioned_image_paragraph(
                f"rIdImg{offset}",
                name,
                bbox_points,
                width,
                height,
                behind_text=is_background,
                relative_height=0 if is_background else 1,
            )
        )
    table_bboxes = [tuple(float(v) for v in table["bbox_points"]) for table in table_records]
    hidden_overlay_runs: list[str] = []
    for table in table_records:
        table_xml = _table_textbox_paragraph(table, hidden=hidden_editable_overlay)
        if hidden_editable_overlay:
            hidden_overlay_runs.append(_drawing_run_from_paragraph(table_xml))
        else:
            body.append(table_xml)
    for item in region_records:
        item_bbox = tuple(float(v) for v in item.get("bbox_points", [0, 0, 0, 0]))
        if any(bbox_overlap(item_bbox, table_bbox) > 0.7 for table_bbox in table_bboxes):
            continue
        if item["classification"] == "normal_editable_text":
            textbox_xml = _textbox_paragraph(item, hidden=hidden_editable_overlay)
            if hidden_editable_overlay:
                hidden_overlay_runs.append(_drawing_run_from_paragraph(textbox_xml))
            else:
                body.append(textbox_xml)
        else:
            media_index = next(
                (idx for idx, (_path, name, _width, _height, _bbox, _classification) in enumerate(image_entries, start=1) if name == item["region_id"]),
                None,
            )
            if media_index is not None:
                body.append(_image_paragraph(f"rIdImg{media_index}", item["region_id"], item["width_px"], item["height_px"]))
            for line in item["text"].splitlines():
                body.append(_paragraph(line))
    if hidden_overlay_runs:
        body.append(
            '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/></w:pPr>'
            + "".join(hidden_overlay_runs)
            + "</w:p>"
        )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    def write_zip_text(zf: zipfile.ZipFile, arcname: str, text: str) -> None:
        info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, text.encode("utf-8"))

    def write_zip_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
        info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, data)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        embedded_xlsx = [Path(table["xlsx_file"]) for table in table_records if table.get("xlsx_file")]
        write_zip_text(zf, "[Content_Types].xml", _content_types_xml([p.name for p in images], len(embedded_xlsx)))
        write_zip_text(zf, "_rels/.rels", _rels_xml())
        write_zip_text(zf, "word/_rels/document.xml.rels", _document_rels_xml(len(images), len(embedded_xlsx)))
        write_zip_text(zf, "word/document.xml", document_xml)
        for index, src in enumerate(images, start=1):
            with Image.open(src) as img:
                tmp = output_path.parent / f"__docx_image{index}.png"
                img.convert("RGBA").save(tmp)
            write_zip_bytes(zf, f"word/media/image{index}.png", tmp.read_bytes())
            tmp.unlink(missing_ok=True)
        for index, src in enumerate(embedded_xlsx, start=1):
            write_zip_bytes(zf, f"word/embeddings/table{index}.xlsx", src.read_bytes())


def collect_files(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().lower()):
        if path.is_file():
            records.append({
                "path": stable_rel(path, root),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return records


def run_pipeline(config_path: Path, clean: bool = False) -> dict[str, Any]:
    config = read_json(config_path)
    output_root = Path(config["output_root"])
    if clean:
        clean_output(output_root)
    else:
        output_root.mkdir(parents=True, exist_ok=True)

    source_pdf, doc, page_number = load_pdf(config)
    source_hash = sha256_file(source_pdf)
    expected_hash = config.get("source_pdf_expected_sha256")
    if expected_hash is not None and expected_hash != source_hash:
        raise ValueError("source_pdf_expected_sha256 does not match source file")

    page = doc[page_number - 1]
    page_id = f"{config['job_id']}_p{page_number:03d}"
    dpi = int(config["render"]["dpi"])
    threshold = int(config["render"]["transparent_threshold"])

    render_record = render_page(page, page_id, dpi, output_root / "page_render")
    svg_record = export_svg_artifacts(page, page_id, output_root / "inkscape", render_record)
    image_records = extract_embedded_images(doc, page, page_id, output_root / "embedded_images")
    regions = detect_text_regions(
        page,
        page_id,
        int(config["regions"]["max_text_regions"]),
        int(config["regions"]["min_text_chars"]),
        str(config["regions"].get("layout_strategy", "block")),
    )
    mark_underlined_spans(page, regions)
    region_records = export_region_images(page, regions, dpi, threshold, output_root / "textbox_regions")
    page_ocr_records = None
    ocr_config = config.get("ocr", {})
    if (
        not region_records
        and ocr_config.get("preferred_engine") == "rapidocr"
        and bool(ocr_config.get("image_only_fallback", True))
    ):
        page_ocr_records = rapidocr_records_for_image(Path(render_record["page_png"]), dpi)
        if page_ocr_records:
            for index, record in enumerate(page_ocr_records, start=1):
                record["region_id"] = f"{page_id}_ocr_{index:04d}"
            ocr_overlay_svg = output_root / "inkscape" / f"{page_id}_ocr_editable_overlay.svg"
            write_ocr_editable_overlay_svg(ocr_overlay_svg, page, page_id, render_record, page_ocr_records)
            svg_record["ocr_editable_overlay_svg"] = ocr_overlay_svg
            svg_record["single_editable_layer_svg"] = ocr_overlay_svg
            svg_record["editable_text_count"] = len(page_ocr_records)
    table_records = export_table_csvs(page, page_id, output_root / "tables", config)
    table_records.extend(export_ocr_table_csvs(
        page_ocr_records,
        page_id,
        output_root / "tables",
        config,
        existing_count=len(table_records),
    ))
    ocr_record = run_ocr(region_records, output_root / "ocr", config, page_ocr_records)

    rebuild_dir = output_root / "rebuilt"
    html_path = rebuild_dir / f"{page_id}.html"
    pdf_path = rebuild_dir / f"{page_id}.pdf"
    docx_path = rebuild_dir / f"{page_id}.docx"
    write_text(html_path, html_document(page_id, render_record, region_records, image_records, output_root))
    make_pdf(pdf_path, page_id, render_record, region_records, image_records)
    rebuild_config = config.get("rebuild", {})
    make_docx(
        docx_path,
        page_id,
        render_record,
        region_records,
        image_records,
        table_records,
        page_rect_points=[round(float(v), 3) for v in page.rect],
        visual_fidelity_background=bool(rebuild_config.get("include_page_render_as_docx_background", False)),
        hidden_editable_overlay=bool(rebuild_config.get("hidden_editable_overlay", False)),
    )

    manifest = {
        "job_id": config["job_id"],
        "config_path": str(config_path),
        "source_pdf": str(source_pdf),
        "source_pdf_sha256": source_hash,
        "selected_page_1based": page_number,
        "page_id": page_id,
        "page_rect_points": [round(float(v), 3) for v in page.rect],
        "dependencies": dependency_versions(),
        "render": {
            **{k: stable_rel(v, output_root) if isinstance(v, Path) else v for k, v in render_record.items()},
            "page_png_sha256": sha256_file(render_record["page_png"]),
            "page_tiff_sha256": sha256_file(render_record["page_tiff"]),
        },
        "inkscape": {
            "editable_text_svg": stable_rel(svg_record["editable_text_svg"], output_root),
            "path_fidelity_svg": stable_rel(svg_record["path_fidelity_svg"], output_root),
            "inkscape_layered_svg": stable_rel(svg_record["inkscape_layered_svg"], output_root),
            "inkscape_fidelity_svg": stable_rel(svg_record["inkscape_fidelity_svg"], output_root),
            "path_art_plus_editable_text_svg": stable_rel(svg_record["path_art_plus_editable_text_svg"], output_root),
            "single_editable_layer_svg": stable_rel(svg_record["single_editable_layer_svg"], output_root),
            "single_editable_layer_id": svg_record["single_editable_layer_id"],
            "editable_text_count": svg_record["editable_text_count"],
            "path_text_uses_removed": svg_record["path_text_uses_removed"],
            "path_font_defs_removed": svg_record["path_font_defs_removed"],
            "single_layer_text_uses_removed": svg_record["single_layer_text_uses_removed"],
            "single_layer_font_defs_removed": svg_record["single_layer_font_defs_removed"],
            "editable_text_svg_sha256": sha256_file(svg_record["editable_text_svg"]),
            "path_fidelity_svg_sha256": sha256_file(svg_record["path_fidelity_svg"]),
            "inkscape_layered_svg_sha256": sha256_file(svg_record["inkscape_layered_svg"]),
            "inkscape_fidelity_svg_sha256": sha256_file(svg_record["inkscape_fidelity_svg"]),
            "path_art_plus_editable_text_svg_sha256": sha256_file(svg_record["path_art_plus_editable_text_svg"]),
            "single_editable_layer_svg_sha256": sha256_file(svg_record["single_editable_layer_svg"]),
        },
        "embedded_images": [
            {**{k: stable_rel(v, output_root) if isinstance(v, Path) else v for k, v in rec.items()}, "sha256": sha256_file(rec["file"])}
            for rec in image_records
        ],
        "textbox_regions": [
            {**{k: stable_rel(v, output_root) if isinstance(v, Path) else v for k, v in rec.items()}, "sha256": sha256_file(rec["file"])}
            for rec in region_records
        ],
        "tables": [
            {
                **{k: stable_rel(v, output_root) if isinstance(v, Path) else v for k, v in rec.items()},
                "sha256": sha256_file(rec["file"]),
                "xlsx_sha256": sha256_file(rec["xlsx_file"]) if rec.get("xlsx_file") else None,
            }
            for rec in table_records
        ],
        "ocr": {
            "ocr_json": stable_rel(ocr_record["ocr_json"], output_root),
            "ocr_text": stable_rel(ocr_record["ocr_text"], output_root),
            "ocr_rtf": stable_rel(ocr_record["ocr_rtf"], output_root),
            "engine": ocr_record["engine"],
            "fallback": any(record.get("fallback") for record in ocr_record["records"]),
            "record_count": len(ocr_record["records"]),
        },
        "rebuilt": {
            "html": stable_rel(html_path, output_root),
            "pdf": stable_rel(pdf_path, output_root),
            "docx": stable_rel(docx_path, output_root),
            "docx_visual_fidelity_background": bool(rebuild_config.get("include_page_render_as_docx_background", False)),
            "docx_hidden_editable_overlay": bool(rebuild_config.get("hidden_editable_overlay", False)),
        },
    }
    write_json(output_root / "manifest.json", manifest)
    checksum_manifest = {"files": collect_files(output_root)}
    write_json(output_root / "checksums.json", checksum_manifest)
    return manifest
