@echo off
setlocal
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install PyMuPDF Pillow reportlab pypdf rapidocr-onnxruntime opencv-python-headless python-docx fonttools
echo.
echo PDFRejuvenator dependencies installed.
echo Run: process_pdf.bat "PATH\TO\SOURCE.pdf"
endlocal
