from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yo.brain as brain_module
from yo.brain import IngestionError, MissingDependencyError, YoBrain
from yo.logging_utils import get_logger
from yo.sample_files import write_sample_xlsx


class StubLoader:
    def __init__(self, path: str) -> None:
        self.path = path
        self._documents = [SimpleNamespace(page_content="stub", metadata={"source": path})]

    def load(self):  # noqa: D401 - simple stub loader
        return list(self._documents)


def _blank_brain() -> YoBrain:
    brain = object.__new__(YoBrain)  # type: ignore[call-arg, return-value]
    brain._logger = get_logger("yo.tests")  # type: ignore[attr-defined]
    brain.data_dir = Path(".")  # type: ignore[attr-defined]
    brain.cache_path = Path("web_cache_test.json")  # type: ignore[attr-defined]
    brain.meta_path = Path("namespace_meta_test.json")  # type: ignore[attr-defined]
    brain.state_path = Path("namespace_state_test.json")  # type: ignore[attr-defined]
    brain.active_namespace = "default"  # type: ignore[attr-defined]
    brain.model_selection = SimpleNamespace(spec="ollama:llama3", provider="ollama", model="llama3")  # type: ignore[attr-defined]
    brain.embedding_selection = SimpleNamespace(
        spec="ollama:nomic-embed-text",
        provider="ollama",
        model="nomic-embed-text",
    )  # type: ignore[attr-defined]
    brain.model_provider = "ollama"  # type: ignore[attr-defined]
    brain.embed_provider = "ollama"  # type: ignore[attr-defined]
    brain.model_name = "llama3"  # type: ignore[attr-defined]
    brain.embed_model = "nomic-embed-text"  # type: ignore[attr-defined]
    brain.config = SimpleNamespace(
        namespace="default",
        model_spec="ollama:llama3",
        embed_model_spec="ollama:nomic-embed-text",
        data_dir=Path("."),
    )  # type: ignore[attr-defined]
    return brain


def test_load_pdf_documents_uses_pdf_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nSample")

    monkeypatch.setattr(YoBrain, "_ensure_dependency", lambda self, module, hint: None)
    monkeypatch.setattr(YoBrain, "_ensure_chardet", lambda self: None)

    calls: list[str] = []

    class PDFLoader(StubLoader):
        def __init__(self, path: str) -> None:
            calls.append(path)
            super().__init__(path)

    monkeypatch.setattr(brain_module, "UnstructuredPDFLoader", PDFLoader)

    brain = _blank_brain()
    documents = YoBrain._load_file_documents(brain, pdf_path)

    assert calls == [str(pdf_path)]
    assert documents and documents[0].page_content == "stub"


def test_load_excel_documents_uses_excel_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    excel_path = tmp_path / "sheet.xlsx"
    write_sample_xlsx(excel_path, overwrite=True)

    monkeypatch.setattr(YoBrain, "_ensure_dependency", lambda self, module, hint: None)
    monkeypatch.setattr(YoBrain, "_ensure_chardet", lambda self: None)

    calls: list[str] = []

    class ExcelLoader(StubLoader):
        def __init__(self, path: str) -> None:
            calls.append(path)
            super().__init__(path)

    monkeypatch.setattr(brain_module, "UnstructuredExcelLoader", ExcelLoader)

    brain = _blank_brain()
    documents = YoBrain._load_file_documents(brain, excel_path)

    assert calls == [str(excel_path)]
    assert documents and documents[0].page_content == "stub"


def test_missing_chardet_raises_dependency_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "needs_chardet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nSample")

    monkeypatch.setattr(YoBrain, "_ensure_dependency", lambda self, module, hint: None)
    monkeypatch.setattr(brain_module, "chardet", None)
    monkeypatch.setattr(brain_module, "UnstructuredPDFLoader", StubLoader)

    brain = _blank_brain()

    with pytest.raises(MissingDependencyError) as excinfo:
        YoBrain._load_file_documents(brain, pdf_path)

    assert "chardet" in str(excinfo.value)


def test_pdf_loader_binary_error_produces_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "needs_extra.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nSample")

    monkeypatch.setattr(YoBrain, "_ensure_dependency", lambda self, module, hint: None)
    monkeypatch.setattr(YoBrain, "_ensure_chardet", lambda self: None)

    class FailingLoader(StubLoader):
        def load(self):  # type: ignore[override]
            raise ValueError("Binary files are not supported")

    monkeypatch.setattr(brain_module, "UnstructuredPDFLoader", FailingLoader)

    brain = _blank_brain()

    with pytest.raises(IngestionError) as excinfo:
        YoBrain._load_file_documents(brain, pdf_path)

    message = str(excinfo.value)
    assert "unstructured" in message
    assert "GitHub" in message


def test_excel_loader_binary_error_produces_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    xlsx_path = tmp_path / "needs_extra.xlsx"
    xlsx_path.write_bytes(b"PK\x03\x04")

    monkeypatch.setattr(YoBrain, "_ensure_dependency", lambda self, module, hint: None)
    monkeypatch.setattr(YoBrain, "_ensure_chardet", lambda self: None)

    class FailingLoader(StubLoader):
        def load(self):  # type: ignore[override]
            raise ValueError("Binary files are not supported")

    monkeypatch.setattr(brain_module, "UnstructuredExcelLoader", FailingLoader)

    brain = _blank_brain()

    with pytest.raises(IngestionError) as excinfo:
        YoBrain._load_file_documents(brain, xlsx_path)

    message = str(excinfo.value)
    assert "unstructured" in message
    assert "openpyxl" in message
    assert "GitHub" in message


def test_unsupported_extension_raises_ingestion_error(tmp_path: Path) -> None:
    brain = _blank_brain()
    odd_file = tmp_path / "archive.zip"
    odd_file.write_bytes(b"binary")

    with pytest.raises(IngestionError) as excinfo:
        YoBrain._load_file_documents(brain, odd_file)

    assert "Unsupported file type" in str(excinfo.value)
