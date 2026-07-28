"""
OCR via Apple Vision framework (pyobjc).
Accurate, local, no network, works natively on macOS.
"""
from pathlib import Path


def extract_text(image_path: Path) -> str:
    """
    Run Apple Vision text recognition on an image.
    Returns all recognized text joined by newlines.
    Falls back to empty string on any error.
    """
    try:
        import Vision
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(str(image_path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})

        request = Vision.VNRecognizeTextRequest.alloc().init()
        # Accurate mode — slightly slower than Fast but worth it for good OCR
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        success, error = handler.performRequests_error_([request], None)
        if not success or error:
            return ""

        lines = []
        for obs in request.results() or []:
            candidates = obs.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))

        return "\n".join(lines)

    except Exception as exc:
        print(f"[ocr] error: {exc}")
        return ""
