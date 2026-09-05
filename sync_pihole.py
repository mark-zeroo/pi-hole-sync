import os
import json
import urllib.request
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_env(filepath):
    """Loads variables from a .env file into os.environ without external dependencies."""
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                val = val.strip().strip("'\"")
                os.environ[key.strip()] = val
                
def update_env_file(filepath, key, value):
    """Updates variable from .env file with new value"""
    if not os.path.exists(filepath):
        return

    updated_lines = []
    key_found = False
    with open(filepath, "r") as f:    
        for line in f:
            if line.strip().startswith(f"{key}="):
                updated_lines.append(f"{key}={value}\n")
                key_found = True
            else:
                updated_lines.append(line)

    if not key_found:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines.append("\n")
        updated_lines.append(f"{key}={value}\n")

    with open(filepath, "w") as f:
        f.writelines(updated_lines)
        
    load_env(filepath)

# Load Configuration
load_env(os.path.join(SCRIPT_DIR, ".env"))
PRIMARY_PI = os.getenv("PRIMARY_PI")
PRIMARY_APP_PASSWORD = os.getenv("PRIMARY_APP_PASSWORD")
SECONDARY_PI = os.getenv("SECONDARY_PI")
SECONDARY_APP_PASSWORD = os.getenv("SECONDARY_APP_PASSWORD")
LOG_LEVEL = os.getenv("LOG_LEVEL")

def update_env_var(var_name):
    """Updates variables assigned above with current value in .env file"""
    if var_name in globals():
        globals()[var_name] = os.getenv(var_name)
    else:
        print(f"Variable '{var_name}' could not be found.")

def check_for_pass():
    """Check if app passwords exist. If not, we'll have to make one"""
    if len(PRIMARY_APP_PASSWORD) == 0:
        prompt_for_pass("PRIMARY_APP_PASSWORD", PRIMARY_PI)
    if len(SECONDARY_APP_PASSWORD) == 0:
        prompt_for_pass("SECONDARY_APP_PASSWORD", SECONDARY_PI)
    return

def prompt_for_pass(PASS_VAR, BASE_URL):
    """Prompt the user for their login password for API authentication"""
    print(f"{PASS_VAR} not found. Please enter your admin console password for {BASE_URL}:")
    console_pass = input()

    sid = get_session_sid(BASE_URL, console_pass)
    
    if sid is None:
        print(f"Failed to get sid.")
        exit(1)
    
    try:
        print("Fetching application password...")
        res = make_request(f"{BASE_URL}/api/auth/app", "GET", headers={"sid": sid})
        if res.get("app"):
            app_pass = res["app"]["password"]
            app_pass_hash = res["app"]["hash"]
            
            setPassHash(PASS_VAR, app_pass, app_pass_hash, BASE_URL, sid)
    except Exception as e:
        print(f"Failed to acquire application password: {e}")
        exit(1)
        
def setPassHash(pass_var, app_pass, hash, base_url, sid):
    """Set the newly-created password hash in the pi-hole config, in the .env file, and update the global variable"""
    try:
        payload = {
            "config": {
                "webserver": {
                    "api": {
                        "app_pwhash": hash
                    }
                }
            }
        }
        
        res = make_request(f"{base_url}/api/config", "PATCH", headers={"sid": sid}, data=payload)
        if res.get("config", {}):
            newConf = res.get("config")
            if newConf["webserver"]["api"]["app_pwhash"] == hash:
                print("Successfully set application password hash in pi-hole.")
                print("Updating .env file...")
                update_env_file(os.path.join(SCRIPT_DIR, ".env"), pass_var, app_pass)
                update_env_var(pass_var)
                
    except Exception as e:
        print(f"Failed to set application password hash: {e}")
        return

def make_request(url, method="GET", headers=None, data=None):
    """Utility helper to send HTTP requests."""
    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if headers:
        req_headers.update(headers)
        
    encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            raw_body = response.read().decode("utf-8").strip()
            if not raw_body:
                return {}
            try:
                return json.loads(raw_body)
            except json.JSONDecodeError:
                return {"raw_response": raw_body}
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} on {method} {url}")
        print(e.read().decode("utf-8"))
        raise

def get_session_sid(base_url, password):
    """Authenticates and returns a session token."""
    if LOG_LEVEL == "debug":
        print(f"-> Fetching sid for {base_url}")
        
    res = make_request(f"{base_url}/api/auth", "POST", data={"password": password})
    if res.get("session", {}).get("valid"):
        return res["session"]["sid"]
    raise Exception(f"Failed to authenticate with {base_url}")

def logout_session(base_url, sid):
    """Terminates the session cleanly to free up API session seats."""
    try:
        make_request(f"{base_url}/api/auth", "DELETE", headers={"sid": sid})
        if LOG_LEVEL == "debug":
            print(f"Logged out and freed session seat on {base_url}")
    except Exception as e:
        print(f"Warning: Failed to log out session on {base_url}: {e}")

