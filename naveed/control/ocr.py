"""Optional text-on-screen lookup, used to resolve "click the Save button".

OCR is deliberately optional: Naveed works without it (the planner supplies
coordinates), and uses it only to turn a *named* target into a point.  Backends
are tried in order of availability and cost:

``pytesseract``  best quality if Tesseract is installed;
``rapidocr``     bundled models via ``rapidocr-onnxruntime``;
``easyocr``      heaviest, last resort.

With none installed the caller gets an empty list and reports an honest "I could
not find that on screen" instead of clicking blindly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence

from .. import lazy

__all__ = ["TextMatch", "find_text", "read_text", "ocr_backends"]


@dataclass
class TextMatch:
    """One piece of recognised text and where it is in the image."""

    text: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float = 0.0

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self):
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)


def ocr_backends() -> List[str]:
    """Installed OCR backends, in preference order."""
    found: List[str] = []
    if lazy.find_spec_safe("pytesseract") is not None:
        found.append("pytesseract")
    if lazy.find_spec_safe("rapidocr_onnxruntime") is not None or lazy.find_spec_safe("rapidocr") is not None:
        found.append("rapidocr")
    if lazy.find_spec_safe("easyocr") is not None:
        found.append("easyocr")
    return found


def read_text(image: Any, *, language: str = "eng", limit: int = 400) -> List[TextMatch]:
    """Recognise text in a PIL/Qt image. Returns ``[]`` when OCR is unavailable."""
    for backend in ocr_backends():
        try:
            if backend == "pytesseract":
                return _read_pytesseract(image, language=language, limit=limit)
            if backend == "rapidocr":
                return _read_rapidocr(image, limit=limit)
            if backend == "easyocr":
                return _read_easyocr(image, limit=limit)
        except Exception:
            continue
    return []


def find_text(image: Any, needle: str, *, language: str = "eng", fuzzy: bool = True) -> List[TextMatch]:
    """Locate *needle* in the image, best match first (OCR required)."""
    target = " ".join(needle.lower().split())
    if not target:
        return []
    matches: List[TextMatch] = []
    for item in read_text(image, language=language):
        text = " ".join(item.text.lower().split())
        if not text:
            continue
        if text == target:
            item.confidence = max(item.confidence, 1.0)
            matches.append(item)
        elif fuzzy and (target in text or text in target):
            item.confidence = max(item.confidence, 0.7)
            matches.append(item)
    matches.sort(key=lambda match: (-match.confidence, match.height))
    return matches


def _to_pil(image: Any) -> Any:
    """Normalise a Qt image to PIL without importing Qt when unnecessary."""
    if hasattr(image, "convert"):
        return image
    PILImage = lazy.load("PIL.Image", extra="capture")
    QtCore = lazy.load("PySide6.QtCore", extra="ui")
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    import io

    return PILImage.open(io.BytesIO(bytes(buffer.data()))).convert("RGB")


def _read_pytesseract(image: Any, *, language: str, limit: int) -> List[TextMatch]:
    pytesseract = lazy.load("pytesseract")
    data = pytesseract.image_to_data(_to_pil(image), lang=language, output_type=pytesseract.Output.DICT)
    matches: List[TextMatch] = []
    for index, text in enumerate(data.get("text", [])):
        stripped = (text or "").strip()
        if not stripped:
            continue
        try:
            confidence = float(data["conf"][index]) / 100.0
        except (KeyError, TypeError, ValueError):
            confidence = 0.0
        if confidence <= 0:
            continue
        matches.append(
            TextMatch(
                text=stripped,
                left=float(data["left"][index]),
                top=float(data["top"][index]),
                right=float(data["left"][index] + data["width"][index]),
                bottom=float(data["top"][index] + data["height"][index]),
                confidence=confidence,
            )
        )
        if len(matches) >= limit:
            break
    return matches


def _read_rapidocr(image: Any, *, limit: int) -> List[TextMatch]:
    module = None
    for name in ("rapidocr_onnxruntime", "rapidocr"):
        module = lazy.optional(name)
        if module is not None:
            break
    if module is None:
        return []
    engine = module.RapidOCR()
    result = engine(_to_pil(image))
    matches: List[TextMatch] = []
    rows: Sequence[Any] = result[0] if isinstance(result, tuple) else result
    for row in rows or []:
        try:
            box, text, confidence = row[0], row[1], float(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        matches.append(TextMatch(text=str(text), left=min(xs), top=min(ys), right=max(xs), bottom=max(ys), confidence=confidence))
        if len(matches) >= limit:
            break
    return matches


def _read_easyocr(image: Any, *, limit: int) -> List[TextMatch]:
    easyocr = lazy.load("easyocr")
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    matches: List[TextMatch] = []
    for box, text, confidence in reader.readtext(_to_pil(image).__array__() if hasattr(_to_pil(image), "__array__") else _to_pil(image)):
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        matches.append(TextMatch(text=str(text), left=min(xs), top=min(ys), right=max(xs), bottom=max(ys), confidence=float(confidence)))
        if len(matches) >= limit:
            break
    return matches
