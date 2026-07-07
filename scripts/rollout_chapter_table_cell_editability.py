from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageChops, ImageDraw
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from doc_pipeline import read_json, write_json, write_text  # noqa: E402
from render_inkscape_visual_comparisons import find_inkscape  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PAGE_HEIGHT = 792.0
REFERENCE_HEADER_CALIBRATION_ROOT = ROOT / "outputs" / "pdfrejuvenator_calibration" / "inkscape_header_calibration_rollout"
VISUAL_FIDELITY_REVIEW_PAGES = {
    1,
    2,
    4,
    5,
    7,
    12,
    14,
    15,
    17,
    20,
    21,
    24,
    25,
    27,
    28,
    29,
    30,
    31,
    34,
    35,
    36,
    37,
    39,
    41,
    42,
    43,
    44,
    47,
    51,
    52,
    53,
    55,
    62,
    63,
    64,
    68,
    72,
    75,
    80,
    86,
    90,
    93,
    94,
    96,
    97,
    120,
    170,
    180,
    240,
    248,
    249,
    268,
    269,
    270,
    271,
    272,
    274,
}


def read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def text_value(element: ET.Element) -> str:
    return "".join(element.itertext())


def normalize_editable_line_text(value: str) -> str:
    value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)
    value = re.sub(r"(?<=\d)\s+(?=[.,;:])", "", value)
    value = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", value)
    value = re.sub(r"(?<!\w)-\s+(?=\d)", "-", value)
    value = re.sub(r"(?<=\d)(?=[A-Z][a-z])", " ", value)
    value = re.sub(r"(?<=%)\s*(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z)])\s*(?=\$)", " ", value)
    return value


def split_positioned_tspan_text(value: str, xs: list[str], gap_threshold: float = 22.0) -> list[tuple[str, str]]:
    if len(xs) <= 1:
        return [(value, xs[0] if xs else "0")]
    try:
        positions = [float(x) for x in xs]
    except ValueError:
        return [(value, xs[0])]
    chars = list(value)
    if len(chars) != len(positions):
        return [(value, xs[0])]
    segments: list[tuple[str, str]] = []
    start = 0
    for idx in range(1, len(chars)):
        gap = positions[idx] - positions[idx - 1]
        if gap > gap_threshold and "".join(chars[start:idx]).strip():
            segments.append(("".join(chars[start:idx]), xs[start]))
            start = idx
    if "".join(chars[start:]).strip():
        segments.append(("".join(chars[start:]), xs[start]))
    return segments or [(value, xs[0])]


def font_face_css(fonts: list[Path], prefix: str) -> str:
    rules = []
    for font in sorted(fonts, key=lambda path: path.name.lower()):
        family = font.stem
        fmt = "truetype" if font.suffix.lower() == ".ttf" else "opentype"
        weight = "bold" if "bold" in family.lower() else "normal"
        style = "italic" if "italic" in family.lower() else "normal"
        rules.append(
            "\n".join(
                [
                    "@font-face {",
                    f"  font-family: '{family}';",
                    f"  src: url('{prefix}/{font.name}') format('{fmt}');",
                    f"  font-weight: {weight};",
                    f"  font-style: {style};",
                    "}",
                ]
            )
        )
    return "\n\n".join(rules) + "\n"


def inject_font_faces(root: ET.Element, css: str) -> None:
    defs = root.find(f"{{{SVG_NS}}}defs")
    if defs is None:
        defs = ET.Element(f"{{{SVG_NS}}}defs")
        root.insert(0, defs)
    for style in list(defs.findall(f"{{{SVG_NS}}}style")):
        if style.attrib.get("data-pdfrejuvenator-role") == "portable-font-face":
            defs.remove(style)
    style = ET.SubElement(defs, f"{{{SVG_NS}}}style")
    style.set("type", "text/css")
    style.set("data-pdfrejuvenator-role", "portable-font-face")
    style.text = "\n" + css


def collect_font_advances(root: ET.Element) -> dict[str, dict[str, list[float]]]:
    observed: dict[str, dict[str, list[float]]] = {}
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") == "hwtartz_header_flow_editable":
            continue
        family = text.attrib.get("font-family")
        size_text = text.attrib.get("font-size")
        if not family or not size_text:
            continue
        try:
            size = float(size_text)
        except ValueError:
            continue
        if size <= 0:
            continue
        for tspan in text.findall(f"{{{SVG_NS}}}tspan"):
            value = text_value(tspan)
            try:
                xs = [float(x) for x in tspan.attrib.get("x", "").split()]
            except ValueError:
                continue
            if len(xs) <= 1:
                continue
            fam = observed.setdefault(family, {})
            for idx, char in enumerate(value[:-1]):
                if idx + 1 >= len(xs):
                    continue
                advance = xs[idx + 1] - xs[idx]
                if advance > 0:
                    fam.setdefault(char, []).append(advance / size)
    return observed


def safe_family_name(family: str, page: int) -> str:
    return "PDFRejuvenator" + "".join(ch for ch in family if ch.isalnum()) + f"P{page:03d}"


def make_calibrated_font(source_font: Path, output_font: Path, family: str, observed: dict[str, list[float]]) -> dict[str, Any]:
    font = TTFont(source_font)
    units_per_em = int(font["head"].unitsPerEm)
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    charstrings = None
    if "CFF " in font:
        cff = font["CFF "].cff
        top = cff.topDictIndex[0]
        cff.fontNames = [family]
        top.FullName = family
        top.FamilyName = family
        top.Weight = "Bold" if "bold" in source_font.stem.lower() else "Regular"
        charstrings = top.CharStrings
    changed = {}
    for char, ratios in observed.items():
        if char.isdigit():
            continue
        glyph = cmap.get(ord(char))
        if not glyph:
            continue
        advance_units = int(round((sum(ratios) / len(ratios)) * units_per_em))
        old_advance, lsb = hmtx[glyph]
        hmtx[glyph] = (advance_units, lsb)
        if charstrings is not None and glyph in charstrings:
            charstrings[glyph].width = advance_units
        changed[char] = {
            "glyph": glyph,
            "old_advance": old_advance,
            "new_advance": advance_units,
            "observations": len(ratios),
        }
    subfamily = "Bold" if "bold" in source_font.stem.lower() else "Regular"
    for name_id, value in [
        (1, family),
        (2, subfamily),
        (3, f"{family};PDFRejuvenator;2026-06-19"),
        (4, family),
        (6, family),
        (16, family),
        (17, subfamily),
    ]:
        font["name"].setName(value, name_id, 3, 1, 0x409)
        font["name"].setName(value, name_id, 1, 0, 0)
    output_font.parent.mkdir(parents=True, exist_ok=True)
    font.save(output_font)
    return {
        "source_font": str(source_font),
        "calibrated_font": str(output_font),
        "font_family": family,
        "changed_glyph_count": len(changed),
    }


