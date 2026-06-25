from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "outputs" / "pdfrejuvenator_review" / "full"
GATE_REPORT = RUN_ROOT / "full_full_book_promotion_gate_report.json"
ROLLOUT_REPORT = RUN_ROOT / "editable_svg_rollout" / "full_full_book_promotion_rollout_report.json"
PACKET_ROOT = RUN_ROOT / "PDFREJUVENATOR_REVIEW_PACKET"


def configure_paths(run_root: Path, report_stem: str) -> None:
    global RUN_ROOT, GATE_REPORT, ROLLOUT_REPORT, PACKET_ROOT
    RUN_ROOT = run_root
    GATE_REPORT = RUN_ROOT / "full_full_book_promotion_gate_report.json"
    ROLLOUT_REPORT = RUN_ROOT / "editable_svg_rollout" / f"{report_stem}_report.json"
    PACKET_ROOT = RUN_ROOT / "PDFREJUVENATOR_REVIEW_PACKET"

PRIORITY_LABELS = {
    1: "front matter",
    2: "known missing text class",
    4: "right-edge numbers",
    5: "right-edge numbers",
    7: "alignment",
    12: "primary fixture",
    14: "middle column",
    15: "table/list spacing",
    17: "table row shading",
    20: "dense layout",
    21: "newlines/bullets",
    24: "character layout",
    25: "character layout",
    27: "character layout",
    28: "character layout",
    29: "character layout",
    30: "character layout",
    31: "character layout",
    34: "character layout",
    35: "character layout",
    36: "character layout",
    37: "character layout",
    39: "character layout",
    41: "character layout",
    42: "character layout",
    43: "character layout",
    44: "character layout",
    47: "character layout",
    51: "table/list layout",
    52: "table/list layout",
    53: "table/list layout",
    55: "newlines/columns",
    62: "table/list layout",
    63: "table/list layout",
    64: "known-good table",
    68: "embedded text table",
    72: "embedded text table",
    75: "right column/table",
    80: "known-good page",
    86: "bottom-right table",
    90: "right-column table",
    93: "right-column table",
    94: "right-column table",
    96: "indentation",
    97: "indentation",
    120: "creative wrap",
    170: "known-good page",
    180: "known-good page",
    240: "known-good page",
    248: "signature layout",
    249: "signature layout",
    268: "index page numbers",
    269: "index page numbers",
    270: "index page numbers",
    271: "index page numbers",
    272: "backer list/newlines",
    274: "signature layout",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_url(value: str | None) -> str:
    if not value:
        return ""
    return Path(value).resolve().as_uri()


def link(label: str, value: str | None) -> str:
    if not value:
        return f'<span class="muted">{html.escape(label)} n/a</span>'
    return f'<a href="{html.escape(file_url(value), quote=True)}">{html.escape(label)}</a>'


def fullres_path(page: int) -> Path:
    return RUN_ROOT / "acceptance" / "manual_review_fullres" / f"page_{page:03d}_source_editable_diff_fullres.png"


def review_sheet_path(page: int) -> Path:
    return RUN_ROOT / "acceptance" / "page_review_sheets" / f"page_{page:03d}_source_render_diff_review.png"


def make_comparison_sheet(page: dict[str, Any], output: Path, scale: float) -> None:
    source = Path(page["source_render"])
    rendered = Path(page["primary_review_render"])
    diff = Path(page.get("primary_review_diff") or "")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not diff.exists():
        diff.parent.mkdir(parents=True, exist_ok=True)
        src_img = Image.open(source).convert("RGB")
        rendered_img = Image.open(rendered).convert("RGB")
        ImageChops.difference(src_img, rendered_img).save(diff)
    panels = [
        ("SOURCE PDF RENDER", Image.open(source).convert("RGB")),
        (f"EDITABLE SVG RENDER ({page.get('primary_review_variant', '')})", Image.open(rendered).convert("RGB")),
        ("PIXEL DIFF", Image.open(diff).convert("RGB")),
    ]
    pad = 24
    label_h = 34
    panel_w = int(max(image.width for _, image in panels) * scale)
    panel_h = int(max(image.height for _, image in panels) * scale)
    canvas = Image.new("RGB", (panel_w * 3 + pad * 4, panel_h + label_h + pad * 2), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(panels):
        resized = image.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
        x = pad + index * (panel_w + pad)
        y = pad + label_h
        draw.text((x, pad), label, fill="black")
        canvas.paste(resized, (x, y))
    canvas.save(output)


def refresh_review_images(pages: list[dict[str, Any]]) -> None:
    for page in pages:
        page_num = int(page["page"])
        sheet = review_sheet_path(page_num)
        make_comparison_sheet(page, sheet, 0.22)
        page["page_review_sheet"] = str(sheet)
        if page_num in PRIORITY_LABELS:
            make_comparison_sheet(page, fullres_path(page_num), 1.0)


def build_dashboard(report: dict[str, Any], pages: list[dict[str, Any]]) -> str:
    cards = []
    for page in pages:
        page_num = int(page["page"])
        page_id = f"{page_num:03d}"
        label = PRIORITY_LABELS.get(page_num, "")
        priority = "yes" if label else "no"
        card_class = "card priority" if label else "card"
        sheet = page.get("page_review_sheet")
        fullres = str(fullres_path(page_num)) if fullres_path(page_num).exists() else ""
        svg = page.get("primary_review_svg")
        render = page.get("primary_review_render")
        edit_test = page.get("primary_review_edit_test_svg")
        variant = page.get("primary_review_variant", "")
        cards.append(
            f"""
      <article class="{card_class}" data-page="{page_id}" data-priority="{priority}" data-variant="{html.escape(variant)}">
        <header><strong>Page {page_id}</strong>{f'<span>{html.escape(label)}</span>' if label else ''}</header>
        <a class="thumb" href="{html.escape(file_url(sheet), quote=True)}"><img src="{html.escape(file_url(sheet), quote=True)}" loading="lazy" alt="Page {page_id} comparison thumbnail"></a>
        <nav>
          {link("Sheet", sheet)}
          {link("Full-res", fullres)}
          {link("SVG", svg)}
          {link("Render", render)}
          {link("Edit test", edit_test)}
        </nav>
      </article>"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PDFRejuvenator Editable SVG Review Dashboard</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 24px; background: #f5f5f3; color: #151515; }}
  h1 {{ margin: 0 0 6px; font-size: 24px; }}
  .meta {{ margin-bottom: 18px; color: #444; }}
  .controls {{ position: sticky; top: 0; background: #f5f5f3; padding: 12px 0; z-index: 2; display: flex; gap: 10px; align-items: center; border-bottom: 1px solid #ccc; }}
  input, select {{ font-size: 14px; padding: 6px 8px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }}
  .card {{ background: white; border: 1px solid #ccc; padding: 10px; }}
  .card.priority {{ border: 3px solid #aa2b35; }}
  header {{ display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }}
  header span {{ color: #aa2b35; font-weight: 700; }}
  .thumb {{ display: block; border: 1px solid #ddd; background: #eee; }}
  img {{ width: 100%; display: block; }}
  nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 13px; }}
  a {{ color: #064f8a; }}
  .muted {{ color: #777; }}
  .viewer {{ position: fixed; inset: 0; display: none; grid-template-rows: auto 1fr auto; background: rgba(0,0,0,.92); color: white; z-index: 10; }}
  .viewer.open {{ display: grid; }}
  .viewer-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 14px; background: #111; }}
  .viewer-title {{ font-weight: 700; }}
  .viewer-actions {{ display: grid; grid-template-columns: repeat(7, minmax(92px, auto)); align-items: center; gap: 8px; }}
  .viewer button, .viewer a {{ border: 1px solid #777; background: #222; color: white; padding: 7px 10px; font-size: 14px; text-decoration: none; cursor: pointer; }}
  .viewer button:hover, .viewer a:hover {{ background: #333; }}
  .viewer button:disabled, .viewer a.disabled {{ opacity: .42; cursor: default; pointer-events: none; }}
  .viewer-frame {{ display: flex; align-items: center; justify-content: center; overflow: auto; padding: 12px; }}
  .viewer-frame img {{ width: auto; max-width: 100%; max-height: calc(100vh - 118px); background: white; }}
  .viewer-help {{ padding: 8px 14px; background: #111; color: #ccc; font-size: 13px; }}
  .viewer-help strong {{ color: white; }}
</style>
</head>
<body>
<h1>PDFRejuvenator Editable SVG Review Dashboard</h1>
<div class="meta">{len(pages)} pages. Status: {html.escape(str(report.get("status", "unknown")))}. Priority pages are outlined in red. Open full-res links for real typography review.</div>
<div class="controls">
  <label>Page <input id="pageFilter" placeholder="e.g. 012" size="8"></label>
  <label>Show <select id="priorityFilter"><option value="all">All pages</option><option value="priority">Priority only</option></select></label>
</div>
<section class="grid" id="grid">
{''.join(cards)}
</section>
<aside class="viewer" id="viewer" aria-hidden="true">
  <div class="viewer-bar">
    <div class="viewer-title" id="viewerTitle">Page</div>
    <div class="viewer-actions">
      <button type="button" id="prevPage">Previous</button>
      <button type="button" id="nextPage">Next</button>
      <button type="button" id="showSheet">Sheet</button>
      <button type="button" id="showFullres">Full-res</button>
      <a id="openCurrentImage" href="#">Open image</a>
      <a id="openSvg" href="#">SVG</a>
      <button type="button" id="closeViewer">Close</button>
    </div>
  </div>
  <div class="viewer-frame"><img id="viewerImage" alt=""></div>
  <div class="viewer-help">Use Left/Right arrows for previous/next. Esc closes. <strong>Full-res mode stays full-res</strong> and cycles through only pages with full-res review sheets.</div>
</aside>
<script>
const pageInput = document.getElementById('pageFilter');
const prioritySelect = document.getElementById('priorityFilter');
const cards = Array.from(document.querySelectorAll('.card'));
const viewer = document.getElementById('viewer');
const viewerTitle = document.getElementById('viewerTitle');
const viewerImage = document.getElementById('viewerImage');
const showSheet = document.getElementById('showSheet');
const showFullres = document.getElementById('showFullres');
const openCurrentImage = document.getElementById('openCurrentImage');
const openSvg = document.getElementById('openSvg');
let currentIndex = -1;
let currentImageMode = 'sheet';
function applyFilters() {{
  const q = pageInput.value.trim().padStart(pageInput.value.trim() ? 3 : 0, '0');
  const priority = prioritySelect.value;
  for (const card of cards) {{
    const pageOk = !q || card.dataset.page.includes(q);
    const priorityOk = priority === 'all' || card.dataset.priority === 'yes';
    card.style.display = pageOk && priorityOk ? '' : 'none';
  }}
}}
function cardLinks(card) {{
  const links = Array.from(card.querySelectorAll('nav a'));
  const byText = new Map(links.map(a => [a.textContent.trim(), a.href]));
  const sheet = byText.get('Sheet') || card.querySelector('.thumb')?.href || '';
  return {{
    sheet,
    fullres: byText.get('Full-res') || '',
    svg: byText.get('SVG') || '',
  }};
}}
function setViewerImage(card, requestedMode) {{
  const links = cardLinks(card);
  const mode = requestedMode === 'fullres' && links.fullres ? 'fullres' : 'sheet';
  const imageHref = mode === 'fullres' ? links.fullres : links.sheet;
  currentImageMode = mode;
  viewerImage.src = imageHref;
  openCurrentImage.href = imageHref;
  showSheet.disabled = mode === 'sheet';
  showFullres.disabled = !links.fullres || mode === 'fullres';
  showFullres.classList.toggle('disabled', !links.fullres);
  return links;
}}
function showCard(index, mode = currentImageMode) {{
  currentIndex = (index + cards.length) % cards.length;
  const card = cards[currentIndex];
  const page = card.dataset.page;
  const titleExtra = card.querySelector('header span')?.textContent || '';
  const links = setViewerImage(card, mode);
  viewerTitle.textContent = `Page ${{page}}${{titleExtra ? ' - ' + titleExtra : ''}} (${{currentImageMode === 'fullres' ? 'full-res' : 'sheet'}})`;
  viewerImage.alt = `Page ${{page}} comparison sheet`;
  openSvg.href = links.svg;
  openSvg.style.display = links.svg ? '' : 'none';
  viewer.classList.add('open');
  viewer.setAttribute('aria-hidden', 'false');
}}
function closeViewer() {{
  viewer.classList.remove('open');
  viewer.setAttribute('aria-hidden', 'true');
  viewerImage.removeAttribute('src');
}}
function stepViewer(delta) {{
  if (!viewer.classList.contains('open')) return;
  if (currentImageMode === 'fullres') {{
    let index = currentIndex;
    for (let checked = 0; checked < cards.length; checked++) {{
      index = (index + delta + cards.length) % cards.length;
      if (cardLinks(cards[index]).fullres) {{
        showCard(index, 'fullres');
        return;
      }}
    }}
  }}
  showCard(currentIndex + delta, currentImageMode);
}}
pageInput.addEventListener('input', applyFilters);
prioritySelect.addEventListener('change', applyFilters);
cards.forEach((card, index) => {{
  const thumb = card.querySelector('.thumb');
  thumb.addEventListener('click', event => {{
    event.preventDefault();
    showCard(index, 'sheet');
  }});
}});
showSheet.addEventListener('click', () => {{ if (currentIndex >= 0) showCard(currentIndex, 'sheet'); }});
showFullres.addEventListener('click', () => {{ if (currentIndex >= 0) showCard(currentIndex, 'fullres'); }});
document.getElementById('prevPage').addEventListener('click', () => stepViewer(-1));
document.getElementById('nextPage').addEventListener('click', () => stepViewer(1));
document.getElementById('closeViewer').addEventListener('click', closeViewer);
viewer.addEventListener('click', event => {{ if (event.target === viewer) closeViewer(); }});
document.addEventListener('keydown', event => {{
  if (!viewer.classList.contains('open')) return;
  if (event.key === 'Escape') closeViewer();
  if (event.key === 'ArrowLeft') stepViewer(-1);
  if (event.key === 'ArrowRight') stepViewer(1);
}});
</script>
</body>
</html>
"""


def write_manifest(pages: list[dict[str, Any]]) -> None:
    path = PACKET_ROOT / "PDFREJUVENATOR_ALL_PAGES_REVIEW_MANIFEST.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "page",
                "priority_label",
                "primary_review_variant",
                "page_review_sheet",
                "fullres",
                "primary_review_svg",
                "primary_review_render",
                "primary_review_edit_test_svg",
            ],
        )
        writer.writeheader()
        for page in pages:
            page_num = int(page["page"])
            writer.writerow(
                {
                    "page": f"{page_num:03d}",
                    "priority_label": PRIORITY_LABELS.get(page_num, ""),
                    "primary_review_variant": page.get("primary_review_variant", ""),
                    "page_review_sheet": page.get("page_review_sheet", ""),
                    "fullres": str(fullres_path(page_num)) if fullres_path(page_num).exists() else "",
                    "primary_review_svg": page.get("primary_review_svg", ""),
                    "primary_review_render": page.get("primary_review_render", ""),
                    "primary_review_edit_test_svg": page.get("primary_review_edit_test_svg", ""),
                }
            )


def write_defect_log_template() -> None:
    path = PACKET_ROOT / "PDFREJUVENATOR_DEFECT_LOG_TEMPLATE.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "page",
                "severity",
                "artifact",
                "issue",
                "expected",
                "actual",
                "notes",
            ],
        )
        writer.writeheader()


