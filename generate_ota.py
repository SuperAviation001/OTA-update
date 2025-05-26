# === Auto-install required packages ===
import subprocess
import sys

for package in ['dropbox', 'tqdm']:
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Installing missing package: {package}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# === Standard imports ===
import os
import hashlib
import json
import dropbox
from tqdm import tqdm
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# === Configuration ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.txt")
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB

def load_access_token():
    if not os.path.isfile(TOKEN_FILE):
        print(f"❌ '{TOKEN_FILE}' not found. Please create it and paste your Dropbox access token inside.")
        sys.exit(1)
    with open(TOKEN_FILE, "r") as f:
        token = f.read().strip()
        if not token:
            print(f"❌ '{TOKEN_FILE}' is empty.")
            sys.exit(1)
        return token

def make_direct_download_link(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query['dl'] = ['1']
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

def sha256sum(filename):
    h = hashlib.sha256()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def upload_to_dropbox(local_path, dropbox_folder, access_token):
    dbx = dropbox.Dropbox(access_token)
    filename = os.path.basename(local_path)

    # Upload path: /<codename>/<filename>
    dropbox_path = f"/{dropbox_folder}/{filename}".replace("//", "/")

    file_size = os.path.getsize(local_path)
    print(f"📤 Uploading '{filename}' to Dropbox path: {dropbox_path} ({file_size / (1024 * 1024):.2f} MB)")

    with open(local_path, "rb") as f:
        if file_size <= CHUNK_SIZE:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        else:
            upload_session_start_result = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=CHUNK_SIZE)
            commit = dropbox.files.CommitInfo(path=dropbox_path, mode=dropbox.files.WriteMode.overwrite)

            offset = CHUNK_SIZE
            with tqdm(total=file_size, unit='B', unit_scale=True, desc='Uploading') as pbar:
                pbar.update(CHUNK_SIZE)

                while offset < file_size:
                    chunk = f.read(CHUNK_SIZE)
                    if (file_size - offset) <= CHUNK_SIZE:
                        dbx.files_upload_session_finish(chunk, cursor, commit)
                        pbar.update(len(chunk))
                        offset += len(chunk)
                    else:
                        dbx.files_upload_session_append_v2(chunk, cursor)
                        offset += len(chunk)
                        cursor.offset = offset
                        pbar.update(len(chunk))

    try:
        link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_path)
    except dropbox.exceptions.ApiError as e:
        if e.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=dropbox_path).links
            if links:
                link_metadata = links[0]
            else:
                print("⚠️ Failed to retrieve existing shared link.")
                sys.exit(1)
        else:
            print(f"❌ Failed to create shared link: {e}")
            sys.exit(1)

    direct_link = make_direct_download_link(link_metadata.url)
    print("✅ Direct Download Link:")
    print(direct_link)
    return direct_link

def main():
    access_token = load_access_token()

    codename = input("Enter device codename (e.g. PL2, miatoll): ").strip()
    ota_dir = os.path.join("out", "target", "product", codename)

    try:
        files = [f for f in os.listdir(ota_dir) if f.startswith("AndroidOne-") and codename in f and f.endswith(".zip")]
    except FileNotFoundError:
        print(f"❌ OTA directory not found: {ota_dir}")
        sys.exit(1)

    if not files:
        print(f"❌ No OTA zip found in {ota_dir} matching pattern AndroidOne-*{codename}-*.zip")
        sys.exit(1)

    filename = files[0]
    file_path = os.path.join(ota_dir, filename)
    print(f"📦 Found OTA package: {file_path}")

    build_prop = os.path.join(ota_dir, "system", "build.prop")
    datetime = "UNKNOWN"
    if os.path.isfile(build_prop):
        with open(build_prop) as f:
            for line in f:
                if line.startswith("ro.build.date.utc="):
                    datetime = line.strip().split("=")[1]
                    break

    file_id = sha256sum(file_path)
    file_size = os.path.getsize(file_path)
    version = "15"  # Adjust this if needed

    dropbox_link = upload_to_dropbox(file_path, codename, access_token)

    output_dir = os.path.join(SCRIPT_DIR, "devices")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{codename}.json")

    ota_json = {
        "response": [
            {
                "datetime": datetime,
                "filename": filename,
                "id": file_id,
                "size": file_size,
                "url": dropbox_link,
                "version": version
            }
        ]
    }

    with open(output_file, "w") as f:
        json.dump(ota_json, f, indent=2)

    print(f"📄 OTA JSON saved to: {output_file}")

if __name__ == "__main__":
    main()
