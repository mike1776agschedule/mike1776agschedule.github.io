"""Shared helpers for the dashboard data lifecycle scripts."""
import re, json, base64, os, sys
from pathlib import Path
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_FILES = [
    REPO_ROOT / "index.html",
    REPO_ROOT / "campaign_schedule_outreach.html",
]

# Canonical 20-field schema for each record.
SCHEMA = [
    "Region", "County", "Category", "Subcategory", "Record_Classification",
    "Organization_or_Event_Name", "Contact_Name", "Contact_Title", "Email", "Phone",
    "Website", "Meeting_or_Event_Date", "Meeting_or_Event_Time", "Recurrence", "Venue",
    "City", "Notes", "Source_URL", "Facebook_URL", "Priority_Tier", "Priority_Label",
]

ENCRYPTED_BLOCK_RE = re.compile(r"window\.FL_AG_ENCRYPTED\s*=\s*\{(.*?)\};", re.DOTALL)


def get_pin() -> str:
    """Get PIN from env var FL_AG_PIN or fail with a friendly error."""
    pin = os.environ.get("FL_AG_PIN")
    if not pin:
        sys.stderr.write(
            "ERROR: FL_AG_PIN env var not set.\n"
            "Export it before running:  export FL_AG_PIN=040476\n"
        )
        sys.exit(1)
    if not re.fullmatch(r"\d{6}", pin):
        sys.stderr.write("ERROR: FL_AG_PIN must be exactly 6 digits.\n")
        sys.exit(1)
    return pin


def read_encrypted_block(html_path: Path) -> dict:
    """Pull salt/iv/ciphertext/iterations out of an HTML file."""
    html = html_path.read_text()
    m = ENCRYPTED_BLOCK_RE.search(html)
    if not m:
        raise RuntimeError(f"No FL_AG_ENCRYPTED block found in {html_path}")
    block = m.group(1)
    return {
        "salt": base64.b64decode(re.search(r'salt:\s*"([^"]+)"', block).group(1)),
        "iv": base64.b64decode(re.search(r'iv:\s*"([^"]+)"', block).group(1)),
        "ciphertext": base64.b64decode(re.search(r'ciphertext:\s*"([^"]+)"', block).group(1)),
        "iterations": int(re.search(r"iterations:\s*(\d+)", block).group(1)),
    }


def derive_key(pin: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(pin.encode())


def decrypt_records(html_path: Path, pin: str) -> list[dict]:
    """Decrypt the dashboard data from an HTML file and return list of records."""
    blob = read_encrypted_block(html_path)
    key = derive_key(pin, blob["salt"], blob["iterations"])
    plaintext = AESGCM(key).decrypt(blob["iv"], blob["ciphertext"], None)
    return json.loads(plaintext)


def encrypt_records(records: list[dict], pin: str, iterations: int = 600_000) -> str:
    """Encrypt records and return the JavaScript block to embed in the HTML."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(pin, salt, iterations)
    payload = json.dumps(records, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(iv, payload, None)
    return (
        "window.FL_AG_ENCRYPTED = {\n"
        f'  salt: "{base64.b64encode(salt).decode()}",\n'
        f'  iv: "{base64.b64encode(iv).decode()}",\n'
        f'  ciphertext: "{base64.b64encode(ciphertext).decode()}",\n'
        f"  iterations: {iterations}\n"
        "};"
    )


def replace_encrypted_block(html_path: Path, new_block: str) -> None:
    html = html_path.read_text()
    new_html, count = ENCRYPTED_BLOCK_RE.subn(new_block, html, count=1)
    if count != 1:
        raise RuntimeError(f"Failed to replace encrypted block in {html_path}")
    html_path.write_text(new_html)