def write_readme(report: dict[str, Any], pages: list[dict[str, Any]]) -> None:
    dashboard = PACKET_ROOT / "pdfrejuvenator_review_dashboard.html"
    lines = [
        "# PDFRejuvenator Review Packet",
        "",
        f"Status: `{report.get('status')}`",
        f"Pages: `{len(pages)}`",
        "",
        f"- Dashboard: `{dashboard}`",
        f"- All-pages manifest: `{PACKET_ROOT / 'PDFREJUVENATOR_ALL_PAGES_REVIEW_MANIFEST.csv'}`",
        f"- Defect log template: `{PACKET_ROOT / 'PDFREJUVENATOR_DEFECT_LOG_TEMPLATE.csv'}`",
        "",
        "The dashboard links use each page's current `primary_review_*` artifacts from the full-book gate report.",
    ]
    (PACKET_ROOT / "README_REVIEW_PACKET.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an editable SVG full-book review packet dashboard.")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--report-stem", default="full_full_book_promotion_rollout")
    args = parser.parse_args()
    configure_paths(args.run_root, args.report_stem)

    report = read_json(GATE_REPORT)
    rollout = read_json(ROLLOUT_REPORT)
    pages = sorted(rollout["pages"], key=lambda item: int(item["page"]))
    PACKET_ROOT.mkdir(parents=True, exist_ok=True)
    refresh_review_images(pages)
    dashboard = PACKET_ROOT / "pdfrejuvenator_review_dashboard.html"
    dashboard.write_text(build_dashboard(report, pages), encoding="utf-8")
    write_manifest(pages)
    write_defect_log_template()
    write_readme(report, pages)
    print(f"dashboard={dashboard}")
    print(f"pages={len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
