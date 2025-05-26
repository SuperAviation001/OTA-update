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

def check_file_exists(dbx, dropbox_path):
    try:
        dbx.files_get_metadata(dropbox_path)
        return True
    except dropbox.exceptions.ApiError:
        return False

def get_or_create_shared_link(dbx, dropbox_path):
    try:
        links = dbx.sharing_list_shared_links(path=dropbox_path).links
        if links:
            return make_direct_download_link(links[0].url)
        else:
            link_metadata = dbx.sharing_create_shared_link_with_settings(dropbox_path)
            return make_direct_download_link(link_metadata.url)
    except dropbox.exceptions.ApiError as e:
        print(f"⚠️ Could not get or create shared link for {dropbox_path}: {e}")
        return None

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

    return get_or_create_shared_link(dbx, dropbox_path)

def main():
    args = sys.argv[1:]
    no_upload = "--no-upload" in args
    codename_arg = next((arg for arg in args if not arg.startswith("--")), None)

    access_token = load_access_token()
    dbx = dropbox.Dropbox(access_token)

    codename = codename_arg.strip() if codename_arg else input("Enter device codename (e.g. PL2, miatoll): ").strip()
    ota_dir = os.path.join("out", "target", "product", codename)

    try:
        files = [f for f in os.listdir(ota_dir) if f.startswith("AndroidOne-") and codename in f and f.endswith(".zip")]
    except FileNotFoundError:
        print(f"❌ OTA directory not found: {ota_dir}")
        sys.exit(1)

    if not files:
        print(f"❌ No OTA zip found in {ota_dir} matching pattern AndroidOne-*{codename}-*.zip")
        sys.exit(1)

    ota_filename = files[0]
    ota_filepath = os.path.join(ota_dir, ota_filename)
    dropbox_path = f"/{codename}/{ota_filename}"
    print(f"📦 Found OTA package: {ota_filepath}")

    android_exp_files = [f for f in os.listdir(ota_dir) if f.startswith("AndroidExperience")]

    build_prop = os.path.join(ota_dir, "system", "build.prop")
    datetime = "UNKNOWN"
    if os.path.isfile(build_prop):
        with open(build_prop) as f:
            for line in f:
                if line.startswith("ro.build.date.utc="):
                    datetime = line.strip().split("=")[1]
                    break

    version = "15"
    ota_file_id = sha256sum(ota_filepath)
    ota_file_size = os.path.getsize(ota_filepath)

    if no_upload:
        print("⏩ --no-upload specified, skipping all uploads...")
        if check_file_exists(dbx, dropbox_path):
            print(f"ℹ️ OTA file exists on Dropbox: {dropbox_path}")
            ota_link = get_or_create_shared_link(dbx, dropbox_path) or "LINK_NOT_FOUND"
        else:
            print(f"⚠️ OTA file not found on Dropbox at {dropbox_path}")
            ota_link = "NOT_FOUND_ON_DROPBOX"
    else:
        if check_file_exists(dbx, dropbox_path):
            print(f"✅ File already exists on Dropbox: {dropbox_path}")
            ota_link = get_or_create_shared_link(dbx, dropbox_path)
        else:
            print("⬆️ File not found on Dropbox, proceeding to upload...")
            ota_link = upload_to_dropbox(ota_filepath, codename, access_token)

        if android_exp_files:
            recovery_path = os.path.join(ota_dir, "recovery.img")
            if os.path.isfile(recovery_path):
                print("🔍 AndroidExperience file detected, uploading recovery.img (no JSON entry)...")
                upload_to_dropbox(recovery_path, codename, access_token)
            else:
                print("⚠️ recovery.img NOT found — skipping.")

    ota_json = {
        "response": [
            {
                "datetime": datetime,
                "filename": ota_filename,
                "id": ota_file_id,
                "size": ota_file_size,
                "url": ota_link,
                "version": version
            }
        ]
    }

    output_dir = os.path.join(SCRIPT_DIR, "devices")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{codename}.json")

    with open(output_file, "w") as f:
        json.dump(ota_json, f, indent=2)

    print(f"📄 OTA JSON saved to: {output_file}")

if __name__ == "__main__":
    main()
