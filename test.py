import os
import random

output_dir = "generated_pdfs"
os.makedirs(output_dir, exist_ok=True)

# Minimal valid PDF header/footer
PDF_HEADER = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 24 Tf 100 700 Td (Dummy PDF) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000010 00000 n 
0000000061 00000 n 
0000000117 00000 n 
0000000215 00000 n 
trailer
<< /Root 1 0 R /Size 5 >>
startxref
308
%%EOF
"""

def create_dummy_pdf(path, target_size_kb):
    with open(path, "wb") as f:
        f.write(PDF_HEADER)
        current_size = f.tell()
        remaining = (target_size_kb * 1024) - current_size
        if remaining > 0:
            f.write(os.urandom(remaining))  # fast random bytes
    print(f"Created {path} ({target_size_kb} KB)")

# Generate 50 dummy PDFs between 512KB and 10MB
for i in range(50):
    size_kb = random.randint(512, 10240)
    filename = f"sample_{i+1:03d}_{size_kb}KB.pdf"
    create_dummy_pdf(os.path.join(output_dir, filename), size_kb)
