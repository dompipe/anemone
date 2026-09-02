from pathlib import Path
import base64, hashlib

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "archive"
OUT = ROOT / "anemone_background_3word.zip"
EXPECTED_SHA256 = "75757f40dcffbbe41ff6204c8895b64a322381d2d079db2086e5b6db5adf235b"

parts = sorted(ARCHIVE.glob("anemone_background_3word.zip.b64.part*"))
if not parts:
    raise SystemExit("No archive parts found")

payload = "".join(p.read_text(encoding="ascii").strip() for p in parts)
raw = base64.b64decode(payload, validate=True)
OUT.write_bytes(raw)

actual = hashlib.sha256(raw).hexdigest()
if actual != EXPECTED_SHA256:
    OUT.unlink(missing_ok=True)
    raise SystemExit(f"SHA256 mismatch: {actual}")

print(f"Wrote {OUT} ({len(raw)} bytes)")
print(f"SHA256 {actual}")
