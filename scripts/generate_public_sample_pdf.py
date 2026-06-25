from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "samples" / "shadow_power_play_sample.pdf"


class SceneBox(Flowable):
    def __init__(self, label: str, width: float = 3.05 * inch, height: float = 1.2 * inch) -> None:
        super().__init__()
        self.label = label
        self.width = width
        self.height = height

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return min(self.width, available_width), self.height

    def draw(self) -> None:
        canvas = self.canv
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#3f4a56"))
        canvas.setFillColor(colors.HexColor("#eef2f6"))
        canvas.rect(0, 0, self.width, self.height, fill=1, stroke=1)
        canvas.setStrokeColor(colors.HexColor("#7b8794"))
        canvas.line(0.12 * inch, 0.12 * inch, self.width - 0.12 * inch, self.height - 0.12 * inch)
        canvas.line(0.12 * inch, self.height - 0.12 * inch, self.width - 0.12 * inch, 0.12 * inch)
        canvas.setFillColor(colors.HexColor("#26313d"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(self.width / 2, self.height / 2 - 3, self.label)
        canvas.restoreState()


def add_page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#66717d"))
    canvas.drawRightString(7.5 * inch, 0.45 * inch, f"Shadow Power Play sample - page {doc.page}")
    canvas.restoreState()


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#1f2a36"),
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#4d5b68"),
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#24313f"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#394859"),
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=9.5,
            leading=12.5,
            firstLineIndent=10,
            spaceAfter=5,
        ),
        "box": ParagraphStyle(
            "box",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            leftIndent=6,
            rightIndent=6,
            spaceBefore=3,
            spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            spaceAfter=3,
        ),
    }


