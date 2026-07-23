#!/usr/bin/env python3
"""
Gmail API Credentials Setup for JARVIS

Run this script to easily configure your Gmail OAuth credentials.
"""
import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
CREDENTIALS_FILE = CONFIG_DIR / "gmail_credentials.json"
API_KEYS_FILE = CONFIG_DIR / "api_keys.json"


def setup_gmail_credentials():
    """Interactive setup for Gmail OAuth credentials."""
    print("\n" + "=" * 70)
    print("  GMAIL API SETUP FOR JARVIS")
    print("=" * 70)
    print("""
This script helps you configure Gmail API access for the email module.

PREREQUISITES:
1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create/select a project
3. Enable Gmail API: APIs & Services > Library > Gmail API > Enable
4. Create OAuth 2.0 credentials: APIs & Services > Credentials > Create Credentials > OAuth Client ID
   - Application type: Desktop Application
   - Name: JARVIS Assistant
   - Authorized redirect URIs: http://localhost:8080/
5. Download the JSON file

""")

    print("Paste the ENTIRE JSON content from the downloaded credentials file below.")
    print("Press Ctrl+D (Linux/Mac) or Ctrl+Z then Enter (Windows) when done:\n")

    try:
        creds_json = sys.stdin.read()
    except KeyboardInterrupt:
        print("\nCancelled.")
        return False

    if not creds_json.strip():
        print("No input provided.")
        return False

    try:
        creds = json.loads(creds_json)
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] Invalid JSON: {e}")
        return False

    # Validate structure
    if "installed" not in creds and "web" not in creds:
        print("\n[ERROR] Invalid credentials format. Must be OAuth Desktop or Web client ID JSON.")
        print("   Expected keys: 'installed' or 'web'")
        return False

    # Save credentials
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    print(f"\n[OK] Credentials saved to: {CREDENTIALS_FILE}")

    # Prompt for user info
    print("\nNow let's add your user info to api_keys.json for personalized email replies:\n")

    user_name = input("Your name (for email sign-off): ").strip()
    user_email = input("Your Gmail address: ").strip().lower()
    user_context = input("Brief context for AI replies (role, projects, etc.): ").strip()

    if not user_email:
        print("Email is required.")
        return False

    # Load existing api_keys.json
    api_keys = {}
    if API_KEYS_FILE.exists():
        try:
            api_keys = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    api_keys.update({
        "user_name": user_name,
        "user_email": user_email,
        "user_context": user_context,
    })

    API_KEYS_FILE.write_text(json.dumps(api_keys, indent=4), encoding="utf-8")
    print(f"\n[OK] User info saved to: {API_KEYS_FILE}")

    print("""
======================================================================
  SETUP COMPLETE!
======================================================================
  Next steps:
  1. Run JARVIS: python main.py
  2. Say: "JARVIS, check my email" or "JARVIS, process my emails"
  3. First time: Browser opens for Google OAuth consent
  4. Review drafts in Gmail web interface before sending
======================================================================
""")
    return True


def check_setup():
    """Check current Gmail setup status."""
    print("\n" + "=" * 70)
    print("  GMAIL API SETUP STATUS")
    print("=" * 70)

    # Check credentials
    if CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            client_type = "installed" if "installed" in creds else "web"
            client_id = creds.get(client_type, {}).get("client_id", "unknown")
            print(f"[OK] Credentials: {CREDENTIALS_FILE}")
            print(f"     Type: {client_type} | Client ID: {client_id[:20]}...")
        except Exception as e:
            print(f"[WARN] Credentials file exists but invalid: {e}")
    else:
        print(f"[MISSING] Credentials: {CREDENTIALS_FILE}")

    # Check token
    token_file = CONFIG_DIR / "gmail_token.json"
    if token_file.exists():
        print(f"[OK] Token file: {token_file} (authenticated)")
    else:
        print(f"[INFO] No token file (will authenticate on first use)")

    # Check api_keys
    if API_KEYS_FILE.exists():
        try:
            keys = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
            print(f"[OK] User config: {API_KEYS_FILE}")
            print(f"     Name: {keys.get('user_name', 'not set')}")
            print(f"     Email: {keys.get('user_email', 'not set')}")
            ctx = keys.get('user_context', 'not set')
            print(f"     Context: {ctx[:50]}...")
        except Exception as e:
            print(f"[WARN] Config file exists but invalid: {e}")
    else:
        print(f"[MISSING] User config: {API_KEYS_FILE}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Gmail API setup for JARVIS")
    parser.add_argument("action", nargs="?", default="setup", choices=["setup", "status"],
                        help="Action to perform (default: setup)")
    args = parser.parse_args()

    if args.action == "status":
        check_setup()
    else:
        setup_gmail_credentials()


if __name__ == "__main__":
    main()