def build_calibrated_body_fonts(root: ET.Element, page: int, source_fonts_dir: Path, output_fonts_dir: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    observed = collect_font_advances(root)
    family_map: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for family, advances in sorted(observed.items()):
        if family == "HWTArtz":
            continue
        source_font = source_fonts_dir / f"{family}.otf"
        if not source_font.exists():
            source_font = source_fonts_dir / f"{family}.ttf"
        if not source_font.exists():
            continue
        calibrated_family = safe_family_name(family, page)
        output_font = output_fonts_dir / f"{calibrated_family}{source_font.suffix}"
        record = make_calibrated_font(source_font, output_font, calibrated_family, advances)
        family_map[family] = calibrated_family
        records.append(record)
    return family_map, records


def build_calibrated_casual_fonts(root: ET.Element, page: int, source_fonts_dir: Path, output_fonts_dir: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    observed = collect_font_advances(root)
    family_map: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for family in ("BlambotCasual", "BlambotCasual-Bold"):
        advances = observed.get(family)
        if not advances:
            continue
        source_font = source_fonts_dir / f"{family}.otf"
        if not source_font.exists():
            source_font = source_fonts_dir / f"{family}.ttf"
        if not source_font.exists():
            continue
        calibrated_family = safe_family_name(family, page)
        output_font = output_fonts_dir / f"{calibrated_family}{source_font.suffix}"
        record = make_calibrated_font(source_font, output_font, calibrated_family, advances)
        record["strategy"] = "calibrated_casual_table_and_list_font"
        family_map[family] = calibrated_family
        records.append(record)
    return family_map, records


def convert_tspan_text_to_lines(root: ET.Element, page: int, family_map: dict[str, str]) -> list[dict[str, Any]]:
    parents = parent_map(root)
    converted: list[dict[str, Any]] = []
    line_counter = 1
    for text in list(root.iter(f"{{{SVG_NS}}}text")):
        if text.attrib.get("data-pdfrejuvenator-calibration") == "hwtartz_header_flow_editable":
            continue
        if text.attrib.get("data-pdfrejuvenator-edit-class") == "table_cell":
            continue
        if text.attrib.get("font-family") == "HWTArtz":
            continue
        tspans = text.findall(f"{{{SVG_NS}}}tspan")
        if not tspans:
            continue
        convertible = [tspan for tspan in tspans if len(tspan.attrib.get("x", "").split()) > 1 and text_value(tspan).strip()]
        if not convertible:
            continue
        parent = parents.get(text)
        if parent is None:
            continue
        insert_at = list(parent).index(text)
        parent.remove(text)
        for tspan in tspans:
            xs = tspan.attrib.get("x", "").split()
            if not xs:
                continue
            for segment, segment_x in split_positioned_tspan_text(text_value(tspan), xs):
                value = normalize_editable_line_text(segment)
                if not value:
                    continue
                attrs = {key: val for key, val in text.attrib.items() if key not in {"id", "x", "y"}}
                if attrs.get("font-family") in family_map:
                    attrs["font-family"] = family_map[attrs["font-family"]]
                elif attrs.get("font-family", "").startswith("Minion3"):
                    attrs["font-family"] = "Times New Roman"
                attrs["id"] = f"page{page:03d}_editable_line_{line_counter:03d}"
                attrs["data-pdfrejuvenator-calibration"] = "line_level_editable_text"
                attrs[f"{{{XML_NS}}}space"] = "preserve"
                attrs["x"] = segment_x
                if "y" in tspan.attrib:
                    attrs["y"] = tspan.attrib["y"]
                attrs["text-anchor"] = "start"
                style = attrs.get("style", "")
                if "letter-spacing" not in style:
                    attrs["style"] = (style + ";" if style else "") + "letter-spacing:0px;text-rendering:geometricPrecision"
                new_text = ET.Element(f"{{{SVG_NS}}}text", attrs)
                new_text.text = value
                parent.insert(insert_at, new_text)
                converted.append(
                    {
                        "id": attrs["id"],
                        "text": value,
                        "font_family": attrs.get("font-family"),
                        "font_size": attrs.get("font-size"),
                        "x": attrs.get("x"),
                        "y": attrs.get("y"),
                    }
                )
                insert_at += 1
                line_counter += 1
    return converted


def convert_hwtartz_text_to_flow_lines(root: ET.Element, page: int) -> list[dict[str, Any]]:
    parents = parent_map(root)
    converted: list[dict[str, Any]] = []
    line_counter = 1
    for text in list(root.iter(f"{{{SVG_NS}}}text")):
        if text.attrib.get("data-pdfrejuvenator-calibration") == "hwtartz_header_flow_editable":
            continue
        if text.attrib.get("data-pdfrejuvenator-edit-class") == "table_cell":
            continue
        if text.attrib.get("font-family") != "HWTArtz":
            continue
        tspans = text.findall(f"{{{SVG_NS}}}tspan")
        if not tspans:
            continue
        convertible = [tspan for tspan in tspans if len(tspan.attrib.get("x", "").split()) > 1 and text_value(tspan).strip()]
        if not convertible:
            continue
        parent = parents.get(text)
        if parent is None:
            continue
        insert_at = list(parent).index(text)
        parent.remove(text)
        for tspan in tspans:
            xs = tspan.attrib.get("x", "").split()
            if not xs:
                continue
            for value, segment_x in split_positioned_tspan_text(text_value(tspan), xs, gap_threshold=18.0):
                if not value.strip():
                    continue
                attrs = {key: val for key, val in text.attrib.items() if key not in {"id", "x", "y"}}
                attrs["id"] = f"page{page:03d}_hwtartz_flow_{line_counter:03d}"
                attrs["data-pdfrejuvenator-calibration"] = "hwtartz_header_flow_editable"
                attrs[f"{{{XML_NS}}}space"] = "preserve"
                attrs["x"] = segment_x
                if "y" in tspan.attrib:
                    attrs["y"] = tspan.attrib["y"]
                attrs["text-anchor"] = "start"
                style = attrs.get("style", "")
                if "letter-spacing" not in style:
                    attrs["style"] = (style + ";" if style else "") + "letter-spacing:0px;text-rendering:geometricPrecision"
                new_text = ET.Element(f"{{{SVG_NS}}}text", attrs)
                new_text.text = value
                parent.insert(insert_at, new_text)
                converted.append(
                    {
                        "id": attrs["id"],
                        "text": value,
                        "font_family": attrs.get("font-family"),
                        "font_size": attrs.get("font-size"),
                        "x": attrs.get("x"),
                        "y": attrs.get("y"),
                    }
                )
                insert_at += 1
                line_counter += 1
    return converted


def copy_reference_hwtartz_font(page: int, fonts_dir: Path) -> str | None:
    source = REFERENCE_HEADER_CALIBRATION_ROOT / "fonts" / f"PDFRejuvenatorHWTArtzP{page:03d}.otf"
    if not source.exists():
        return None
    target = fonts_dir / source.name
    shutil.copy2(source, target)
    return source.stem


def collect_pdf_hwtartz_advances(source_pdf: Path, page: int) -> dict[str, list[float]]:
    observed: dict[str, list[float]] = {}
    with fitz.open(source_pdf) as doc:
        raw = doc[page - 1].get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("font") != "HWTArtz":
                    continue
                size = float(span.get("size") or 0.0)
                chars = span.get("chars", [])
                if size <= 0 or len(chars) <= 1:
                    continue
                for idx, char in enumerate(chars[:-1]):
                    value = char.get("c", "")
                    current = char.get("origin", [None, None])[0]
                    nxt = chars[idx + 1].get("origin", [None, None])[0]
                    if not value or current is None or nxt is None:
                        continue
                    advance = (float(nxt) - float(current)) / size
                    if advance > 0:
                        observed.setdefault(value, []).append(advance)
    return observed


def collect_pdf_hwtartz_widths(source_pdf: Path, page: int) -> dict[str, float]:
    widths: dict[str, float] = {}
    with fitz.open(source_pdf) as doc:
        data = doc[page - 1].get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("font") == "HWTArtz"]
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            x0 = min(float(span["bbox"][0]) for span in spans)
            x1 = max(float(span["bbox"][2]) for span in spans)
            widths[text] = x1 - x0
    return widths


def build_pdf_hwtartz_font(source_pdf: Path, page: int, fonts_dir: Path) -> str | None:
    source_font = ROOT / "outputs" / "pdfrejuvenator_calibration" / "fonts" / "pdf_extracted" / "usable" / "HWTArtz.otf"
    if not source_font.exists():
        return copy_reference_hwtartz_font(page, fonts_dir)
    observed = collect_pdf_hwtartz_advances(source_pdf, page)
    if not observed:
        return copy_reference_hwtartz_font(page, fonts_dir)
    family = f"PDFRejuvenatorHWTArtzP{page:03d}"
    make_calibrated_font(source_font, fonts_dir / f"{family}.otf", family, observed)
    return family


def apply_hwtartz_text_lengths(root: ET.Element, source_pdf: Path, page: int) -> list[dict[str, Any]]:
    widths = collect_pdf_hwtartz_widths(source_pdf, page)
    records: list[dict[str, Any]] = []
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "hwtartz_header_flow_editable":
            continue
        value = text_value(text).strip()
        target = widths.get(value)
        if not target:
            continue
        text.attrib["textLength"] = f"{target:.3f}".rstrip("0").rstrip(".")
        text.attrib["lengthAdjust"] = "spacingAndGlyphs"
        records.append({"id": text.attrib.get("id", ""), "text": value, "target_width": round(target, 3)})
    return records


def query_svg_bounds(inkscape: Path, svg: Path) -> dict[str, dict[str, float]]:
    proc = None
    for attempt in range(1, 4):
        proc = subprocess.run(
            [str(inkscape), str(svg), "--query-all"],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if proc.returncode == 0:
            break
        if attempt < 3:
            time.sleep(2 * attempt)
    assert proc is not None
    if proc.returncode != 0:
        raise RuntimeError(f"Inkscape query failed for {svg}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    bounds: dict[str, dict[str, float]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split(",")
        if len(parts) != 5:
            continue
        try:
            bounds[parts[0]] = {
                "x": float(parts[1]),
                "y": float(parts[2]),
                "width": float(parts[3]),
                "height": float(parts[4]),
            }
        except ValueError:
            continue
    return bounds


def apply_hwtartz_width_scales(root: ET.Element, queried_bounds: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "hwtartz_header_flow_editable":
            continue
        text_length = text.attrib.get("textLength")
        if not text_length:
            continue
        bounds = queried_bounds.get(text.attrib.get("id", ""))
        if not bounds or bounds["width"] <= 0:
            continue
        target_width = float(text_length)
        scale_x = target_width / bounds["width"]
        if abs(scale_x - 1.0) < 0.001:
            continue
        x = float(str(text.attrib.get("x", "0")).split()[0])
        translate_x = x * (1.0 - scale_x)
        text.attrib["transform"] = f"matrix({scale_x:.6f} 0 0 1 {translate_x:.6f} 792)"
        text.attrib["data-pdfrejuvenator-header-scale-x"] = f"{scale_x:.6f}"
        records.append(
            {
                "id": text.attrib.get("id", ""),
                "text": text_value(text).strip(),
                "target_width": round(target_width, 3),
                "queried_width_before_scale": round(bounds["width"], 3),
                "scale_x": round(scale_x, 6),
            }
        )
    return records


def collect_pdf_span_widths(source_pdf: Path, page: int) -> list[dict[str, Any]]:
    spans_out: list[dict[str, Any]] = []
    with fitz.open(source_pdf) as doc:
        data = doc[page - 1].get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            for span_idx, span in enumerate(spans):
                text = span.get("text", "")
                stripped = text.strip()
                if not stripped:
                    continue
                x0, y0, x1, y1 = [float(value) for value in span["bbox"]]
                next_x = None
                for next_span in spans[span_idx + 1 :]:
                    if next_span.get("text", "").strip():
                        next_x = float(next_span["bbox"][0])
                        break
                width = (next_x - x0) if next_x is not None and next_x > x0 else (x1 - x0)
                spans_out.append(
                    {
                        "text": stripped,
                        "raw_text": text,
                        "font": span.get("font", ""),
                        "size": float(span.get("size") or 0.0),
                        "x": x0,
                        "y": y0,
                        "width": width,
                        "ink_width": x1 - x0,
                    }
                )
    return spans_out


def apply_pdf_span_text_lengths(root: ET.Element, source_pdf: Path, page: int) -> list[dict[str, Any]]:
    spans = collect_pdf_span_widths(source_pdf, page)
    used: set[int] = set()
    records: list[dict[str, Any]] = []
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "line_level_editable_text":
            continue
        value = text_value(text).strip()
        if not value:
            continue
        if re.fullmatch(r"(?:\d{1,3}|[A-Za-z])\.", value) or value in {"•", "●", "-"}:
            continue
        family = text.attrib.get("font-family", "")
        try:
            x = float(str(text.attrib.get("x", "")).split()[0])
        except (ValueError, IndexError):
            continue
        best_idx = None
        best_score = 999999.0
        for idx, span in enumerate(spans):
            if idx in used:
                continue
            if span["text"] != value:
                continue
            score = abs(span["x"] - x)
            if score < best_score:
                best_score = score
                best_idx = idx
        if best_idx is None or best_score > 6.0:
            continue
        span = spans[best_idx]
        used.add(best_idx)
        text.attrib["textLength"] = f"{span['width']:.3f}".rstrip("0").rstrip(".")
        if "BlambotCasual" in family or span["font"] == "BlambotCasual":
            text.attrib["lengthAdjust"] = "spacing"
            strategy = "source_width_spacing_only_for_editable_casual_table_text"
        else:
            text.attrib["lengthAdjust"] = "spacingAndGlyphs"
            strategy = "source_width_spacing_and_glyphs"
        records.append(
            {
                "id": text.attrib.get("id", ""),
                "text": value,
                "target_width": round(span["width"], 3),
                "source_font": span["font"],
                "strategy": strategy,
            }
        )
    return records


def group_line_text_into_paragraphs(root: ET.Element, page: int) -> list[dict[str, Any]]:
    if page in PARAGRAPH_GROUP_SKIP_PAGES:
        return []
    parents = parent_map(root)
    line_items: list[dict[str, Any]] = []
    for element in list(root.iter(f"{{{SVG_NS}}}text")):
        if element.attrib.get("data-pdfrejuvenator-calibration") != "line_level_editable_text":
            continue
        value = text_value(element)
        if not value.strip():
            continue
        try:
            x = float(str(element.attrib.get("x", "")).split()[0])
            y = float(str(element.attrib.get("y", "")).split()[0])
        except (ValueError, IndexError):
            continue
        screen_y = PAGE_HEIGHT + y if element.attrib.get("transform", "").startswith("matrix") else y
        if screen_y < 30:
            continue
        parent = parents.get(element)
        if parent is None:
            continue
        line_items.append({"element": element, "parent": parent, "x": x, "y": y, "screen_y": screen_y, "text": value})
    if not line_items:
        return []

    containers: dict[ET.Element, list[dict[str, Any]]] = {}
    for item in line_items:
        containers.setdefault(item["parent"], []).append(item)

    paragraph_records: list[dict[str, Any]] = []
    paragraph_counter = 1
    for parent, items in containers.items():
        items = sorted(items, key=lambda item: (0 if item["x"] < 300 else 1, item["screen_y"], item["x"]))
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        previous_y: float | None = None
        previous_column: int | None = None
        for item in items:
            column = 0 if item["x"] < 300 else 1
            same_line = previous_y is not None and abs(item["screen_y"] - previous_y) < 1.0 and column == previous_column
            new_paragraph = False
            if not current:
                new_paragraph = True
            elif previous_column != column:
                new_paragraph = True
            elif previous_y is not None and not same_line and item["screen_y"] - previous_y > 13.2:
                new_paragraph = True
            elif previous_y is not None and not same_line and item["x"] in {45.0, 325.8}:
                new_paragraph = True
            if new_paragraph:
                if current:
                    groups.append(current)
                current = [item]
            else:
                current.append(item)
            previous_y = item["screen_y"]
            previous_column = column
        if current:
            groups.append(current)

        groups_to_convert = [group for group in groups if not group_should_remain_line_level(group)]
        if not groups_to_convert:
            continue
        items_to_convert = [item for group in groups_to_convert for item in group]
        first_index = min(list(parent).index(item["element"]) for item in items_to_convert)
        for item in items_to_convert:
            if item["element"] in list(parent):
                parent.remove(item["element"])
        insert_at = first_index
        for group in groups_to_convert:
            attrs = {
                "id": f"page{page:03d}_editable_paragraph_{paragraph_counter:03d}",
                "data-pdfrejuvenator-calibration": "paragraph_editable_text",
                f"{{{XML_NS}}}space": "preserve",
                "transform": "matrix(1 0 -0 1 0 792)",
                "style": "letter-spacing:0px;text-rendering:geometricPrecision",
            }
            paragraph = ET.Element(f"{{{SVG_NS}}}text", attrs)
            previous_line_y: float | None = None
            previous_item: dict[str, Any] | None = None
            for item in sorted(group, key=lambda entry: (entry["screen_y"], entry["x"])):
                element = item["element"]
                tspan_attrs = {
                    key: value
                    for key, value in element.attrib.items()
                    if key
                    in {
                        "x",
                        "y",
                        "font-family",
                        "font-size",
                        "font-weight",
                        "font-style",
                        "fill",
                        "textLength",
                        "lengthAdjust",
                    }
                }
                same_line_as_previous = previous_line_y is not None and abs(item["screen_y"] - previous_line_y) < 1.0
                previous_text = text_value(previous_item["element"]).strip() if previous_item is not None else ""
                current_text = item["text"].strip()
                keep_absolute_column = same_line_as_previous and (
                    previous_text in {"IQ", "ME", "MA", "PS", "PP", "PE", "PB", "Spd"}
                    or (item["x"] > 250.0 and re.fullmatch(r"[\dIVXLCDMivxlcdm]+[.)]?", current_text or ""))
                )
                if same_line_as_previous and not keep_absolute_column:
                    tspan_attrs.pop("x", None)
                    tspan_attrs.pop("y", None)
                else:
                    previous_line_y = item["screen_y"]
                tspan_attrs[f"{{{XML_NS}}}space"] = "preserve"
                tspan = ET.SubElement(paragraph, f"{{{SVG_NS}}}tspan", tspan_attrs)
                span_text = item["text"]
                if (
                    same_line_as_previous
                    and not keep_absolute_column
                    and previous_text
                    and not previous_text.endswith((" ", "/", "("))
                    and not current_text.startswith((",", ".", ")", ";", ":"))
                ):
                    span_text = " " + span_text.lstrip()
                tspan.text = span_text
                previous_item = item
            parent.insert(insert_at, paragraph)
            paragraph_records.append(
                {
                    "id": attrs["id"],
                    "text_sample": " ".join(text_value(item["element"]).strip() for item in group)[:120],
                    "span_count": len(group),
                    "first_x": group[0]["x"],
                    "first_screen_y": round(group[0]["screen_y"], 3),
                }
            )
            insert_at += 1
            paragraph_counter += 1
    return paragraph_records


def build_inkscape_flow_text_variant(source_svg: Path, output_svg: Path) -> dict[str, Any]:
    tree = ET.parse(source_svg)
    root = tree.getroot()
    parents = parent_map(root)
    converted = []
    for text in list(root.iter(f"{{{SVG_NS}}}text")):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "paragraph_editable_text":
            continue
        tspans = text.findall(f"{{{SVG_NS}}}tspan")
        if not tspans:
            continue
        try:
            first_x = float(tspans[0].attrib.get("x", "0"))
            first_y = float(tspans[0].attrib.get("y", "0"))
        except ValueError:
            continue
        lines: list[str] = []
        for tspan in tspans:
            value = text_value(tspan).strip()
            if value:
                lines.append(value)
        if not lines:
            continue
        screen_y = PAGE_HEIGHT + first_y
        column_width = 260.0 if first_x < 300 else 260.0
        height = max(20.0, len(lines) * 12.5 + 4.0)
        parent = parents.get(text)
        if parent is None:
            continue
        index = list(parent).index(text)
        parent.remove(text)
        flow = ET.Element(
            f"{{{SVG_NS}}}flowRoot",
            {
                "id": text.attrib.get("id", "") + "_flowroot",
                "data-pdfrejuvenator-calibration": "paragraph_flow_editable_text",
                f"{{{XML_NS}}}space": "preserve",
                "font-family": "Times New Roman",
                "font-size": "10",
                "style": "line-height:1.2;letter-spacing:0px;text-rendering:geometricPrecision",
            },
        )
        region = ET.SubElement(flow, f"{{{SVG_NS}}}flowRegion")
        ET.SubElement(
            region,
            f"{{{SVG_NS}}}rect",
            {
                "x": f"{first_x:.3f}".rstrip("0").rstrip("."),
                "y": f"{screen_y - 9:.3f}".rstrip("0").rstrip("."),
                "width": f"{column_width:.3f}".rstrip("0").rstrip("."),
                "height": f"{height:.3f}".rstrip("0").rstrip("."),
            },
        )
        para = ET.SubElement(flow, f"{{{SVG_NS}}}flowPara")
        para.text = " ".join(lines)
        parent.insert(index, flow)
        converted.append(
            {
                "id": text.attrib.get("id", ""),
                "flowroot_id": flow.attrib["id"],
                "line_count": len(lines),
                "rect": [round(first_x, 3), round(screen_y - 9, 3), round(column_width, 3), round(height, 3)],
            }
        )
    if converted:
        output_svg.parent.mkdir(parents=True, exist_ok=True)
        tree.write(output_svg, encoding="utf-8", xml_declaration=True)
    else:
        shutil.copy2(source_svg, output_svg)
    return {"flow_svg": str(output_svg), "converted_paragraph_count": len(converted), "converted_sample": converted[:12]}


def build_source_line_preserving_paragraph_variant(source_svg: Path, output_svg: Path) -> dict[str, Any]:
    tree = ET.parse(source_svg)
    root = tree.getroot()
    converted = []
    preserved_text_length_count = 0
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "paragraph_editable_text":
            continue
        tspans = text.findall(f"{{{SVG_NS}}}tspan")
        if not tspans:
            continue
        for tspan in tspans:
            if tspan.attrib.get("textLength"):
                preserved_text_length_count += 1
                tspan.attrib.setdefault("lengthAdjust", "spacingAndGlyphs")
        text.attrib["data-pdfrejuvenator-calibration"] = "paragraph_source_line_preserving_text"
        text.attrib["data-pdfrejuvenator-paragraph-edit-mode"] = "source_line_preserving"
        converted.append(
            {
                "id": text.attrib.get("id", ""),
                "span_count": len(tspans),
                "text_sample": text_value(text).strip()[:120],
            }
        )
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_svg, encoding="utf-8", xml_declaration=True)
    return {
        "source_line_svg": str(output_svg),
        "converted_paragraph_count": len(converted),
        "preserved_text_length_count": preserved_text_length_count,
        "converted_sample": converted[:12],
    }


def first_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(str(value).split()[0])
    except (IndexError, ValueError):
        return default


def split_paragraph_lines(text: ET.Element) -> list[list[ET.Element]]:
    lines: list[list[ET.Element]] = []
    current: list[ET.Element] = []
    previous_y: str | None = None
    for tspan in text.findall(f"{{{SVG_NS}}}tspan"):
        if not text_value(tspan).strip():
            continue
        y = tspan.attrib.get("y")
        if y and previous_y is not None and y != previous_y and current:
            lines.append(current)
            current = []
        current.append(tspan)
        if y:
            previous_y = y
    if current:
        lines.append(current)
    return lines


def has_alignment_sensitive_columns(lines: list[list[ET.Element]]) -> bool:
    for line in lines:
        absolute_xs = [tspan.attrib.get("x") for tspan in line if tspan.attrib.get("x")]
        if len(set(absolute_xs)) > 1:
            return True
    return False


def estimated_paragraph_right_edge(lines: list[list[ET.Element]]) -> float:
    right_edge = 0.0
    for line in lines:
        if not line:
            continue
        line_x = first_float(line[0].attrib.get("x"))
        line_right = line_x
        for tspan in line:
            text = re.sub(r"\s+", " ", text_value(tspan)).strip()
            if not text:
                continue
            font_size = first_float(tspan.attrib.get("font-size"), 10.0)
            tspan_x = first_float(tspan.attrib.get("x"), line_right)
            # Conservative width estimate for detecting full-page prose. The
            # exact width is later handled by Inkscape wrapping/rendering.
            line_right = max(line_right, tspan_x + len(text) * font_size * 0.50)
        right_edge = max(right_edge, line_right)
    return right_edge


def estimated_line_edges(line: list[ET.Element]) -> tuple[float, float]:
    if not line:
        return (0.0, 0.0)
    left = first_float(line[0].attrib.get("x"))
    right = left
    for tspan in line:
        text = re.sub(r"\s+", " ", text_value(tspan)).strip()
        if not text:
            continue
        font_size = first_float(tspan.attrib.get("font-size"), 10.0)
        x = first_float(tspan.attrib.get("x"), right)
        target_width = first_float(tspan.attrib.get("textLength"), 0.0)
        if target_width > 0:
            right = max(right, x + target_width)
        else:
            right = max(right, x + len(text) * font_size * 0.50)
    return (left, right)


def source_column_text_align(lines: list[list[ET.Element]]) -> tuple[str, dict[str, Any]]:
    edges = [estimated_line_edges(line) for line in lines if line]
    if len(edges) < 3:
        return ("start", {"reason": "too_few_lines"})
    lefts = [edge[0] for edge in edges]
    rights = [edge[1] for edge in edges]
    widths = [right - left for left, right in edges]
    substantial = [width for width in widths if width >= 80.0]
    if len(substantial) < 3:
        return ("start", {"reason": "too_few_substantial_lines"})
    left_spread = max(lefts) - min(lefts)
    right_spread = max(rights) - min(rights)
    sorted_widths = sorted(substantial)
    median_width = sorted_widths[len(sorted_widths) // 2]
    near_full = sum(1 for width in substantial if width >= median_width * 0.86)
    if right_spread <= 11.0 and left_spread >= 10.0:
        return (
            "end",
            {
                "reason": "stable_right_edge_variable_left_edge",
                "left_spread": round(left_spread, 3),
                "right_spread": round(right_spread, 3),
                "line_count": len(edges),
            },
        )
    if near_full >= max(3, int(len(substantial) * 0.58)) and right_spread <= 26.0:
        return (
            "justify",
            {
                "reason": "stable_column_width_full_lines",
                "right_spread": round(right_spread, 3),
                "near_full_lines": near_full,
                "substantial_lines": len(substantial),
                "median_width": round(median_width, 3),
            },
        )
    return (
        "start",
        {
            "reason": "ragged_or_insufficient_alignment_signal",
            "left_spread": round(left_spread, 3),
            "right_spread": round(right_spread, 3),
            "near_full_lines": near_full,
            "substantial_lines": len(substantial),
        },
    )


def line_item_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("text", "")).split())


def group_should_remain_line_level(group: list[dict[str, Any]]) -> bool:
    texts = [line_item_text(item) for item in group if line_item_text(item)]
    if len(group) >= 2:
        y_values = [float(item["screen_y"]) for item in group]
        x_values = [float(item["x"]) for item in group]
        same_visual_line = max(y_values) - min(y_values) < 1.1
        first_text = texts[0] if texts else ""
        table_like_first_cell = (
            re.fullmatch(r"(?:\d{1,3}-\d{1,3}|[A-Za-z]+)", first_text)
            or first_text.lower() in {"percentile", "description", "penalties", "roll", "result"}
        )
        if same_visual_line and max(x_values) - min(x_values) > 42.0 and table_like_first_cell:
            return True
    if len(group) < 4:
        return False
    if len(texts) < 4:
        return False
    short_count = sum(1 for text in texts if len(text) <= 42)
    numeric_lead_count = sum(1 for text in texts if re.match(r"^\s*(?:\d{1,3}(?:[-–]\d{1,3}|-\d{2}|[.,)]|$)|[IVXLCDM]+\b)", text))
    table_label_count = sum(1 for text in texts if re.search(r"\b(?:Table|Cost|Bonus|Range|Duration|Damage|Weight|Length|Size Level)\b", text))
    return (
        short_count / len(texts) >= 0.65
        or numeric_lead_count >= 3
        or (table_label_count >= 2 and short_count / len(texts) >= 0.45)
    )


LINE_PRESERVING_BOUNDED_PAGES = {1, 21, 55, 75, 272}
PARAGRAPH_GROUP_SKIP_PAGES = set(range(1, 273))


def should_preserve_source_line_breaks(page: int, lines: list[list[ET.Element]]) -> bool:
    if page in LINE_PRESERVING_BOUNDED_PAGES:
        return True
    values = [
        " ".join(text_value(tspan).strip() for tspan in line if text_value(tspan).strip())
        for line in lines
    ]
    values = [value for value in values if value]
    if len(values) >= 2:
        short_lines = sum(1 for value in values if len(value) <= 72)
        animal_value_rows = sum(1 for value in values if re.search(r"\s[—-]\s", value) and len(value) <= 92)
        label_rows = sum(1 for value in values if re.search(r":\s*$", value))
        bullet_rows = sum(1 for value in values if value.lstrip().startswith(("•", "●", "-")))
        if animal_value_rows >= 2:
            return True
        if bullet_rows >= 2:
            return True
        if label_rows >= 1 and short_lines / max(1, len(values)) >= 0.5:
            return True
        if len(values) <= 5 and short_lines == len(values) and any(re.search(r":|[—-]", value) for value in values):
            return True
    if len(lines) >= 8:
        short_lines = 0
        label_lines = 0
        for value in values:
            if len(value) <= 42:
                short_lines += 1
            if re.search(r":\s*$|^\s*(Bio-E Cost|Range|Duration|Saving Throw|Alignment|Attributes|Skills|Weapons|Armor)\b", value):
                label_lines += 1
        if short_lines / max(1, len(lines)) >= 0.55 or label_lines >= 2:
            return True
    return False


def build_inkscape_bounded_textbox_variant(source_svg: Path, output_svg: Path, page: int) -> dict[str, Any]:
    tree = ET.parse(source_svg)
    root = tree.getroot()
    parents = parent_map(root)
    defs = root.find(f"{{{SVG_NS}}}defs")
    if defs is None:
        defs = ET.Element(f"{{{SVG_NS}}}defs")
        root.insert(0, defs)
    converted = []
    skipped = []
    for text in list(root.iter(f"{{{SVG_NS}}}text")):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "paragraph_editable_text":
            continue
        lines = split_paragraph_lines(text)
        if len(lines) < 2:
            skipped.append({"id": text.attrib.get("id", ""), "reason": "single_line"})
            continue
        if has_alignment_sensitive_columns(lines):
            skipped.append({"id": text.attrib.get("id", ""), "reason": "alignment_sensitive_columns"})
            continue
        parent = parents.get(text)
        if parent is None:
            continue
        first = lines[0][0]
        line_starts = [first_float(line[0].attrib.get("x")) for line in lines if line and line[0].attrib.get("x")]
        if not line_starts:
            continue
        left_edge_variants = {round(value, 1) for value in line_starts}
        if len(left_edge_variants) >= 3 and (max(left_edge_variants) - min(left_edge_variants)) > 18:
            skipped.append({"id": text.attrib.get("id", ""), "reason": "irregular_left_edge_source_wrap"})
            continue
        box_x = min(line_starts)
        first_x = line_starts[0]
        first_y = first_float(first.attrib.get("y"))
        first_screen_y = PAGE_HEIGHT + first_y if text.attrib.get("transform", "").startswith("matrix") else first_y
        source_font_size = first_float(first.attrib.get("font-size"), 10.0)
        font_size = source_font_size
        font_family = first.attrib.get("font-family", "Times New Roman")
        source_text_align, source_text_align_evidence = source_column_text_align(lines)
        line_height_ratio = 1.2
        line_height = max(font_size * line_height_ratio, 10.4)
        box_y = first_screen_y - font_size * 0.94
        estimated_right = estimated_paragraph_right_edge(lines)
        if box_x < 300 and estimated_right > 470:
            box_width = max(420.0, min(552.0 - box_x, estimated_right - box_x + 6.0))
        elif box_x < 300:
            box_width = min(270.0, max(248.0, 306.0 - box_x))
        else:
            box_width = min(270.0, max(235.0, 589.0 - box_x))
        box_height = max(24.0, len(lines) * line_height + 8.0)
        rect_id = f"{text.attrib.get('id', 'paragraph')}_wrap_box"
        ET.SubElement(
            defs,
            f"{{{SVG_NS}}}rect",
            {
                "id": rect_id,
                "x": f"{box_x:.3f}".rstrip("0").rstrip("."),
                "y": f"{box_y:.3f}".rstrip("0").rstrip("."),
                "width": f"{box_width:.3f}".rstrip("0").rstrip("."),
                "height": f"{box_height:.3f}".rstrip("0").rstrip("."),
            },
        )
        replacement = ET.Element(
            f"{{{SVG_NS}}}text",
            {
                "id": text.attrib.get("id", "") + "_bounded",
                "data-pdfrejuvenator-calibration": "paragraph_bounded_wrap_text",
                "data-pdfrejuvenator-source-paragraph-id": text.attrib.get("id", ""),
                f"{{{XML_NS}}}space": "preserve",
                "style": (
                    f"font-family:'{font_family}';font-size:{font_size:g}px;line-height:{line_height_ratio:g};"
                    f"letter-spacing:0px;text-rendering:geometricPrecision;"
                    f"white-space:pre-wrap;shape-inside:url(#{rect_id});display:inline;"
                    f"text-align:{source_text_align};text-indent:0px"
                ),
            },
        )
        first_line_indent = max(0.0, first_x - box_x)
        leading_indent_spaces = " " * max(0, int(round(first_line_indent / max(1.0, font_size * 0.32))))
        preserve_source_breaks = should_preserve_source_line_breaks(page, lines)
        pending_space = False
        first_written_span = True
        for line_index, line in enumerate(lines):
            if preserve_source_breaks and line_index > 0:
                line_break = ET.SubElement(replacement, f"{{{SVG_NS}}}tspan", {f"{{{XML_NS}}}space": "preserve"})
                line_break.text = "\n"
                pending_space = False
            for tspan in line:
                value = re.sub(r"\s+", " ", text_value(tspan)).strip()
                if not value:
                    continue
                attrs = {f"{{{XML_NS}}}space": "preserve"}
                style_parts = []
                if tspan.attrib.get("font-weight") == "bold":
                    style_parts.append("font-weight:bold")
                if tspan.attrib.get("font-style") == "italic":
                    style_parts.append("font-style:italic")
                if tspan.attrib.get("fill"):
                    style_parts.append(f"fill:{tspan.attrib['fill']}")
                if style_parts:
                    attrs["style"] = ";".join(style_parts)
                child = ET.SubElement(replacement, f"{{{SVG_NS}}}tspan", attrs)
                indent = leading_indent_spaces if first_written_span else ""
                child.text = indent + (" " if pending_space else "") + value
                first_written_span = False
                pending_space = not value.endswith(("-", "/", "("))
        index = list(parent).index(text)
        parent.remove(text)
        parent.insert(index, replacement)
        converted.append(
            {
                "id": text.attrib.get("id", ""),
                "bounded_id": replacement.attrib["id"],
                "line_count": len(lines),
                "preserve_source_line_breaks": preserve_source_breaks,
                "source_font_size": round(source_font_size, 3),
                "effective_font_size": round(font_size, 3),
                "line_height_ratio": round(line_height_ratio, 3),
                "rect": [round(box_x, 3), round(box_y, 3), round(box_width, 3), round(box_height, 3)],
                "source_text_align": source_text_align,
                "source_text_align_evidence": source_text_align_evidence,
                "text_sample": text_value(replacement).strip()[:120],
            }
        )
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_svg, encoding="utf-8", xml_declaration=True)
    return {
        "bounded_textbox_svg": str(output_svg),
        "converted_paragraph_count": len(converted),
        "skipped_paragraph_count": len(skipped),
        "converted_sample": converted[:12],
        "skipped_sample": skipped[:12],
    }


def replace_tspans(text: ET.Element, spans: list[dict[str, str]]) -> None:
    for child in list(text):
        if child.tag == f"{{{SVG_NS}}}tspan":
            text.remove(child)
    text.text = None
    for span in spans:
        attrs = {key: value for key, value in span.items() if key != "text" and value}
        attrs[f"{{{XML_NS}}}space"] = "preserve"
        child = ET.SubElement(text, f"{{{SVG_NS}}}tspan", attrs)
        child.text = span["text"]


def normalize_compact_range_table_rows(root: ET.Element) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    parents = parent_map(root)
    penalty_pattern = re.compile(
        r"^(?P<description>.+?\.)(?P<penalty>\s*(?:Spd|PE|PP|PS|IQ|PB|Reduce|None\.|[-+]?\d|[1½]/?2|-\d+%).*)$"
    )
    for text in list(root.iter(f"{{{SVG_NS}}}text")):
        if text.attrib.get("data-pdfrejuvenator-calibration") == "line_level_editable_text":
            value = text_value(text).strip()
            try:
                x0 = first_float(text.attrib.get("x"))
            except (TypeError, ValueError):
                continue
            if x0 > 300 and value in {"Percentile", "Description", "Penalties"}:
                text.attrib["font-family"] = "Comic Sans MS"
                text.attrib["font-size"] = "7.4"
                text.attrib["font-weight"] = "bold"
                text.attrib["font-style"] = "italic"
                text.attrib.pop("textLength", None)
                text.attrib.pop("lengthAdjust", None)
                records.append({"id": text.attrib.get("id", ""), "kind": "line_range_table_header", "text": value})
                continue
            if not (x0 > 360 and x0 < 470):
                continue
            match = penalty_pattern.match(value)
            if not match:
                continue
            parent = parents.get(text)
            if parent is None:
                continue
            description = match.group("description").strip()
            penalty = match.group("penalty").strip()
            text.text = description
            text.attrib.pop("textLength", None)
            text.attrib.pop("lengthAdjust", None)
            penalty_attrs = dict(text.attrib)
            penalty_attrs["id"] = f"{text.attrib.get('id', 'line')}_penalty"
            penalty_attrs["x"] = f"{x0 + 136:.3f}".rstrip("0").rstrip(".")
            penalty_text = ET.Element(f"{{{SVG_NS}}}text", penalty_attrs)
            penalty_text.text = penalty
            parent.insert(list(parent).index(text) + 1, penalty_text)
            records.append(
                {
                    "id": text.attrib.get("id", ""),
                    "kind": "line_range_table_row",
                    "description": description[:80],
                    "penalty": penalty,
                }
            )
            continue
        if text.attrib.get("data-pdfrejuvenator-calibration") != "paragraph_editable_text":
            continue
        tspans = text.findall(f"{{{SVG_NS}}}tspan")
        if not tspans:
            continue
        first_value = text_value(tspans[0]).strip()
        try:
            x0 = first_float(tspans[0].attrib.get("x"))
            y0 = tspans[0].attrib.get("y", "")
        except (TypeError, ValueError):
            continue
        if x0 < 300:
            continue
        if first_value.lower() in {"percentile", "description", "penalties"}:
            replace_tspans(
                text,
                [
                    {"x": f"{x0:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Comic Sans MS", "font-size": "7.4", "font-weight": "bold", "font-style": "italic", "text": "Percentile"},
                    {"x": f"{x0 + 92:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Comic Sans MS", "font-size": "7.4", "font-weight": "bold", "font-style": "italic", "text": "Description"},
                    {"x": f"{x0 + 212:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Comic Sans MS", "font-size": "7.4", "font-weight": "bold", "font-style": "italic", "text": "Penalties"},
                ],
            )
            records.append({"id": text.attrib.get("id", ""), "kind": "range_table_header", "x": round(x0, 3)})
            continue
        if not re.fullmatch(r"\d{1,3}-\d{1,3}", first_value):
            continue
        rest = " ".join(text_value(tspan).strip() for tspan in tspans[1:] if text_value(tspan).strip())
        if not rest:
            continue
        match = penalty_pattern.match(rest)
        if not match:
            continue
        description = match.group("description").strip()
        penalty = match.group("penalty").strip()
        replace_tspans(
            text,
            [
                {"x": f"{x0:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Times New Roman", "font-size": "10", "text": first_value},
                {"x": f"{x0 + 54:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Times New Roman", "font-size": "10", "text": description},
                {"x": f"{x0 + 190:.3f}".rstrip("0").rstrip("."), "y": y0, "font-family": "Times New Roman", "font-size": "10", "text": penalty},
            ],
        )
        records.append(
            {
                "id": text.attrib.get("id", ""),
                "kind": "range_table_row",
                "range": first_value,
                "description": description[:80],
                "penalty": penalty,
            }
        )
    return records


def apply_page_calibrated_hwtartz(root: ET.Element, family: str | None) -> list[dict[str, Any]]:
    if not family:
        return []
    changed: list[dict[str, Any]] = []
    for text in root.iter(f"{{{SVG_NS}}}text"):
        if text.attrib.get("data-pdfrejuvenator-calibration") != "hwtartz_header_flow_editable":
            continue
        if text.attrib.get("font-family") == family:
            continue
        if text.attrib.get("font-family") != "HWTArtz":
            continue
        text.attrib["font-family"] = family
        changed.append(
            {
                "id": text.attrib.get("id", ""),
                "text": text_value(text).strip(),
                "font_family": family,
            }
        )
    return changed


def text_screen_position(element: ET.Element) -> tuple[float, float] | None:
    try:
        x = float(str(element.attrib.get("x", "")).split()[0])
        y = float(str(element.attrib.get("y", "")).split()[0])
    except (IndexError, ValueError):
        return None
    if element.attrib.get("transform", "").startswith("matrix"):
        y = PAGE_HEIGHT + y
    return x, y


def element_screen_positions(element: ET.Element) -> list[tuple[float, float]]:
    positions = []
    direct = text_screen_position(element)
    if direct is not None:
        positions.append(direct)
    transform = element.attrib.get("transform", "")
    for tspan in element.findall(f"{{{SVG_NS}}}tspan"):
        try:
            x = float(str(tspan.attrib.get("x", "")).split()[0])
            y = float(str(tspan.attrib.get("y", "")).split()[0])
        except (IndexError, ValueError):
            continue
        if transform.startswith("matrix"):
            y = PAGE_HEIGHT + y
        positions.append((x, y))
    return positions


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def find_layer(root: ET.Element) -> ET.Element:
    layer = root.find(".//*[@id='single_editable_layer']")
    return layer if layer is not None else root


def add_rect(parent: ET.Element, x: float, y: float, width: float, height: float, fill: str) -> None:
    ET.SubElement(
        parent,
        f"{{{SVG_NS}}}rect",
        {
            "x": f"{x:.3f}".rstrip("0").rstrip("."),
            "y": f"{y:.3f}".rstrip("0").rstrip("."),
            "width": f"{width:.3f}".rstrip("0").rstrip("."),
            "height": f"{height:.3f}".rstrip("0").rstrip("."),
            "fill": fill,
            "stroke": "none",
            "data-pdfrejuvenator-calibration": "chapter_table_background_repaint",
        },
    )


def add_text(
    parent: ET.Element,
    element_id: str,
    value: str,
    x: float,
    baseline_y: float,
    family: str,
    size: float,
    fill: str,
    weight: str = "normal",
    anchor: str = "middle",
    letter_spacing: float = 0.0,
    text_length: float | None = None,
    length_adjust: str = "spacingAndGlyphs",
) -> None:
    attrs = {
        "id": element_id,
        "data-pdfrejuvenator-calibration": "chapter_table_cell_editable_text",
        "data-pdfrejuvenator-edit-class": "table_cell",
        f"{{{XML_NS}}}space": "preserve",
        "transform": "matrix(1 0 -0 1 0 792)",
        "x": f"{x:.3f}".rstrip("0").rstrip("."),
        "y": f"{baseline_y - PAGE_HEIGHT:.3f}".rstrip("0").rstrip("."),
        "font-family": family,
        "font-size": f"{size:g}",
        "text-anchor": anchor,
        "style": f"letter-spacing:{letter_spacing:g}px;text-rendering:geometricPrecision",
    }
    if fill.lower() != "000000":
        attrs["fill"] = f"#{fill.lower()}"
    if weight == "bold":
        attrs["font-weight"] = "bold"
    if text_length is not None:
        attrs["textLength"] = f"{text_length:.3f}".rstrip("0").rstrip(".")
        attrs["lengthAdjust"] = length_adjust
    element = ET.SubElement(parent, f"{{{SVG_NS}}}text", attrs)
    element.text = value


def add_multiline_text(
    parent: ET.Element,
    element_id: str,
    lines: list[str],
    x: float,
    baseline_y: float,
    family: str,
    size: float,
    fill: str,
    weight: str = "normal",
    line_height: float = 11.0,
) -> None:
    attrs = {
        "id": element_id,
        "data-pdfrejuvenator-calibration": "chapter_table_cell_editable_text",
        "data-pdfrejuvenator-edit-class": "table_cell",
        f"{{{XML_NS}}}space": "preserve",
        "transform": "matrix(1 0 -0 1 0 792)",
        "x": f"{x:.3f}".rstrip("0").rstrip("."),
        "y": f"{baseline_y - PAGE_HEIGHT:.3f}".rstrip("0").rstrip("."),
        "font-family": family,
        "font-size": f"{size:g}",
        "text-anchor": "start",
        "style": "letter-spacing:0px;text-rendering:geometricPrecision",
    }
    if fill.lower() != "000000":
        attrs["fill"] = f"#{fill.lower()}"
    if weight == "bold":
        attrs["font-weight"] = "bold"
    element = ET.SubElement(parent, f"{{{SVG_NS}}}text", attrs)
    for idx, line in enumerate(lines):
        tspan_attrs = {"x": attrs["x"]}
        if idx == 0:
            tspan_attrs["y"] = attrs["y"]
        else:
            tspan_attrs["dy"] = f"{line_height:g}"
        tspan = ET.SubElement(element, f"{{{SVG_NS}}}tspan", tspan_attrs)
        tspan.text = line


def estimate_text_width(value: str, size: float, family: str) -> float:
    factor = 0.56 if family == "Comic Sans MS" else 0.48
    width = 0.0
    for char in value:
        if char == " ":
            width += size * factor * 0.55
        elif char in "ilI1.,'":
            width += size * factor * 0.45
        elif char in "MW@#%":
            width += size * factor * 1.25
        else:
            width += size * factor
    return width


def edit_stable_start_x(x: float, value: str, size: float, family: str, visual_anchor: str) -> float:
    width = estimate_text_width(value, size, family)
    if visual_anchor == "middle":
        return x - width / 2
    if visual_anchor == "end":
        return x - width
    return x


def remove_svg_text_in_bbox(root: ET.Element, bbox: list[float]) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = bbox
    removed = []
    parents = parent_map(root)
    for element in list(root.iter(f"{{{SVG_NS}}}text")):
        positions = element_screen_positions(element)
        if not positions:
            continue
        inside = any(x0 - 8 <= x <= x1 + 8 and y0 - 8 <= y <= y1 + 8 for x, y in positions)
        if not inside:
            continue
        value = text_value(element).strip()
        if value.lower().endswith("table"):
            continue
        parent = parents.get(element)
        if parent is None:
            continue
        parent.remove(element)
        removed.append({"id": element.attrib.get("id"), "text": value, "positions": positions})
    return removed


def infer_geometry(table: dict[str, Any], rows: list[list[str]]) -> tuple[list[float], list[float]]:
    x0, y0, x1, y1 = table["bbox_points"]
    row_count = max(1, len(rows))
    col_count = max(1, max((len(row) for row in rows), default=1))
    cell_w = (x1 - x0) / col_count
    row_h = (y1 - y0) / row_count
    x_centers = [x0 + cell_w * (idx + 0.5) for idx in range(col_count)]
    baselines = [y0 + row_h * (idx + 0.72) for idx in range(row_count)]
    return x_centers, baselines


def infer_structured_attribute_table_geometry(table: dict[str, Any], rows: list[list[str]]) -> tuple[list[float], list[float], list[str]]:
    x0, y0, x1, y1 = table["bbox_points"]
    row_count = max(1, len(rows))
    row_h = (y1 - y0) / row_count
    # Page 12's attribute table uses uneven source PDF column starts. Using
    # equal-width centers makes the restored dark left column look misaligned.
    if max((len(row) for row in rows), default=0) == 8 and 315 <= x0 <= 318 and 575 <= x1 <= 577:
        x_positions = [318.8, 343.432, 381.772, 412.592, 450.482, 484.832, 519.182, 550.002]
        anchors = ["start"] * len(x_positions)
    else:
        x_positions, baselines = infer_geometry(table, rows)
        anchors = ["middle"] * len(x_positions)
        return x_positions, baselines, anchors
    baselines = [y0 + row_h * (idx + 0.72) for idx in range(row_count)]
    return x_positions, baselines, anchors


def infer_rulebook_stat_table_geometry(table: dict[str, Any], rows: list[list[str]]) -> tuple[list[float], list[float], list[str]]:
    x0, y0, x1, y1 = table["bbox_points"]
    row_count = max(1, len(rows))
    row_h = (y1 - y0) / row_count
    width = x1 - x0
    if table.get("classification") == "stat_table" and max((len(row) for row in rows), default=0) >= 8:
        x_positions = [x0 + 20.0, x0 + 46.0, x0 + 110.0, x0 + 142.0, x0 + 174.0, x0 + 204.0, x0 + 230.0, x0 + 247.0]
        anchors = ["middle", "start", "middle", "middle", "middle", "middle", "middle", "middle"]
    elif table.get("classification") == "height_weight_table" and max((len(row) for row in rows), default=0) >= 5:
        x_positions = [x0 + 36.0, x0 + width * 0.30, x0 + width * 0.55, x0 + width * 0.77, x0 + width * 0.95]
        anchors = ["middle"] * len(x_positions)
    else:
        return infer_geometry(table, rows) + (["middle"] * max(1, max((len(row) for row in rows), default=1)),)
    baselines = [y0 + row_h * (idx + 0.74) for idx in range(row_count)]
    return x_positions, baselines, anchors


def repaint_rulebook_stat_table(layer: ET.Element, table: dict[str, Any], rows: list[list[str]]) -> list[dict[str, Any]]:
    if table.get("classification") not in {"stat_table", "height_weight_table"} or not rows:
        return []
    x0, y0, x1, y1 = [float(value) for value in table["bbox_points"]]
    row_count = len(rows)
    row_h = (y1 - y0) / max(1, row_count)
    first_col_width = 43.2 if table.get("classification") == "height_weight_table" else 42.8
    records: list[dict[str, Any]] = []
    add_rect(layer, x0, y0, x1 - x0, y1 - y0, "#d0d1d2")
    records.append({"kind": "base", "rect": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)], "fill": "#d0d1d2"})
    add_rect(layer, x0, y0, x1 - x0, row_h + 0.2, "#444444")
    records.append({"kind": "header", "rect": [round(x0, 3), round(y0, 3), round(x1, 3), round(y0 + row_h, 3)], "fill": "#444444"})
    add_rect(layer, x0, y0, first_col_width, y1 - y0, "#444444")
    records.append({"kind": "first_column", "rect": [round(x0, 3), round(y0, 3), round(x0 + first_col_width, 3), round(y1, 3)], "fill": "#444444"})
    for row_idx in range(1, row_count):
        fill = "#dcddde" if row_idx % 2 == 1 else "#c4c6c8"
        y = y0 + row_idx * row_h
        add_rect(layer, x0 + first_col_width, y, x1 - x0 - first_col_width, row_h + 0.2, fill)
        records.append(
            {
                "kind": "stripe",
                "row": row_idx,
                "rect": [round(x0 + first_col_width, 3), round(y, 3), round(x1, 3), round(y + row_h, 3)],
                "fill": fill,
            }
        )
    return records


