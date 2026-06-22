"""Extract text from the attached DOCX."""
import zipfile
import sys
from xml.etree import ElementTree as ET

path = r"C:\Users\ahernz\github_for_aimsun\Coordinated_TSP_Implementation_Direction_Jun.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

with zipfile.ZipFile(path) as z:
    with z.open("word/document.xml") as f:
        xml = f.read().decode("utf-8")

root = ET.fromstring(xml)
out_lines = []
for p in root.iter(W + "p"):
    parts = []
    for t in p.iter(W + "t"):
        if t.text:
            parts.append(t.text)
    line = "".join(parts).strip()
    if line:
        out_lines.append(line)

# Also dump headings with style if available
print("\n".join(out_lines))