def get_adlists(base_url, sid):
    """Gets the dictionary of current adlists from Pi-hole."""
    res = make_request(f"{base_url}/api/lists?type=block", "GET", headers={"sid": sid})
    return res.get("lists", res)

def add_adlist(base_url, sid, address, comment, enabled=True):
    """Adds a new adlist to the server."""
    payload = {
        "address": address,
        "comment": comment if comment is not None else "",
        "enabled": enabled
    }
    url = f"{base_url}/api/lists?type=block"
    return make_request(url, "POST", headers={"sid": sid}, data=payload)

def delete_adlist(base_url, sid, address):
    """Deletes an adlist by its URL address."""
    encoded_address = urllib.parse.quote(address, safe='')
    url = f"{base_url}/api/lists/{encoded_address}?type=block"
    return make_request(url, "DELETE", headers={"sid": sid})

def update_gravity(base_url, sid):
    """Triggers a gravity db database update by trying known v6 gravity API paths."""
    print(f"Triggering gravity update on {base_url}...")
    url = f"{base_url}/api/action/gravity"

    try:
        make_request(url, "POST", headers={"sid": sid})
        print(f"-> Success! Gravity update triggered via POST {url}")
        return
    except urllib.error.HTTPError as e:
        print(f"-> Error updating gravity: {e.code}")
        raise


def main():
    check_for_pass()
    
    if not PRIMARY_APP_PASSWORD or not SECONDARY_APP_PASSWORD:
        raise ValueError("Error: Both PRIMARY_APP_PASSWORD and SECONDARY_APP_PASSWORD must be set in .env")
    
    p_sid = None
    s_sid = None
    
    try:
        print(PRIMARY_APP_PASSWORD, SECONDARY_APP_PASSWORD)
        print("Authenticating with both Pi-holes...")
        p_sid = get_session_sid(PRIMARY_PI, PRIMARY_APP_PASSWORD)
        s_sid = get_session_sid(SECONDARY_PI, SECONDARY_APP_PASSWORD)
        
        print("Fetching current adlists...")
        p_lists = get_adlists(PRIMARY_PI, p_sid)
        s_lists = get_adlists(SECONDARY_PI, s_sid)
        
        # 1. Safety Guard: Prevent catastrophic accidental wipes
        if not p_lists:
            print("\n[SAFETY ABORT] Primary Pi-hole returned 0 lists. Sync aborted to prevent deleting all lists on Secondary!")
            return
            
        print(f"-> Fetched {len(p_lists)} lists from Primary.")
        print(f"-> Fetched {len(s_lists)} lists from Secondary.")
        
        p_map = {item["address"].strip().lower(): (item.get("id"), item.get("comment", ""), item.get("enabled", True)) for item in p_lists}
        s_map = {item["address"].strip().lower(): (item.get("id"), item.get("comment", ""), item.get("enabled", True)) for item in s_lists}
        
        if LOG_LEVEL == "debug":
            # Debugging: Print addresses to see any hidden mismatch
            print("\n--- DEBUG ADDRESS COMPARISON ---")
            print(f"Primary list addresses: {list(p_map.keys())}")
            print(f"Secondary list addresses: {list(s_map.keys())}")
            print("--------------------------------\n")
        
        to_add = []
        to_delete = []
        
        # We preserve the original casing from p_lists for the actual addition
        for item in p_lists:
            addr_raw = item["address"]
            addr_key = addr_raw.strip().lower()
            if addr_key not in s_map:
                to_add.append((addr_raw, item.get("comment", ""), item.get("enabled", True)))
                
        # We preserve the original casing from s_lists for deletion
        for item in s_lists:
            addr_raw = item["address"]
            addr_key = addr_raw.strip().lower()
            if addr_key not in p_map:
                to_delete.append(addr_raw)
        
        changes_made = False
        
        if to_delete:
            print(f"Removing {len(to_delete)} stale list(s) from Secondary...")
            for addr in to_delete:
                print(f"-> Deleting: {addr}")
                delete_adlist(SECONDARY_PI, s_sid, addr)
            changes_made = True
            
        if to_add:
            print(f"Adding {len(to_add)} missing list(s) to Secondary...")
            for addr, comment, enabled in to_add:
                print(f"-> Adding: {addr}")
                add_adlist(SECONDARY_PI, s_sid, addr, comment, enabled)
            changes_made = True
            
        if changes_made:
            print("Lists successfully synced!")
            update_gravity(SECONDARY_PI, s_sid)
            print("Gravity database compiled successfully!")
        else:
            print("Secondary Pi-hole is already perfectly in sync with Primary. No actions needed.")
            
    except Exception as e:
        print(f"\nSync failed: {e}")
    finally:
        if LOG_LEVEL == "debug":
            print("\nCleaning up sessions...")
        if p_sid:
            logout_session(PRIMARY_PI, p_sid)
        if s_sid:
            logout_session(SECONDARY_PI, s_sid)

if __name__ == "__main__":
    main()