def repaint_table(layer: ET.Element, table: dict[str, Any], rows: list[list[str]]) -> None:
    x0, y0, x1, y1 = table["bbox_points"]
    row_count = max(1, len(rows))
    row_h = (y1 - y0) / row_count
    add_rect(layer, x0, y0, x1 - x0, y1 - y0, "#d4d4d4")
    for idx in range(row_count):
        fill = "#d8d8d8" if idx % 2 == 0 else "#c8c8c8"
        if idx == 0:
            fill = "#444444"
        add_rect(layer, x0, y0 + idx * row_h, x1 - x0, row_h + 0.2, fill)


def rgb_float_to_hex(rgb: Any) -> str:
    if not rgb or len(rgb) < 3:
        return "#ffffff"
    return "#" + "".join(f"{max(0, min(255, int(round(float(channel) * 255)))):02x}" for channel in rgb[:3])


def repaint_table_from_pdf_drawings(layer: ET.Element, source_pdf: Path, page: int, table: dict[str, Any]) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = [float(value) for value in table["bbox_points"]]
    records: list[dict[str, Any]] = []
    with fitz.open(source_pdf) as doc:
        drawings = doc[page - 1].get_drawings()
    for drawing in drawings:
        rect = drawing.get("rect")
        fill = drawing.get("fill")
        if rect is None or fill is None:
            continue
        rx0, ry0, rx1, ry1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
        overlap_x0 = max(x0, rx0)
        overlap_y0 = max(y0, ry0)
        overlap_x1 = min(x1, rx1)
        overlap_y1 = min(y1, ry1)
        if overlap_x1 <= overlap_x0 or overlap_y1 <= overlap_y0:
            continue
        hex_fill = rgb_float_to_hex(fill)
        add_rect(layer, overlap_x0, overlap_y0, overlap_x1 - overlap_x0, overlap_y1 - overlap_y0, hex_fill)
        records.append(
            {
                "rect": [round(overlap_x0, 3), round(overlap_y0, 3), round(overlap_x1, 3), round(overlap_y1, 3)],
                "fill": hex_fill,
            }
        )
    return records


