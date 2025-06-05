import os
import base64
import uuid
import random
import csv
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
import argparse
import boto3
import shutil

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

def cleanup_s3_from_csv(bucket_name, csv_path):
    s3 = boto3.client('s3')
    objects_to_delete = []

    if os.path.exists(csv_path):
        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"test_xmls/{row['filename']}"
                objects_to_delete.append({'Key': key})

        # Add CSV itself
        objects_to_delete.append({'Key': os.path.basename(csv_path)})

        if objects_to_delete:
            s3.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_to_delete})
            print(f"✅ Deleted {len(objects_to_delete)} objects from s3://{bucket_name}")
        else:
            print("⚠️ No objects found to delete.")
    else:
        print(f"❌ CSV not found: {csv_path}")


def upload_to_s3(file_path, bucket_name, s3_key):
    s3 = boto3.client('s3')
    s3.upload_file(file_path, bucket_name, s3_key)
    print(f"Uploaded {file_path} to s3://{bucket_name}/{s3_key}")


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
    parser = argparse.ArgumentParser(description="Generate XML and optionally upload to S3")
    parser.add_argument("--num", type=int, default=5, help="Number of files to generate")
    parser.add_argument("--upload-s3", action="store_true", help="Upload output files to S3")
    parser.add_argument("--s3-bucket", type=str, help="S3 bucket to upload to")
    parser.add_argument("--cleanup", action="store_true", help="Remove local files after processing")
    parser.add_argument("--cleanup-s3", action="store_true", help="Remove s3 files after processing")
    args = parser.parse_args()

    num_files = int(os.getenv("NUM_FILES", args.num))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with ProcessPoolExecutor() as executor:
        results = list(executor.map(generate_and_update, range(num_files)))

    with open(CSV_FILE, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "filepath", "messageId", "lrn", "timestamp"])
        writer.writerows(results)

    print(f"JMeter CSV saved: {CSV_FILE}")

    s3_keys = []

    # Upload to S3
    if args.upload_s3:
        if not args.s3_bucket:
            print("❌ --s3-bucket is required when using --upload-s3")
            return
        s3_keys.append(os.path.basename(CSV_FILE))
        upload_to_s3(CSV_FILE, args.s3_bucket, os.path.basename(CSV_FILE))
        for _, path, *_ in results:
            key = f"test_xmls/{os.path.basename(path)}"
            s3_keys.append(key)
            upload_to_s3(path, args.s3_bucket, key)

    # Cleanup
    if args.cleanup:
        print("Cleaning up local files...")
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
        if os.path.exists(CSV_FILE):
            os.remove(CSV_FILE)

    # Cleanup S3 if requested
    if args.cleanup_s3:
      if not args.s3_bucket:
        print("❌ --s3-bucket is required with --cleanup-s3")
      else:
        cleanup_s3_from_csv(args.s3_bucket, CSV_FILE)



if __name__ == "__main__":
    main()
