python - <<'PY'
import csv
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(
    input("/Users/priyanshu/Desktop/coback-gap-analysis/data/COBACK_Marenthal_Inputs").strip()
).expanduser().resolve()

manifest = root / "document_starters.csv"

if not manifest.is_file():
    raise SystemExit(f"Manifest not found: {manifest}")

with manifest.open(encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))

paths = []
for row in rows:
    path = (root / row["file"]).resolve()
    if not path.is_relative_to(root):
        raise SystemExit(f"Unsafe path in manifest: {row['file']}")
    paths.append(path)

missing = [path for path in paths if not path.is_file()]
if missing:
    raise SystemExit(
        "Missing starter documents:\n"
        + "\n".join(str(path) for path in missing)
    )

output = root / "coback_starter_documents.zip"

with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
    archive.write(manifest, arcname=manifest.name)
    for path in paths:
        archive.write(path, arcname=path.relative_to(root))

print(f"\nCreated: {output}")
print(f"Included {len(paths)} starter documents and their manifest.")
PY