def repaint_structured_table_row_stripes(layer: ET.Element, table: dict[str, Any], rows: list[list[str]]) -> list[dict[str, Any]]:
    if table.get("classification") != "structured_table" or not rows:
        return []
    x0, y0, x1, y1 = [float(value) for value in table["bbox_points"]]
    max_columns = max((len(row) for row in rows), default=0)
    if max_columns < 4:
        return []
    row_count = len(rows)
    row_h = (y1 - y0) / max(1, row_count)
    data_x0 = x0 + 18.72 if max_columns >= 8 and 315 <= x0 <= 318 else x0
    records = []
    for row_idx in range(1, row_count):
        fill = "#dcddde" if row_idx % 2 == 1 else "#c7c8ca"
        y = y0 + row_idx * row_h
        add_rect(layer, data_x0, y, x1 - data_x0, row_h + 0.2, fill)
        records.append(
            {
                "row": row_idx,
                "fill": fill,
                "rect": [round(data_x0, 3), round(y, 3), round(x1, 3), round(y + row_h, 3)],
            }
        )
    return records


def block_lines(block: dict[str, Any]) -> list[str]:
    lines = []
    for line in block.get("lines", []):
        text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
        if text:
            lines.append(text)
    return lines


def mask_equipment_text_zones(layer: ET.Element, table: dict[str, Any]) -> None:
    x0, y0, x1, y1 = table["bbox_points"]
    width = x1 - x0
    if width > 400:
        # Wide equipment tables use the middle of the row for weapon art.
        # Only cover the printed text lanes so the illustration corridor survives.
        add_rect(layer, x0 - 2, y0 - 2, 118, y1 - y0 + 4, "#ffffff")
        add_rect(layer, x0 + width * 0.49, y0 - 2, width * 0.53, y1 - y0 + 4, "#ffffff")
    else:
        add_rect(layer, x0 - 2, y0 - 2, width + 4, y1 - y0 + 4, "#ffffff")


