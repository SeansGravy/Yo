"""Helpers for generating sample ingestion files without shipping binaries."""
from __future__ import annotations

import base64
from pathlib import Path

SAMPLE_PDF_CONTENT = """%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 55 >>
stream
BT
/F1 24 Tf
72 720 Td
(Hello from Yo PDF fixture.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000062 00000 n 
0000000118 00000 n 
0000000247 00000 n 
0000000381 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
457
%%EOF
"""

SAMPLE_XLSX_BASE64 = (
    "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"
)


def write_sample_pdf(path: Path, overwrite: bool = False) -> Path:
    """Write the sample PDF to ``path`` if it doesn't already exist."""
    if path.exists() and not overwrite:
        return path
    path.write_bytes(SAMPLE_PDF_CONTENT.encode("utf-8"))
    return path


def write_sample_xlsx(path: Path, overwrite: bool = False) -> Path:
    """Write the sample XLSX to ``path`` if it doesn't already exist."""
    if path.exists() and not overwrite:
        return path
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:
        data = base64.b64decode(SAMPLE_XLSX_BASE64)
        path.write_bytes(data)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "YoData"
        ws.append(["Topic", "Summary"])
        ws.append(["LangChain", "Composable RAG workflows."])
        ws.append(["Milvus Lite", "Embedded vector store for local recall."])
        ws.append(["Yo", "Your local-second-brain CLI."])
        wb.save(path)
    return path


def ensure_ingest_samples(base_dir: Path | None = None) -> dict[str, Path]:
    """Ensure the standard fixtures exist and return their paths."""
    root = base_dir or Path(__file__).resolve().parents[1] / "fixtures" / "ingest"
    root.mkdir(parents=True, exist_ok=True)
    pdf_path = root / "brochure.pdf"
    xlsx_path = root / "sample.xlsx"
    write_sample_pdf(pdf_path)
    write_sample_xlsx(xlsx_path)
    return {"pdf": pdf_path, "xlsx": xlsx_path}