def boxed_text(text: str, style: ParagraphStyle) -> Table:
    table = Table([[Paragraph(text, style)]], colWidths=[3.05 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f1e7")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#806b3a")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def data_table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#26313d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("LEADING", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aa5b1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fbfcfd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_story() -> list:
    s = styles()
    story: list = [
        Paragraph("Shadow Power Play", s["title"]),
        Paragraph(
            "A synthetic public PDFRejuvenator sample adventure. All names, places, factions, and rules text are "
            "original placeholder material for testing PDF-to-editable-SVG conversion.",
            s["subtitle"],
        ),
        Paragraph("Overview", s["h1"]),
        Paragraph(
            "Night Harbor is one bad week from a blackout. A private security contractor, a civic reform group, "
            "and an underground courier network are all chasing the same stolen grid ledger. The player characters "
            "arrive when the ledger changes hands during a rain-soaked fundraiser.",
            s["body"],
        ),
        boxed_text(
            "<b>Read Aloud:</b> Thunder rolls over the old transit hall. The lights dim, recover, and dim again. "
            "Across the room, a silver case changes hands under the balcony while every camera in the hall turns "
            "toward the wrong door.",
            s["box"],
        ),
        Spacer(1, 8),
        Paragraph("Opening Beats", s["h2"]),
        data_table(
            [
                ["Beat", "Pressure", "Clue"],
                ["1", "Guests panic as lights fail in sequence.", "A relay tag blinks under the catering table."],
                ["2", "A courier flees through the service corridor.", "The courier carries a false case."],
                ["3", "Security locks the public exits.", "The real case was swapped before the lockdown."],
                ["4", "A city engineer asks for protection.", "Her badge opens the substation gate."],
            ],
            [0.35 * inch, 1.35 * inch, 1.35 * inch],
        ),
        Spacer(1, 8),
        SceneBox("Transit Hall Map Placeholder"),
        Paragraph("Faction Clock", s["h1"]),
        Paragraph(
            "Advance one clock segment whenever the group spends too long, makes a loud move, or leaves a clue "
            "behind. At six segments, the contractor frames the courier network and triggers a controlled outage.",
            s["body"],
        ),
        data_table(
            [
                ["Clock", "Event"],
                ["1", "Contractor drones sweep nearby alleys."],
                ["2", "The civic reform group leaks partial ledger pages."],
                ["3", "A decoy repair crew enters the east substation."],
                ["4", "The stolen ledger is copied to a rooftop relay."],
                ["5", "Police scanners report a citywide power threat."],
                ["6", "The blackout begins in three districts."],
            ],
            [0.55 * inch, 2.45 * inch],
        ),
        PageBreak(),
        Paragraph("Keyed Locations", s["h1"]),
        Paragraph("A. Transit Hall Balcony", s["h2"]),
        Paragraph(
            "The balcony overlooks the fundraiser floor and offers direct access to the lighting booth. A careful "
            "search finds a patched control cable and a strip of black cloth caught in the railing.",
            s["body"],
        ),
        Paragraph("B. Service Corridor", s["h2"]),
        Paragraph(
            "The corridor is cramped, wet, and loud with old pipes. It is useful for chases because sightlines are "
            "short and every junction has at least two ways out.",
            s["body"],
        ),
        Paragraph("C. East Substation", s["h2"]),
        Paragraph(
            "This fenced brick building houses the relay hardware. The alarm panel accepts the city engineer's badge, "
            "but opening the inner cage starts a three-minute silent alarm.",
            s["body"],
        ),
        data_table(
            [
                ["Obstacle", "Simple Approach", "Complication"],
                ["Fence", "Climb, cut, or use a badge.", "A patrol vehicle turns the corner."],
                ["Relay Cage", "Bypass the keypad.", "The keypad records failed attempts."],
                ["Ledger Cache", "Pull the drive from bay seven.", "The drive is mirrored to a rooftop relay."],
            ],
            [0.85 * inch, 1.1 * inch, 1.1 * inch],
        ),
        Spacer(1, 8),
        SceneBox("Substation Diagram Placeholder"),
        Paragraph("Sample NPC Blocks", s["h1"]),
        data_table(
            [
                ["Name", "Role", "Want", "Tell"],
                ["Mara Venn", "City engineer", "Keep the grid online", "Always checks exits before speaking."],
                ["Jon Vale", "Courier broker", "Recover the real ledger", "Knows who hired the decoy crew."],
                ["Director Hale", "Security executive", "Own the public story", "Uses calm language when cornered."],
            ],
            [0.78 * inch, 0.78 * inch, 0.88 * inch, 0.78 * inch],
        ),
        PageBreak(),
        Paragraph("Resolution Paths", s["h1"]),
        Paragraph(
            "The adventure ends when the characters control the ledger, expose the frame-up, or choose which faction "
            "gets the evidence. The strongest ending gives the city engineer enough proof to halt the outage without "
            "handing full control to any one faction.",
            s["body"],
        ),
        data_table(
            [
                ["Outcome", "Public Result", "Follow-Up Hook"],
                ["Ledger published", "The contractor loses the city bid.", "Someone edits one page before release."],
                ["Ledger withheld", "The outage is prevented quietly.", "The civic group demands transparency."],
                ["Ledger traded", "One faction gains leverage.", "A second ledger appears with different numbers."],
            ],
            [0.85 * inch, 1.1 * inch, 1.1 * inch],
        ),
        Spacer(1, 8),
        boxed_text(
            "<b>Design Note:</b> This sample intentionally contains multi-column prose, tables, boxed text, page "
            "numbers, and placeholder art boxes so PDFRejuvenator has public material to process and validate.",
            s["box"],
        ),
        Paragraph("Conversion Stress Checklist", s["h1"]),
        data_table(
            [
                ["Feature", "Present"],
                ["Paragraph text with indentation", "Yes"],
                ["Repeated table headers", "Yes"],
                ["Boxed read-aloud text", "Yes"],
                ["Placeholder images", "Yes"],
                ["Mixed fonts and page footer", "Yes"],
            ],
            [1.6 * inch, 1.4 * inch],
        ),
    ]
    return story


def build_pdf(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
    )
    frame_gap = 0.2 * inch
    column_width = (letter[0] - document.leftMargin - document.rightMargin - frame_gap) / 2
    frames = [
        Frame(document.leftMargin, document.bottomMargin, column_width, document.height, id="left"),
        Frame(document.leftMargin + column_width + frame_gap, document.bottomMargin, column_width, document.height, id="right"),
    ]
    document.addPageTemplates([PageTemplate(id="two_column", frames=frames, onPage=add_page_number)])
    document.build(build_story())
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the public PDFRejuvenator sample PDF.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = build_pdf(args.output.resolve())
    print(f"SAMPLE_PDF={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