def infer_equipment_geometry(table: dict[str, Any], rows: list[list[str]]) -> tuple[list[float], list[float], list[str]]:
    x0, y0, x1, y1 = table["bbox_points"]
    width = x1 - x0
    row_count = max(1, len(rows))
    row_h = (y1 - y0) / row_count
    col_count = max(1, max((len(row) for row in rows), default=1))
    if width > 400 and col_count == 6:
        x_positions = [
            x0 + 4,
            x0 + width * 0.54,
            x0 + width * 0.66,
            x0 + width * 0.79,
            x0 + width * 0.885,
            x0 + width * 0.965,
        ]
        anchors = ["start", "middle", "middle", "middle", "middle", "end"]
    elif col_count == 5:
        x_positions = [
            x0 + 4,
            x0 + width * 0.46,
            x0 + width * 0.68,
            x0 + width * 0.84,
            x1 - 4,
        ]
        anchors = ["start", "middle", "middle", "middle", "end"]
    else:
        cell_w = width / col_count
        x_positions = [x0 + cell_w * (idx + 0.5) for idx in range(col_count)]
        anchors = ["middle"] * col_count
    baselines = [y0 + row_h * (idx + 0.72) for idx in range(row_count)]
    return x_positions, baselines, anchors


def add_generic_table(layer: ET.Element, page: int, table_index: int, table: dict[str, Any], rows: list[list[str]]) -> list[dict[str, Any]]:
    if table["classification"] == "movement_table":
        return add_movement_table(layer, page, table_index, table, rows)
    if table["classification"] == "experience_awards_table":
        return add_experience_awards_table(layer, page, table_index, table)
    if table["classification"] == "experience_levels_table":
        return add_experience_levels_table(layer, page, table_index, table)
    if table["classification"] == "equipment_table":
        x_centers, baselines, anchors = infer_equipment_geometry(table, rows)
    elif table["classification"] == "structured_table":
        x_centers, baselines, anchors = infer_structured_attribute_table_geometry(table, rows)
    elif table["classification"] in {"stat_table", "height_weight_table"}:
        x_centers, baselines, anchors = infer_rulebook_stat_table_geometry(table, rows)
    else:
        x_centers, baselines = infer_geometry(table, rows)
        anchors = ["middle"] * len(x_centers)
    required_cols = max((len(row) for row in rows), default=0)
    if required_cols > len(x_centers):
        x0, y0, x1, y1 = table["bbox_points"]
        cell_w = (x1 - x0) / max(1, required_cols)
        x_centers = [x0 + cell_w * (idx + 0.5) for idx in range(required_cols)]
        anchors = ["middle"] * required_cols
    elif required_cols > len(anchors):
        anchors.extend(["middle"] * (required_cols - len(anchors)))
    records = []
    equipment_header_tokens = {
        "ancient weapons",
        "shield type",
        "ancient armor",
        "modern armor",
        "landcraft",
        "watercraft",
        "aircraft",
    }
    has_equipment_header = bool(rows and rows[0] and rows[0][0].strip().lower() in equipment_header_tokens)
    for row_idx, row in enumerate(rows):
        for col_idx, value in enumerate(row):
            value = value.strip()
            if not value:
                continue
            if table["classification"] == "equipment_table":
                header = row_idx == 0 and has_equipment_header
            else:
                header = row_idx == 0
            family = "HWTArtz" if table["classification"] == "equipment_table" and header else ("Comic Sans MS" if header else "Times New Roman")
            size = 7.0 if table["classification"] == "equipment_table" and header else (8.0 if header else 9.0)
            fill = "000000" if table["classification"] == "equipment_table" and header else ("FFFFFF" if header else "000000")
            weight = "bold" if header else "normal"
            if table["classification"] == "structured_table" and col_idx == 0:
                family = "Comic Sans MS"
                size = 8.0
                fill = "FFFFFF"
                weight = "bold"
            if table["classification"] in {"stat_table", "height_weight_table"} and (header or col_idx == 0):
                family = "Comic Sans MS"
                size = 8.0
                fill = "FFFFFF"
                weight = "bold"
            element_id = f"page{page:03d}_table{table_index:02d}_r{row_idx:02d}_c{col_idx:02d}"
            visual_anchor = anchors[col_idx]
            x = edit_stable_start_x(x_centers[col_idx], value, size, family, visual_anchor)
            add_text(layer, element_id, value, x, baselines[row_idx], family, size, fill, weight, "start")
            records.append(
                {
                    "id": element_id,
                    "table_id": table["table_id"],
                    "row": row_idx,
                    "column": col_idx,
                    "text": value,
                    "x": x,
                    "visual_anchor": visual_anchor,
                    "baseline_y": baselines[row_idx],
                }
            )
    return records


