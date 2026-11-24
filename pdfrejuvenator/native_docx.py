"""Native editable DOCX conversion from PDF geometry; no bundled source content."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def normalized(text: str) -> str:
    text = ''.join(ch for ch in text.replace('\xad', '') if ch == '\n' or ord(ch) >= 32)
    return ' '.join(text.split())

def page_selector(value: str | None, count: int) -> list[int]:
    if not value:
        return list(range(1, count + 1))
    selected: set[int] = set()
    for term in value.split(','):
        a, sep, b = term.strip().partition('-')
        if not a.isdigit() or (sep and (not b.isdigit())):
            raise ValueError(f'bad_page_selector:{term}')
        lo, hi = (int(a), int(b or a))
        if lo < 1 or hi > count or hi < lo:
            raise ValueError(f'page_selector_out_of_range:{term}:1-{count}')
        selected.update(range(lo, hi + 1))
    return sorted(selected)

def source_lines(page: fitz.Page) -> list[dict]:
    records: list[dict] = []
    for block in page.get_text('dict').get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            spans = line.get('spans', [])
            text = normalized(''.join(s.get('text', '') for s in spans))
            if not text:
                continue
            x0, y0, x1, y1 = line['bbox']
            max_size = max((float(s.get('size', 0)) for s in spans), default=8.0)
            flags = max((int(s.get('flags', 0)) for s in spans), default=0)
            records.append({'text': text, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1, 'size': max_size, 'flags': flags})
    return records

def classify_layout(page: fitz.Page, lines: list[dict]) -> str:
    if len(lines) <= 5:
        return 'title_or_art'
    width = page.rect.width
    left = [x for x in lines if x['x0'] < width * 0.47 and x['x1'] < width * 0.58]
    right = [x for x in lines if x['x0'] > width * 0.52]
    if len(left) >= 6 and len(right) >= 6:
        return 'two_column_prose'
    return 'one_column_prose'

def ordered_columns(page: fitz.Page, lines: list[dict], layout: str) -> list[list[dict]]:
    if layout != 'two_column_prose':
        return [sorted(lines, key=lambda item: (item['y0'], item['x0']))]
    width = page.rect.width
    full = [x for x in lines if x['x0'] < width * 0.25 and x['x1'] > width * 0.75]
    body = [x for x in lines if x not in full]
    left = sorted([x for x in body if x['x0'] < width * 0.5], key=lambda item: item['y0'])
    right = sorted([x for x in body if x['x0'] >= width * 0.5], key=lambda item: item['y0'])
    return [sorted(full, key=lambda item: item['y0']), left, right]

def is_scan_layer_stack(page: fitz.Page, placements: list[tuple[int, fitz.Rect]]) -> bool:
    minimum_area = page.rect.width * page.rect.height * 0.88
    full_page = [rect for _xref, rect in placements if rect.width * rect.height >= minimum_area and rect.width >= page.rect.width * 0.9 and (rect.height >= page.rect.height * 0.9)]
    return len(full_page) >= 3

def extract_art(page: fitz.Page, pdf: fitz.Document, page_dir: Path, corrections: dict) -> list[dict]:
    include = set(corrections.get('includeXrefs', []))
    exclude = set(corrections.get('excludeXrefs', []))
    placements = [(image[0], rect) for image in page.get_images(full=True) if image[0] not in exclude for rect in page.get_image_rects(image[0])]
    if not include and is_scan_layer_stack(page, placements):
        asset = page_dir / 'scan-layer-composite.png'
        page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(asset)
        return [{'composite': True, 'semanticRole': 'source_scan_layer_composite', 'bbox': [round(v, 2) for v in page.rect], 'asset': str(asset.resolve()), 'sha256': digest(asset)}]
    result: list[dict] = []
    seen: set[tuple] = set()
    for image in page.get_images(full=True):
        xref = image[0]
        if xref in exclude:
            continue
        if include and xref not in include:
            continue
        for rect in page.get_image_rects(xref):
            area = rect.width * rect.height
            if xref not in include and (area < 3600 or rect.width < 40 or rect.height < 40):
                continue
            key = (xref, round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            asset = page_dir / f'art-{xref}-{len(result)}.png'
            if not asset.exists():
                pix = fitz.Pixmap(pdf, xref)
                pix.save(asset)
            result.append({'xref': xref, 'bbox': [round(v, 2) for v in rect], 'asset': str(asset.resolve()), 'sha256': digest(asset)})
    for index, region in enumerate(corrections.get('compositeRegions', [])):
        clip = fitz.Rect(region['bbox'])
        asset = page_dir / f'composite-{index}.png'
        page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=clip, alpha=False).save(asset)
        result.append({'composite': True, 'bbox': region['bbox'], 'asset': str(asset.resolve()), 'sha256': digest(asset)})
    return result

def in_any_region(x0: float, y0: float, regions: list[list[float]]) -> bool:
    return any(region[0] <= x0 <= region[2] and region[1] <= y0 <= region[3] for region in regions)

def add_coordinate_table(document: Document, page: fitz.Page, role: dict, lines: list[dict]) -> None:
    bounds = role['columnBounds']
    columns = len(bounds) - 1
    rows: dict[int, list[list[str]]] = {}
    for line in sorted((line for line in lines if in_any_region(line['x0'], line['y0'], role.get('headerTextRegions', []))), key=lambda item: (item['y0'], item['x0'])):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(line['text'])
        r.font.name = 'Times New Roman'
        r.font.size = Pt(max(9, min(18, line['size'] + 1)))
        r.bold = line['size'] >= 10
    catalog_regions = role.get('catalogRegions')
    for x0, y0, _x1, _y1, word, *_ in page.get_text('words'):
        if y0 > role.get('maxY', page.rect.height - 18) or (word.isdigit() and y0 > page.rect.height - 50):
            continue
        if catalog_regions and (not in_any_region(x0, y0, catalog_regions)):
            continue
        col = next((i for i in range(columns) if bounds[i] <= x0 < bounds[i + 1]), None)
        if col is None:
            continue
        key = round(y0 / role.get('rowTolerance', 9))
        rows.setdefault(key, [[] for _ in range(columns)])[col].append(word)
    table = document.add_table(rows=0, cols=columns)
    table.style = 'Table Grid'
    for _key, values in sorted(rows.items()):
        if not any(values):
            continue
        cells = table.add_row().cells
        for index, tokens in enumerate(values):
            if tokens:
                r = cells[index].paragraphs[0].add_run(' '.join(tokens))
                r.font.name = 'Times New Roman'
                r.font.size = Pt(8)
    footer_regions = role.get('footerTextRegions', [])
    for line in sorted((line for line in lines if in_any_region(line['x0'], line['y0'], footer_regions)), key=lambda item: (item['x0'], item['y0'])):
        p = document.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run(line['text'])
        r.font.name = 'Times New Roman'
        r.font.size = Pt(8.5)


def validate_destination(output_root: Path) -> Path:
    """Refuse application data and repository trees before creating output."""
    output = output_root.resolve()
    repo = Path(__file__).resolve().parents[1]
    if output == repo or repo in output.parents:
        raise ValueError("output_must_be_outside_repository")
    if any("clairvoyance" in part.casefold() for part in output.parts):
        raise ValueError("output_under_clairvoyance_is_an_error")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise ValueError("output_must_be_outside_repository")
    if output.exists():
        raise ValueError("output_directory_must_be_new")
    return output


def convert_pdf(source: Path, output_root: Path, pages: str | None = None,
                corrections: Path | None = None) -> dict:
    """Emit native paragraphs, coordinate tables and source images without inference."""
    source = source.resolve()
    output = validate_destination(output_root)
    source_sha = digest(source)
    rules = {}
    if corrections is not None:
        payload = json.loads(corrections.read_text(encoding="utf-8"))
        if payload.get("sourceSha256") != source_sha:
            raise ValueError("correction_source_hash_mismatch")
        rules = payload.get("pages", {})
    with fitz.open(source) as pdf:
        selected = page_selector(pages, len(pdf))
        if not selected:
            raise ValueError("empty_page_selection")
        output.mkdir(parents=True, exist_ok=False)
        document = Document()
        section = document.sections[0]
        section.top_margin = section.bottom_margin = Inches(.42)
        section.left_margin = section.right_margin = Inches(.48)
        records = []
        for position, number in enumerate(selected):
            page = pdf[number - 1]
            rule = rules.get(str(number), {})
            lines = source_lines(page)
            lines = [line for line in lines if not in_any_region(
                line["x0"], line["y0"], rule.get("excludeTextRegions", []))]
            for line in lines:
                for old, new in rule.get("replacements", {}).items():
                    line["text"] = line["text"].replace(old, new)
            page_dir = output / "assets" / str(number)
            page_dir.mkdir(parents=True)
            arts = extract_art(page, pdf, page_dir, rule)
            for art in arts:
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.add_run().add_picture(art["asset"], width=Inches(5.7))
            layout = classify_layout(page, lines)
            if rule.get("columnBounds"):
                add_coordinate_table(document, page, rule, lines)
            else:
                for column in ordered_columns(page, lines, layout):
                    for line in column:
                        paragraph = document.add_paragraph()
                        paragraph.paragraph_format.space_after = Pt(0)
                        run = paragraph.add_run(line["text"])
                        run.font.name = "Times New Roman"
                        run.font.size = Pt(max(7.5, min(15, line["size"])))
                        run.bold = bool(line["flags"] & 16) or line["size"] >= 11.5
            records.append({"sourcePage": number, "layout": layout,
                            "nativeLines": len(lines), "images": len(arts),
                            "requiresOcr": not bool(lines)})
            if position < len(selected) - 1:
                document.add_page_break()
        docx = output / "document.docx"
        document.save(docx)
    receipt = {"sourceSha256": source_sha, "docxSha256": digest(docx),
               "docx": str(docx), "pages": records,
               "runtimeInference": False,
               "limitations": "Raster text remains an image; no OCR. Reflow is not pixel parity."}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
