import os
import base64
import uuid
import random
import csv
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
import argparse

# Constants
BASE_XML = "ie.xml"
OUTPUT_DIR = "test_xmls"
CSV_FILE = "jmeter_data.csv"
NUM_FILES = 5

def generate_pdf_of_size(path: str, size_mb: float):
    with open(path, "wb") as f:
        f.write(b'%PDF-1.4\n')
        while f.tell() < size_mb * 1024 * 1024:
            f.write(os.urandom(1024))
        f.write(b'\n%%EOF')

def generate_and_update(i):
    size_mb = round(random.uniform(1, 9.5), 1)
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    compact = now.strftime("%Y%m%d%H%M%S")

    pdf_filename = f"IE3F32_{size_mb}MB_{compact}_{i}.pdf"
    xml_filename = os.path.join(OUTPUT_DIR, f"ie_updated_{size_mb}MB_{compact}_{i}.xml")
    full_path = os.path.abspath(xml_filename)

    message_id = f"TEST-MSG-ID{uuid.uuid4()}"
    lrn = f"{compact}_001LRN"

    generate_pdf_of_size(pdf_filename, size_mb)

    with open(pdf_filename, "rb") as pdf_file:
        encoded_pdf = base64.b64encode(pdf_file.read()).decode("utf-8")

    ns = {'ns': 'urn:wco:datamodel:WCO:CIS:1'}
    ET.register_namespace('', ns['ns'])
    tree = ET.parse(BASE_XML)
    root = tree.getroot()

    def set_text(tag_path, text):
        tag = root.find(tag_path, ns)
        if tag is not None:
            tag.text = text

    set_text(".//ns:content", encoded_pdf)
    set_text(".//ns:filename", pdf_filename)
    set_text(".//ns:MessageId", message_id)
    set_text(".//ns:LRN", lrn)
    set_text(".//ns:Timestamp", timestamp)
    set_text(".//ns:documentIssueDate/ns:DateTime", timestamp)

    tree.write(xml_filename, encoding="utf-8", xml_declaration=True)
    os.remove(pdf_filename)

    # Return fields for JMeter CSV
    return (pdf_filename, full_path, message_id, lrn, timestamp)

def main():
    parser = argparse.ArgumentParser(description="Generate XML and PDF files for MQ load testing.")
    parser.add_argument("--num", type=int, default=5, help="Number of XML/PDF files to generate.")
    args = parser.parse_args()
     # Allow ENV to override CLI arg
    num_files = int(os.getenv("NUM_FILES", args.num))

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with ProcessPoolExecutor() as executor:
        results = list(executor.map(generate_and_update, range(num_files)))

    with open(CSV_FILE, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "filepath", "messageId", "lrn", "timestamp"])
        writer.writerows(results)

    print(f"JMeter CSV saved: {CSV_FILE}")

if __name__ == "__main__":
    main()