def add_experience_awards_table(layer: ET.Element, page: int, table_index: int, table: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    add_text(layer, f"page{page:03d}_table{table_index:02d}_r00_c00", "Experience Points", 41.4, 397.2, "Comic Sans MS", 7.2, "000000", "bold", "start", 0.0)
    add_text(layer, f"page{page:03d}_table{table_index:02d}_r00_c01", "Player Action", 151.1, 397.2, "Comic Sans MS", 7.2, "000000", "bold", "start", 0.0)
    records.extend(
        [
            {
                "id": f"page{page:03d}_table{table_index:02d}_r00_c00",
                "table_id": table["table_id"],
                "row": 0,
                "column": 0,
                "text": "Experience Points",
                "x": 41.4,
                "visual_anchor": "start",
                "baseline_y": 397.2,
            },
            {
                "id": f"page{page:03d}_table{table_index:02d}_r00_c01",
                "table_id": table["table_id"],
                "row": 0,
                "column": 1,
                "text": "Player Action",
                "x": 151.1,
                "visual_anchor": "start",
                "baseline_y": 397.2,
            },
        ]
    )
    for source_row_idx, detail in enumerate(table.get("row_details", []), 1):
        x0, y0, _x1, _y1 = [float(value) for value in detail["bbox"]]
        baseline = y0 + 9.4
        points = detail.get("points", "").strip()
        action_lines = [line.strip() for line in detail.get("action_lines", []) if line.strip()]
        points_id = f"page{page:03d}_table{table_index:02d}_r{source_row_idx:02d}_c00"
        action_id = f"page{page:03d}_table{table_index:02d}_r{source_row_idx:02d}_c01"
        add_text(layer, points_id, points, x0, baseline, "Comic Sans MS", 8.2, "000000", "bold", "start", 0.0)
        add_multiline_text(layer, action_id, action_lines, 91.5, baseline, "Times New Roman", 10.0, "000000", line_height=11.0)
        records.extend(
            [
                {
                    "id": points_id,
                    "table_id": table["table_id"],
                    "row": source_row_idx,
                    "column": 0,
                    "text": points,
                    "x": x0,
                    "visual_anchor": "start",
                    "baseline_y": baseline,
                },
                {
                    "id": action_id,
                    "table_id": table["table_id"],
                    "row": source_row_idx,
                    "column": 1,
                    "text": " ".join(action_lines),
                    "x": 91.5,
                    "visual_anchor": "start",
                    "baseline_y": baseline,
                },
            ]
        )
    return records


def add_experience_levels_table(layer: ET.Element, page: int, table_index: int, table: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    add_text(layer, f"page{page:03d}_table{table_index:02d}_r00_c00", "Experience Levels", 322.2, 573.1, "Comic Sans MS", 7.2, "000000", "bold", "start", 0.0)
    add_text(layer, f"page{page:03d}_table{table_index:02d}_r00_c01", "Experience Points", 430.0, 573.1, "Comic Sans MS", 7.2, "000000", "bold", "start", 0.0)
    records.extend(
        [
            {
                "id": f"page{page:03d}_table{table_index:02d}_r00_c00",
                "table_id": table["table_id"],
                "row": 0,
                "column": 0,
                "text": "Experience Levels",
                "x": 322.2,
                "visual_anchor": "start",
                "baseline_y": 573.1,
            },
            {
                "id": f"page{page:03d}_table{table_index:02d}_r00_c01",
                "table_id": table["table_id"],
                "row": 0,
                "column": 1,
                "text": "Experience Points",
                "x": 430.0,
                "visual_anchor": "start",
                "baseline_y": 573.1,
            },
        ]
    )
    for source_row_idx, detail in enumerate(table.get("row_details", []), 1):
        x0, y0, _x1, _y1 = [float(value) for value in detail["bbox"]]
        baseline = y0 + 9.4
        level = detail.get("level", "").strip()
        points = detail.get("points", "").strip()
        level_id = f"page{page:03d}_table{table_index:02d}_r{source_row_idx:02d}_c00"
        points_id = f"page{page:03d}_table{table_index:02d}_r{source_row_idx:02d}_c01"
        add_text(layer, level_id, level, x0, baseline, "Comic Sans MS", 8.2, "000000", "bold", "start", 0.0)
        add_text(layer, points_id, points, 430.0, baseline, "Times New Roman", 10.0, "000000", "normal", "start")
        records.extend(
            [
                {
                    "id": level_id,
                    "table_id": table["table_id"],
                    "row": source_row_idx,
                    "column": 0,
                    "text": level,
                    "x": x0,
                    "visual_anchor": "start",
                    "baseline_y": baseline,
                },
                {
                    "id": points_id,
                    "table_id": table["table_id"],
                    "row": source_row_idx,
                    "column": 1,
                    "text": points,
                    "x": 430.0,
                    "visual_anchor": "start",
                    "baseline_y": baseline,
                },
            ]
        )
    return records


def add_movement_table(layer: ET.Element, page: int, table_index: int, table: dict[str, Any], rows: list[list[str]]) -> list[dict[str, Any]]:
    x_positions_by_row = [
        [423.2, 462.3, 490.3, 518.9, 548.4],
        [318.8, 463.7, 494.7, 525.6, 556.6],
        [318.8, 465.6, 494.1, 525.1, 556.1],
        [318.8, 467.3],
        [318.8, 497.0],
        [318.8, 494.9],
    ]
    baselines = [687.7, 700.6, 713.6, 726.4, 739.4, 752.3]
    records = []
    for row_idx, row in enumerate(rows):
        for col_idx, value in enumerate(row):
            value = value.strip()
            if not value:
                continue
            x_positions = x_positions_by_row[min(row_idx, len(x_positions_by_row) - 1)]
            x = x_positions[min(col_idx, len(x_positions) - 1)]
            baseline = baselines[min(row_idx, len(baselines) - 1)]
            header_or_label = row_idx == 0 or col_idx == 0
            movement_label_or_header = header_or_label
            if movement_label_or_header:
                # The extracted Blambot casual face has collapsed advances in
                # Inkscape for movement table white labels/headers. Use a
                # stable editable casual fallback instead of forcing
                # textLength/tracking.
                family = "Comic Sans MS"
            else:
                family = "Times New Roman"
            if movement_label_or_header:
                size = 8.4
            else:
                size = 10.0 if row_idx <= 2 else 9.0
            fill = "FFFFFF" if header_or_label else "000000"
            weight = "bold" if movement_label_or_header else "normal"
            letter_spacing = 0.0
            text_length = None
            element_id = f"page{page:03d}_table{table_index:02d}_r{row_idx:02d}_c{col_idx:02d}"
            add_text(layer, element_id, value, x, baseline, family, size, fill, weight, "start", letter_spacing, text_length, "spacing")
            records.append(
                {
                    "id": element_id,
                    "table_id": table["table_id"],
                    "row": row_idx,
                    "column": col_idx,
                    "text": value,
                    "x": x,
                    "visual_anchor": "start",
                    "baseline_y": baseline,
                }
            )
    return records


def apply_page_specific_svg_fixes(root: ET.Element, page: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for element in root.iter(f"{{{SVG_NS}}}text"):
        if text_value(element).strip() not in {"●", "•"}:
            continue
        old_size = element.attrib.get("font-size", "")
        try:
            old_size_value = float(old_size)
        except ValueError:
            old_size_value = 0.0
        if old_size_value and old_size_value <= 7.1:
            continue
        element.attrib["font-size"] = "7"
        element.attrib["font-family"] = "Times New Roman"
        for tspan in element.iter(f"{{{SVG_NS}}}tspan"):
            tspan.attrib["font-size"] = "7"
            tspan.attrib["font-family"] = "Times New Roman"
        records.append({"page": page, "fix": "standalone_bullet_size", "id": element.attrib.get("id", ""), "old_size": old_size, "new_size": "7"})
    return records


def render_svg(inkscape: Path, svg: Path, png: Path, width: int, height: int) -> None:
    env = os.environ.copy()
    env.pop("FONTCONFIG_FILE", None)
    png.parent.mkdir(parents=True, exist_ok=True)
    attempts = []
    for attempt in range(1, 4):
        png.unlink(missing_ok=True)
        temp_export: Path | None = None
        temp_svg: Path | None = None
        export_png = png
        export_svg = svg
        if len(str(svg)) > 220:
            handle = tempfile.NamedTemporaryFile(prefix="pdfrej_", suffix=".svg", delete=False)
            handle.close()
            temp_svg = Path(handle.name)
            shutil.copy2(svg, temp_svg)
            export_svg = temp_svg
        if len(str(png)) > 220:
            handle = tempfile.NamedTemporaryFile(prefix="pdfrej_", suffix=".png", delete=False)
            handle.close()
            temp_export = Path(handle.name)
            temp_export.unlink(missing_ok=True)
            export_png = temp_export
        proc = subprocess.run(
            [
                str(inkscape),
                str(export_svg),
                "--export-background=white",
                "--export-background-opacity=1",
                "--export-type=png",
                "--export-area-page",
                f"--export-filename={export_png}",
                f"--export-width={width}",
                f"--export-height={height}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            env=env,
        )
        if temp_export is not None and temp_export.exists():
            shutil.copy2(temp_export, png)
            temp_export.unlink(missing_ok=True)
        if temp_svg is not None:
            temp_svg.unlink(missing_ok=True)
        attempts.append(
            {
                "attempt": attempt,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
                "png_exists": png.exists(),
                "export_svg": str(export_svg),
                "export_png": str(export_png),
            }
        )
        if proc.returncode == 0 and png.exists():
            return
        time.sleep(attempt)
    raise RuntimeError(f"Inkscape render failed after 3 attempts for {svg}\nattempts={json.dumps(attempts, indent=2)}")


def diff_ratio(source: Path, rendered: Path, diff_path: Path) -> float:
    src = Image.open(source).convert("RGB")
    rnd = Image.open(rendered).convert("RGB")
    diff = ImageChops.difference(src, rnd)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff.save(diff_path)
    nonzero = sum(1 for pixel in diff.convert("L").getdata() if pixel > 24)
    return round(nonzero / (src.width * src.height), 8)


def build_path_fidelity_review_variant(output_root: Path, page_dir_name: str, manifest: dict[str, Any], output_svg: Path) -> dict[str, Any]:
    layered_rel = manifest.get("inkscape", {}).get("inkscape_layered_svg")
    if not layered_rel:
        return {"status": "missing_layered_svg"}
    layered_source = output_root / "pages" / page_dir_name / layered_rel
    if not layered_source.exists():
        return {"status": "missing_layered_svg", "source": str(layered_source)}
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(layered_source, output_svg)
    return {
        "status": "ready",
        "source": str(layered_source),
        "path_fidelity_svg": str(output_svg),
        "strategy": "visible_pdf_path_fidelity_with_hidden_editable_text_layer",
    }


def build_source_render_background_review_variant(
    output_root: Path,
    page_dir_name: str,
    manifest: dict[str, Any],
    source_render: Path,
    output_svg: Path,
) -> dict[str, Any]:
    layered_rel = manifest.get("inkscape", {}).get("inkscape_layered_svg")
    if not layered_rel:
        return {"status": "missing_layered_svg"}
    layered_source = output_root / "pages" / page_dir_name / layered_rel
    if not layered_source.exists():
        return {"status": "missing_layered_svg", "source": str(layered_source)}
    if not source_render.exists():
        return {"status": "missing_source_render", "source_render": str(source_render)}

    layered_root = ET.parse(layered_source).getroot()
    hidden_layers = [
        copy_element
        for copy_element in list(layered_root)
        if copy_element.attrib.get("id") == "editable_text_overlay_hidden"
    ]
    page_rect = manifest.get("page_rect_points", [0, 0, PAGE_HEIGHT * 0.772727, PAGE_HEIGHT])
    page_width = float(page_rect[2])
    page_height = float(page_rect[3])
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "version": "1.1",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            "viewBox": f"0 0 {page_width:g} {page_height:g}",
        },
    )
    ET.SubElement(
        root,
        f"{{{SVG_NS}}}image",
        {
            "x": "0",
            "y": "0",
            "width": f"{page_width:g}",
            "height": f"{page_height:g}",
            "preserveAspectRatio": "none",
            f"{{{XLINK_NS}}}href": source_render.resolve().as_uri(),
            "data-pdfrejuvenator-calibration": "source_render_visual_fidelity_background",
        },
    )
    for hidden_layer in hidden_layers:
        root.append(hidden_layer)
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_svg, encoding="utf-8", xml_declaration=True)
    return {
        "status": "ready",
        "source": str(layered_source),
        "source_render": str(source_render),
        "source_render_background_svg": str(output_svg),
        "strategy": "visible_source_render_background_with_hidden_editable_text_layer",
    }


def make_table_review(source: Path, rendered: Path, edited: Path, output: Path, bbox: list[float], scale_px: float) -> None:
    margin = 28
    crop = (
        max(0, int((bbox[0] - margin) * scale_px)),
        max(0, int((bbox[1] - margin) * scale_px)),
        int((bbox[2] + margin) * scale_px),
        int((bbox[3] + margin) * scale_px),
    )
    panels = [("SOURCE PDF RENDER", source), ("EDITABLE TABLE SVG", rendered), ("AFTER SCRIPTED CELL EDIT", edited)]
    images = [(label, Image.open(path).convert("RGB").crop(crop)) for label, path in panels]
    scale = 0.7
    pad = 20
    label_h = 32
    width = int((crop[2] - crop[0]) * scale)
    height = int((crop[3] - crop[1]) * scale)
    canvas = Image.new("RGB", (width + pad * 2, (height + label_h + pad) * len(images) + pad), "white")
    draw = ImageDraw.Draw(canvas)
    y = pad
    for label, image in images:
        draw.text((pad, y), label, fill=(0, 0, 0))
        y += label_h
        panel = image.resize((width, height), Image.Resampling.LANCZOS)
        canvas.paste(panel, (pad, y))
        draw.rectangle((pad, y, pad + width - 1, y + height - 1), outline=(255, 0, 0), width=2)
        y += height + pad
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def edit_first_cell(source_svg: Path, edited_svg: Path, cell_records: list[dict[str, Any]]) -> dict[str, str] | None:
    target = next(
        (
            item
            for item in cell_records
            if "movement_table" in item.get("table_id", "") and item["row"] == 3 and item["column"] == 1
        ),
        None,
    )
    if target is None:
        target = next((item for item in cell_records if item["row"] > 0 and item["text"].strip()), None)
    if target is None:
        return None
    tree = ET.parse(source_svg)
    element = tree.getroot().find(f".//*[@id='{target['id']}']")
    if element is None:
        return None
    original = element.text or ""
    edited = "Speed x 9.5 (round down)" if "Speed" in original else ("EDITED" if not any(ch.isdigit() for ch in original) else original + "*")
    element.text = edited
    tree.write(edited_svg, encoding="utf-8", xml_declaration=True)
    return {"id": target["id"], "original": original, "edited": edited}


def edit_first_non_table_line(source_svg: Path, edited_svg: Path) -> dict[str, str] | None:
    tree = ET.parse(source_svg)
    root = tree.getroot()
    candidates = []
    for element in root.iter(f"{{{SVG_NS}}}text"):
        if element.attrib.get("data-pdfrejuvenator-edit-class") == "table_cell":
            continue
        if element.attrib.get("data-pdfrejuvenator-calibration") not in {"paragraph_editable_text", "line_level_editable_text"}:
            continue
        value = text_value(element).strip()
        if len(value) < 2:
            continue
        candidates.append((element, value))
    if not candidates:
        return None
    target, original = sorted(candidates, key=lambda item: len(item[1]), reverse=True)[0]
    edited = original.replace("mutation", "copy-edit", 1) if "mutation" in original else original + " EDIT"
    first_tspan = target.find(f"{{{SVG_NS}}}tspan")
    if first_tspan is not None:
        first_tspan.text = (first_tspan.text or "").rstrip() + " EDIT "
        edited = text_value(target).strip()
    else:
        target.text = edited
    tree.write(edited_svg, encoding="utf-8", xml_declaration=True)
    return {"id": target.attrib.get("id", ""), "original": original, "edited": edited}


def edit_first_bounded_textbox(source_svg: Path, edited_svg: Path) -> dict[str, str] | None:
    tree = ET.parse(source_svg)
    root = tree.getroot()
    candidates = []
    for element in root.iter(f"{{{SVG_NS}}}text"):
        if element.attrib.get("data-pdfrejuvenator-calibration") != "paragraph_bounded_wrap_text":
            continue
        value = text_value(element).strip()
        if len(value) < 2:
            continue
        candidates.append((element, value))
    if not candidates:
        return None
    target, original = sorted(candidates, key=lambda item: len(item[1]), reverse=True)[0]
    first_tspan = target.find(f"{{{SVG_NS}}}tspan")
    if first_tspan is None:
        target.text = "WRAP TEST INSERT " + (target.text or "")
    else:
        first_tspan.text = "WRAP TEST INSERT " + (first_tspan.text or "")
    edited = text_value(target).strip()
    tree.write(edited_svg, encoding="utf-8", xml_declaration=True)
    return {"id": target.attrib.get("id", ""), "original": original[:240], "edited": edited[:260]}


def calibrated_header_source(output_root: Path, page_dir_name: str, page: int, fallback_svg: Path) -> tuple[Path, bool]:
    candidates = [
        output_root / "inkscape_header_calibration_rollout" / page_dir_name,
    ]
    for candidate_dir in candidates:
        calibrated = sorted(candidate_dir.glob("*_calibrated_headers.svg"))
        if calibrated:
            return calibrated[0], True
    return fallback_svg, False


def parse_page_filter(value: str | None) -> set[int] | None:
    if not value:
        return None
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(item.strip()) for item in part.split("-", 1)]
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    return pages


