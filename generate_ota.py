import os
import sys
import hashlib
import json
import subprocess

def main():
    codename = input("Enter device codename (e.g. PL2, miatoll): ").strip()
    ota_package_dir = f"out/target/product/{codename}"

    # Try to find the OTA package matching pattern AndroidOne-*{codename}-*.zip
    try:
        files = [f for f in os.listdir(ota_package_dir) if f.startswith("AndroidOne-") and codename in f and f.endswith(".zip")]
    except FileNotFoundError:
        print(f"OTA package directory not found: {ota_package_dir}")
        sys.exit(1)

    if not files:
        print(f"OTA package file not found in {ota_package_dir}.")
        print(f"Ensure the file follows the pattern: AndroidOne-*{codename}-*.zip")
        sys.exit(1)
    
    # If multiple files matched, take the first one
    filename = files[0]
    file_path = os.path.join(ota_package_dir, filename)
    print(f"Found OTA package: {file_path}")

    # Extract datetime from build.prop
    build_prop_path = os.path.join(ota_package_dir, "system", "build.prop")
    datetime = "UNKNOWN"
    if os.path.exists(build_prop_path):
        try:
            with open(build_prop_path, "r") as f:
                for line in f:
                    if line.startswith("ro.build.date.utc="):
                        datetime = line.strip().split("=", 1)[1]
                        break
        except Exception:
            pass

    # Calculate sha256 checksum
    def sha256sum(filename):
        h = hashlib.sha256()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    id_hash = sha256sum(file_path)

    # Get size in bytes
    size = os.path.getsize(file_path)

    version = "15"  # change if needed

    base_url = "https://storage.googleapis.com/rom"
    url = f"{base_url}/{filename}"

    output_dir = "./OTA/devices"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{codename}.json")

    # Create JSON structure
    data = {
        "response": [
            {
                "datetime": datetime,
                "filename": filename,
                "id": id_hash,
                "size": size,
                "url": url,
                "version": version,
            }
        ]
    }

    # Write JSON, prettified if possible
    try:
        import json
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Minimal OTA JSON saved to {output_file}")
    except Exception as e:
        print(f"Failed to write JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
