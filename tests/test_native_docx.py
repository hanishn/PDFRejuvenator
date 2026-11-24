
import fitz
import pytest
from docx import Document

from pdfrejuvenator.native_docx import convert_pdf, validate_destination


def synthetic_pdf(path):
    with fitz.open() as pdf:
        page = pdf.new_page()
        for row in range(12):
            page.insert_text((40, 60 + row * 16), f"Left synthetic row {row}")
            page.insert_text((330, 60 + row * 16), f"Right synthetic row {row}")
        pdf.save(path)


def test_columns_remain_native_and_in_reading_order(tmp_path):
    source = tmp_path / "synthetic.pdf"
    synthetic_pdf(source)
    result = convert_pdf(source, tmp_path / "output")
    text = [p.text for p in Document(result["docx"]).paragraphs if p.text]
    assert text == ([f"Left synthetic row {i}" for i in range(12)] +
                    [f"Right synthetic row {i}" for i in range(12)])
    assert result["pages"][0]["layout"] == "two_column_prose"
    assert result["runtimeInference"] is False


def test_coordinate_grid_retains_every_row(tmp_path):
    import hashlib
    import json

    source = tmp_path / "synthetic.pdf"
    synthetic_pdf(source)
    correction = tmp_path / "rules.json"
    correction.write_text(json.dumps({
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "pages": {"1": {"columnBounds": [0, 300, 600], "rowTolerance": 16}},
    }))
    result = convert_pdf(source, tmp_path / "output", corrections=correction)
    table = Document(result["docx"]).tables[0]
    assert len(table.rows) == 12
    assert table.rows[-1].cells[0].text == "Left synthetic row 11"
    assert table.rows[-1].cells[1].text == "Right synthetic row 11"


def test_hash_mismatch_and_invalid_pages_write_nothing(tmp_path):
    source = tmp_path / "synthetic.pdf"
    synthetic_pdf(source)
    rules = tmp_path / "rules.json"
    rules.write_text('{"sourceSha256": "wrong", "pages": {}}')
    with pytest.raises(ValueError, match="correction_source_hash_mismatch"):
        convert_pdf(source, tmp_path / "output", corrections=rules)
    with pytest.raises(ValueError, match="page_selector_out_of_range"):
        convert_pdf(source, tmp_path / "output", pages="2")
    assert not (tmp_path / "output").exists()


def test_forbidden_destinations(tmp_path):
    with pytest.raises(ValueError, match="clairvoyance"):
        validate_destination(tmp_path / "Clairvoyance" / "scratch")
    repo = tmp_path / "repository"
    repo.mkdir()
    (repo / ".git").mkdir()
    with pytest.raises(ValueError, match="repository"):
        validate_destination(repo / "output")


def test_numeric_text_and_raster_only_page_are_retained(tmp_path):
    source = tmp_path / "synthetic.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 60), "12345")
        raster = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80), False)
        raster.clear_with(128)
        page = pdf.new_page()
        page.insert_image(fitz.Rect(40, 40, 200, 200), pixmap=raster)
        pdf.save(source)
    result = convert_pdf(source, tmp_path / "output")
    document = Document(result["docx"])
    assert "12345" in [p.text for p in document.paragraphs]
    assert len(document.inline_shapes) == 1
    assert result["pages"][1]["requiresOcr"] is True