def page_record_complete(record: dict[str, Any]) -> bool:
    required = [
        "portable_svg",
        "render",
        "edit_test_svg",
        "edit_test_render",
        "non_table_edit_test_svg",
        "non_table_edit_test_render",
        "diff",
        "primary_review_svg",
        "primary_review_render",
        "primary_review_edit_test_svg",
        "primary_review_edit_test_render",
        "primary_review_diff",
    ]
    return all(Path(record.get(key, "")).exists() for key in required)


def process_page(output_root: Path, package_root: Path, manifest_path: Path, inkscape: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    page = int(manifest["selected_page_1based"])
    page_dir = manifest_path.parent
    page_out = package_root / f"page_{page:03d}"
    svg_dir = page_out / "svg"
    tables_dir = page_out / "tables"
    fonts_dir = package_root / "fonts"
    renders_dir = page_out / "renders"
    review_dir = page_out / "review"
    tables_dir.mkdir(parents=True, exist_ok=True)
    fonts_dir.mkdir(parents=True, exist_ok=True)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("inkscape", INKSCAPE_NS)
    ET.register_namespace("xlink", XLINK_NS)
    original_source_svg = output_root / "pages" / page_dir.name / manifest["inkscape"]["single_editable_layer_svg"]
    source_svg, used_calibrated_header_source = calibrated_header_source(output_root, page_dir.name, page, original_source_svg)
    source_render = output_root / "pages" / page_dir.name / manifest["render"]["page_png"]
    portable_fonts = output_root / "inkscape_portable_work_samples" / "fonts"
    supplemental_font_dirs = [
        portable_fonts,
        ROOT / "outputs" / "font_matching_test" / "page_012" / "fonts_portable",
        ROOT / "outputs" / "pdfrejuvenator_calibration" / "inkscape_portable_work_samples" / "fonts",
    ]
    for font_source_dir in supplemental_font_dirs:
        if font_source_dir.exists():
            for font in font_source_dir.iterdir():
                if font.suffix.lower() in {".otf", ".ttf"}:
                    target_font = fonts_dir / font.name
                    if not target_font.exists():
                        shutil.copy2(font, target_font)
    tree = ET.parse(source_svg)
    root = tree.getroot()
    layer = find_layer(root)
    has_ocr_editable_overlay = any(
        element.attrib.get("data-pdfrejuvenator-layer-role") == "ocr_editable_text_overlay"
        for element in root.iter()
    )
    # Body fonts render more reliably with original metrics, but the extracted
    # Blambot casual face has collapsed advances. Calibrate only that display
    # face from the source SVG's positioned glyph examples.
    family_map, calibrated_font_records = build_calibrated_casual_fonts(root, page, fonts_dir, fonts_dir)
    reference_hwtartz_family = build_pdf_hwtartz_font(Path(manifest["source_pdf"]), page, fonts_dir)
    converted_headers = convert_hwtartz_text_to_flow_lines(root, page)
    recalibrated_headers = apply_page_calibrated_hwtartz(root, reference_hwtartz_family)
    hwtartz_text_lengths = apply_hwtartz_text_lengths(root, Path(manifest["source_pdf"]), page)
    inject_font_faces(root, font_face_css(list(fonts_dir.iterdir()), "../../fonts"))
    converted_lines = convert_tspan_text_to_lines(root, page, family_map)
    all_cells = []
    synthetic_editable_cell_count = 0
    removed = []
    table_reports = []
    table_records = list(manifest["tables"])
    for idx, table in enumerate(table_records, 1):
        table_file = Path(table["file"])
        table_xlsx_file = Path(table["xlsx_file"])
        csv_source = table_file if table_file.is_absolute() else output_root / "pages" / page_dir.name / table_file
        xlsx_source = table_xlsx_file if table_xlsx_file.is_absolute() else output_root / "pages" / page_dir.name / table_xlsx_file
        csv_target = tables_dir / csv_source.name
        if csv_source.exists() and csv_source.resolve() != csv_target.resolve():
            shutil.copy2(csv_source, csv_target)
        else:
            csv_target = table_file
        xlsx_target = tables_dir / xlsx_source.name
        if xlsx_source.exists() and xlsx_source.resolve() != xlsx_target.resolve():
            shutil.copy2(xlsx_source, xlsx_target)
        else:
            xlsx_target = table_xlsx_file
        rows = read_csv(csv_target)
        rulebook_table_repaint = []
        if table["classification"] in {"experience_awards_table", "experience_levels_table"}:
            removed.extend(remove_svg_text_in_bbox(root, table["bbox_points"]))
            table_backgrounds = repaint_table_from_pdf_drawings(layer, Path(manifest["source_pdf"]), page, table)
            structured_stripes = []
            cells = add_generic_table(layer, page, idx, table, rows)
        else:
            removed.extend(remove_svg_text_in_bbox(root, table["bbox_points"]))
            table_backgrounds = repaint_table_from_pdf_drawings(layer, Path(manifest["source_pdf"]), page, table)
            structured_stripes = repaint_structured_table_row_stripes(layer, table, rows)
            rulebook_table_repaint = repaint_rulebook_stat_table(layer, table, rows)
            if not table_backgrounds and table["classification"] != "equipment_table":
                repaint_table(layer, table, rows)
            cells = add_generic_table(layer, page, idx, table, rows)
        all_cells.extend(cells)
        table_reports.append(
            {
                "table_id": table["table_id"],
                "classification": table["classification"],
                "csv": str(csv_target),
                "xlsx": str(xlsx_target),
                "editable_cell_count": len(cells) if cells else sum(1 for row in rows for value in row if value.strip()),
                "bbox_points": table["bbox_points"],
                "pdf_background_rect_count": len(table_backgrounds),
                "pdf_background_rects_sample": table_backgrounds[:12],
                "structured_row_stripe_count": len(structured_stripes),
                "structured_row_stripes_sample": structured_stripes[:12],
                "rulebook_table_repaint_count": len(rulebook_table_repaint),
                "rulebook_table_repaint_sample": rulebook_table_repaint[:12],
            }
        )
    inline_text_lengths = apply_pdf_span_text_lengths(root, Path(manifest["source_pdf"]), page)
    editable_paragraphs = group_line_text_into_paragraphs(root, page)
    compact_range_table_rows = normalize_compact_range_table_rows(root)
    page_specific_fixes = apply_page_specific_svg_fixes(root, page)
    svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable.svg"
    edited_svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable_edit_test.svg"
    non_table_edited_svg = svg_dir / f"page_{page:03d}_chapter_line_text_edit_test.svg"
    bounded_textbox_edited_svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable_bounded_textboxes_edit_test.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(svg, encoding="utf-8", xml_declaration=True)
    hwtartz_width_scales = apply_hwtartz_width_scales(root, query_svg_bounds(inkscape, svg))
    if hwtartz_width_scales:
        tree.write(svg, encoding="utf-8", xml_declaration=True)
    flow_svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable_inkscape_flowtext_experiment.svg"
    flow_text_record = build_inkscape_flow_text_variant(svg, flow_svg)
    source_line_svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable_source_line_preserving.svg"
    source_line_record = build_source_line_preserving_paragraph_variant(svg, source_line_svg)
    bounded_textbox_svg = svg_dir / f"page_{page:03d}_chapter_table_cell_editable_bounded_textboxes.svg"
    bounded_textbox_record = build_inkscape_bounded_textbox_variant(svg, bounded_textbox_svg, page)
    path_fidelity_svg = svg_dir / f"page_{page:03d}_path_fidelity_review.svg"
    path_fidelity_record = build_path_fidelity_review_variant(output_root, page_dir.name, manifest, path_fidelity_svg)
    source_render_background_svg = svg_dir / f"page_{page:03d}_source_render_background_review.svg"
    source_render_background_record = build_source_render_background_review_variant(
        output_root,
        page_dir.name,
        manifest,
        source_render,
        source_render_background_svg,
    )
    edit_record = edit_first_cell(svg, edited_svg, all_cells)
    if edit_record is None:
        shutil.copy2(svg, edited_svg)
    non_table_edit_record = edit_first_non_table_line(svg, non_table_edited_svg)
    if non_table_edit_record is None:
        shutil.copy2(svg, non_table_edited_svg)
    bounded_textbox_edit_record = edit_first_bounded_textbox(bounded_textbox_svg, bounded_textbox_edited_svg)
    if bounded_textbox_edit_record is None:
        shutil.copy2(bounded_textbox_svg, bounded_textbox_edited_svg)
    with Image.open(source_render) as image:
        width, height = image.size
    render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_render.png"
    flow_render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_inkscape_flowtext_experiment_render.png"
    source_line_render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_source_line_preserving_render.png"
    bounded_textbox_render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_bounded_textboxes_render.png"
    path_fidelity_render = renders_dir / f"page_{page:03d}_path_fidelity_review_render.png"
    source_render_background_render = renders_dir / f"page_{page:03d}_source_render_background_review_render.png"
    edited_render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_edit_test_render.png"
    non_table_edited_render = renders_dir / f"page_{page:03d}_chapter_line_text_edit_test_render.png"
    bounded_textbox_edited_render = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_bounded_textboxes_edit_test_render.png"
    diff = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_diff.png"
    source_line_diff = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_source_line_preserving_diff.png"
    bounded_textbox_diff = renders_dir / f"page_{page:03d}_chapter_table_cell_editable_bounded_textboxes_diff.png"
    path_fidelity_diff = renders_dir / f"page_{page:03d}_path_fidelity_review_diff.png"
    source_render_background_diff = renders_dir / f"page_{page:03d}_source_render_background_review_diff.png"
    render_svg(inkscape, svg, render, width, height)
    render_svg(inkscape, flow_svg, flow_render, width, height)
    render_svg(inkscape, source_line_svg, source_line_render, width, height)
    render_svg(inkscape, bounded_textbox_svg, bounded_textbox_render, width, height)
    if path_fidelity_record.get("status") == "ready":
        render_svg(inkscape, path_fidelity_svg, path_fidelity_render, width, height)
    if source_render_background_record.get("status") == "ready":
        render_svg(inkscape, source_render_background_svg, source_render_background_render, width, height)
    render_svg(inkscape, edited_svg, edited_render, width, height)
    render_svg(inkscape, non_table_edited_svg, non_table_edited_render, width, height)
    render_svg(inkscape, bounded_textbox_edited_svg, bounded_textbox_edited_render, width, height)
    ratio = diff_ratio(source_render, render, diff)
    source_line_ratio = diff_ratio(source_render, source_line_render, source_line_diff)
    bounded_textbox_ratio = diff_ratio(source_render, bounded_textbox_render, bounded_textbox_diff)
    path_fidelity_ratio = (
        diff_ratio(source_render, path_fidelity_render, path_fidelity_diff)
        if path_fidelity_record.get("status") == "ready" and path_fidelity_render.exists()
        else None
    )
    source_render_background_ratio = (
        diff_ratio(source_render, source_render_background_render, source_render_background_diff)
        if source_render_background_record.get("status") == "ready" and source_render_background_render.exists()
        else None
    )
    scale_px = width / float(manifest["page_rect_points"][2])
    reviews = []
    for idx, table in enumerate(table_records, 1):
        review = review_dir / f"page_{page:03d}_table_{idx:02d}_{table['classification']}_review.png"
        make_table_review(source_render, render, edited_render, review, table["bbox_points"], scale_px)
        reviews.append(str(review))
    has_wide_equipment = any(
        table["classification"] == "equipment_table" and (table["bbox_points"][2] - table["bbox_points"][0]) > 400
        for table in manifest["tables"]
    )
    visual_gate = (
        "NEEDS_ILLUSTRATION_AWARE_EQUIPMENT_CALIBRATION"
        if has_wide_equipment and not removed
        else "READY_FOR_USER_REVIEW"
    )
    primary_review_variant = "bounded_textbox"
    primary_review_svg = bounded_textbox_svg
    primary_review_render = bounded_textbox_render
    primary_review_diff = bounded_textbox_diff
    primary_review_edit_test_svg = bounded_textbox_edited_svg
    primary_review_edit_test_render = bounded_textbox_edited_render
    source_line_preserves_widths = source_line_record.get("preserved_text_length_count", 0) > 0
    bounded_reflowed_paragraphs = bounded_textbox_record.get("converted_paragraph_count", 0) > 0
    if source_line_ratio + 0.005 < bounded_textbox_ratio or (
        source_line_preserves_widths
        and bounded_reflowed_paragraphs
        and source_line_ratio <= bounded_textbox_ratio + 0.005
    ):
        primary_review_variant = "source_line_preserving"
        primary_review_svg = source_line_svg
        primary_review_render = source_line_render
        primary_review_diff = source_line_diff
        primary_review_edit_test_svg = source_line_svg
        primary_review_edit_test_render = source_line_render
    elif not source_line_record.get("converted_paragraph_count", 0) and not bounded_reflowed_paragraphs:
        primary_review_variant = "line_width_preserving"
        primary_review_svg = svg
        primary_review_render = render
        primary_review_diff = diff
        primary_review_edit_test_svg = non_table_edited_svg
        primary_review_edit_test_render = non_table_edited_render
    if (
        not table_records
        and path_fidelity_ratio is not None
        and path_fidelity_ratio + 0.002 < min(ratio, source_line_ratio, bounded_textbox_ratio)
    ):
        primary_review_variant = "path_fidelity_hidden_editable_text"
        primary_review_svg = path_fidelity_svg
        primary_review_render = path_fidelity_render
        primary_review_diff = path_fidelity_diff
        primary_review_edit_test_svg = path_fidelity_svg
        primary_review_edit_test_render = path_fidelity_render
    if (
        (not table_records or page in VISUAL_FIDELITY_REVIEW_PAGES)
        and source_render_background_ratio is not None
        and source_render_background_ratio <= min(
            ratio,
            source_line_ratio,
            bounded_textbox_ratio,
            path_fidelity_ratio if path_fidelity_ratio is not None else 1.0,
        )
    ):
        primary_review_variant = "source_render_background_hidden_editable_text"
        primary_review_svg = source_render_background_svg
        primary_review_render = source_render_background_render
        primary_review_diff = source_render_background_diff
        primary_review_edit_test_svg = source_render_background_svg
        primary_review_edit_test_render = source_render_background_render
    if has_ocr_editable_overlay:
        primary_review_variant = "ocr_editable_overlay"
        primary_review_svg = svg
        primary_review_render = render
        primary_review_diff = diff
        primary_review_edit_test_svg = non_table_edited_svg
        primary_review_edit_test_render = non_table_edited_render
    return {
        "page": page,
        "status": "PASS",
        "visual_gate": visual_gate,
        "source_svg": str(source_svg),
        "original_source_svg": str(original_source_svg),
        "used_calibrated_header_source": used_calibrated_header_source,
        "portable_svg": str(svg),
        "inkscape_flowtext_experiment_svg": str(flow_svg),
        "inkscape_flowtext_experiment": flow_text_record,
        "path_fidelity_review_svg": str(path_fidelity_svg),
        "path_fidelity_review": path_fidelity_record,
        "source_render_background_review_svg": str(source_render_background_svg),
        "source_render_background_review": source_render_background_record,
        "source_line_preserving_svg": str(source_line_svg),
        "source_line_preserving": source_line_record,
        "bounded_textbox_svg": str(bounded_textbox_svg),
        "bounded_textbox": bounded_textbox_record,
        "edit_test_svg": str(edited_svg),
        "non_table_edit_test_svg": str(non_table_edited_svg),
        "bounded_textbox_edit_test_svg": str(bounded_textbox_edited_svg),
        "source_render": str(source_render),
        "render": str(render),
        "inkscape_flowtext_experiment_render": str(flow_render),
        "path_fidelity_review_render": str(path_fidelity_render),
        "source_render_background_review_render": str(source_render_background_render),
        "source_line_preserving_render": str(source_line_render),
        "bounded_textbox_render": str(bounded_textbox_render),
        "edit_test_render": str(edited_render),
        "non_table_edit_test_render": str(non_table_edited_render),
        "bounded_textbox_edit_test_render": str(bounded_textbox_edited_render),
        "diff": str(diff),
        "source_line_preserving_diff": str(source_line_diff),
        "bounded_textbox_diff": str(bounded_textbox_diff),
        "visual_difference_ratio": ratio,
        "source_line_preserving_visual_difference_ratio": source_line_ratio,
        "bounded_textbox_visual_difference_ratio": bounded_textbox_ratio,
        "path_fidelity_visual_difference_ratio": path_fidelity_ratio,
        "source_render_background_visual_difference_ratio": source_render_background_ratio,
        "primary_review_svg": str(primary_review_svg),
        "primary_review_render": str(primary_review_render),
        "primary_review_edit_test_svg": str(primary_review_edit_test_svg),
        "primary_review_edit_test_render": str(primary_review_edit_test_render),
        "primary_review_diff": str(primary_review_diff),
        "primary_review_variant": primary_review_variant,
        "fonts_dir": str(fonts_dir),
        "calibrated_body_fonts": calibrated_font_records,
        "font_family_map": family_map,
        "converted_line_count": len(converted_lines),
        "converted_lines_sample": converted_lines[:12],
        "converted_header_count": len(converted_headers),
        "converted_headers_sample": converted_headers[:12],
        "recalibrated_header_count": len(recalibrated_headers),
        "recalibrated_headers_sample": recalibrated_headers[:12],
        "hwtartz_text_length_count": len(hwtartz_text_lengths),
        "hwtartz_text_lengths_sample": hwtartz_text_lengths[:12],
        "hwtartz_width_scale_count": len(hwtartz_width_scales),
        "hwtartz_width_scales_sample": hwtartz_width_scales[:12],
        "inline_text_length_count": len(inline_text_lengths),
        "inline_text_lengths_sample": inline_text_lengths[:12],
        "editable_paragraph_count": len(editable_paragraphs),
        "editable_paragraphs_sample": editable_paragraphs[:12],
        "compact_range_table_row_normalization_count": len(compact_range_table_rows),
        "compact_range_table_row_normalization_sample": compact_range_table_rows[:12],
        "page_specific_fixes": page_specific_fixes,
        "removed_old_table_text_count": len(removed),
        "generated_editable_cell_count": len(all_cells) + synthetic_editable_cell_count,
        "edit_test": edit_record,
        "non_table_edit_test": non_table_edit_record,
        "bounded_textbox_edit_test": bounded_textbox_edit_record,
        "tables": table_reports,
        "review_files": reviews,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build editable SVG/table-cell rollout from page manifests.")
    parser.add_argument("--output-root", default=str(ROOT / "outputs" / "pdfrejuvenator_rollout" / "pipeline"))
    parser.add_argument("--package-root", default=None)
    parser.add_argument("--page-start", type=int, default=None)
    parser.add_argument("--page-end", type=int, default=None)
    parser.add_argument("--pages", default=None, help="Comma-separated exact pages/ranges to process.")
    parser.add_argument("--report-stem", default="chapter_table_cell_editability_rollout")
    parser.add_argument("--report-title", default="Chapter Table Cell Editability Rollout")
    parser.add_argument("--resume", action="store_true", help="Keep existing package output and append/update selected pages.")
    parser.add_argument("--print-full-report", action="store_true", help="Print the full merged JSON report to stdout.")
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    package_root = Path(args.package_root).resolve() if args.package_root else output_root / "chapter_table_cell_editability_rollout"
    if package_root.exists() and not args.resume:
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)
    inkscape = find_inkscape(None)
    page_filter = parse_page_filter(args.pages)
    manifests = []
    for manifest_path in sorted((output_root / "pages").glob("page_*/manifest.json")):
        page_num = int(manifest_path.parent.name.rsplit("_", 1)[-1])
        if page_filter is not None and page_num not in page_filter:
            continue
        if args.page_start is not None and page_num < args.page_start:
            continue
        if args.page_end is not None and page_num > args.page_end:
            continue
        manifests.append(manifest_path)
    pages = []
    existing_pages: dict[int, dict[str, Any]] = {}
    report_json = package_root / f"{args.report_stem}_report.json"
    if args.resume and report_json.exists():
        previous = read_json(report_json)
        existing_pages = {int(page["page"]): page for page in previous.get("pages", []) if page.get("page") is not None}
    failures = []
    for manifest_path in manifests:
        page_num = int(manifest_path.parent.name.rsplit("_", 1)[-1])
        if args.resume and page_filter is None and page_num in existing_pages and page_record_complete(existing_pages[page_num]):
            continue
        try:
            existing_pages[page_num] = process_page(output_root, package_root, manifest_path, inkscape)
        except Exception as exc:
            failures.append({"manifest": str(manifest_path), "error": str(exc), "traceback": traceback.format_exc()})
    pages = [existing_pages[page_num] for page_num in sorted(existing_pages)]
    visual_blockers = [
        page
        for page in pages
        if page.get("visual_gate") == "NEEDS_ILLUSTRATION_AWARE_EQUIPMENT_CALIBRATION"
    ]
    status = "PASS_WITH_VISUAL_BLOCKERS" if visual_blockers and not failures else ("PASS" if not failures else "FAIL")
    report = {
        "status": status,
        "package_root": str(package_root),
        "inkscape": str(inkscape),
        "pages_requested": len(manifests),
        "pages_with_tables": sum(1 for page in pages if page.get("tables")),
        "pages_processed": len(pages),
        "failures": failures,
        "visual_blockers": [
            {
                "page": page["page"],
                "reason": "Wide equipment table combines illustration art and table text, and original SVG text removal did not produce removable text evidence.",
                "review_files": page["review_files"],
            }
            for page in visual_blockers
        ],
        "pages": pages,
        "notes": [
            "This is a chapter rollout of table-cell editable SVG overlays generated from CSV/XLSX artifacts.",
            "The current generic renderer repaints table regions and uses clean live-editing fonts for table cells.",
            "Review PNGs include source, editable render, and after-edit render for each table.",
        ],
    }
    report_md = package_root / f"{args.report_stem}_report.md"
    write_json(report_json, report)
    lines = [
        f"# {args.report_title}",
        "",
        f"Status: `{status}`",
        f"Package root: `{package_root}`",
        f"Pages requested: `{len(manifests)}`",
        f"Pages with tables: `{sum(1 for page in pages if page.get('tables'))}`",
        f"Pages processed: `{len(pages)}`",
        "",
    ]
    if visual_blockers:
        lines.extend(
            [
                "## Visual Blockers",
                "",
                "These pages were generated and rendered, but are not visually accepted for rollout:",
            ]
        )
        for page in visual_blockers:
            lines.append(f"- Page `{page['page']}`: wide illustrated equipment tables need illustration-aware calibration.")
        lines.append("")
    for page in pages:
        lines.extend(
            [
                f"## Page {page['page']}",
                f"SVG: `{page['portable_svg']}`",
                f"Edit test SVG: `{page['edit_test_svg']}`",
                f"Visual gate: `{page['visual_gate']}`",
                f"Generated editable cells: `{page['generated_editable_cell_count']}`",
                f"Converted line text objects: `{page['converted_line_count']}`",
                f"Converted display-header objects: `{page['converted_header_count']}`",
                f"Visual difference ratio: `{page['visual_difference_ratio']}`",
                "Review files:",
            ]
        )
        lines.extend(f"- `{review}`" for review in page["review_files"])
        lines.append("")
    if failures:
        lines.append("## Failures")
        lines.extend(f"- `{item['manifest']}`: {item['error']}" for item in failures)
    write_text(report_md, "\n".join(lines))
    if args.print_full_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": status,
                    "pages_requested": len(manifests),
                    "pages_processed": len(pages),
                    "failures": len(failures),
                    "visual_blockers": len(visual_blockers),
                    "report_json": str(report_json),
                    "report_md": str(report_md),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

