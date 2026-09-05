import os
import json
import time
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

    max_retries = 3
    delay = 0
    
    for attempt in range(max_retries):
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
            error_body = e.read().decode("utf-8")
            print(f"HTTP Error {e.code} on {method} {url}")
            print(error_body)

            if "database is locked" in error_body:
                if attempt == max_retries - 1:
                    print(f"Max retries reached. Database remains locked.")
                    raise
                
                delay += 1.5
                print(f"Database locked (attempt {attempt + 1}/{max_retries}). Retrying in {delay}s")
                time.sleep(delay)
   

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
    res = make_request(f"{base_url}/api/lists", "GET", headers={"sid": sid})
    return res.get("lists", res)

def add_adlist(base_url, sid, address, comment, enabled, listType):
    """Adds a new adlist to the server."""
    payload = {
        "address": address,
        "comment": comment if comment is not None else "",
        "enabled": enabled
    }
    url = f"{base_url}/api/lists?type={listType}"
    return make_request(url, "POST", headers={"sid": sid}, data=payload)

def delete_adlist(base_url, sid, address, listType):
    """Deletes an adlist by its URL address."""
    encoded_address = urllib.parse.quote(address, safe='')
    url = f"{base_url}/api/lists/{encoded_address}?type={listType}"
    return make_request(url, "DELETE", headers={"sid": sid})

def enable_adlist(base_url, sid, address, comment, listType):
    """Enable a previously disabled adlist"""
    payload = {
        "comment": comment if comment is not None else "",
        "enabled": True,
        "type": listType
    }
    
    url = f"{base_url}/api/lists/{address}?type={listType}"
    return make_request(url, "PUT", headers={"sid": sid}, data=payload)

def disable_adlist(base_url, sid, address, comment, listType):
    """Disable a previously enabled adlist"""
    payload = {
        "comment": comment if comment is not None else "",
        "enabled": False
    }
    
    url = f"{base_url}/api/lists/{address}?type={listType}"
    return make_request(url, "PUT", headers={"sid": sid}, data=payload)

def allow_adlist(base_url, sid, address):
    payload = {
        "type": "allow"
    }
    
    url = f"{base_url}/api/lists/{address}?type=block"
    return make_request(url, "PUT", headers={"sid": sid}, data=payload)

def block_adlist(base_url, sid, address):
    payload = {
        "type": "block"
    }
    
    url = f"{base_url}/api/lists/{address}?type=allow"
    return make_request(url, "PUT", headers={"sid": sid}, data=payload)

def update_adlist_groups(base_url, sid, address, listType, listGroups, prim_groups, sec_groups):
    payload = {
        "groups": listGroups
    }

    url = f"{base_url}/api/lists/{address}?type={listType}"
    return make_request(url, "PUT", headers={"sid": sid}, data=payload)

def get_groups(base_url, sid):
    url = f"{base_url}/api/groups"
    try:
        res = make_request(url, "GET", headers={"sid": sid})
        return res.get("groups")
    except Exception as e:
        print(f"Could not fetch groups: {e}")
        
def create_group(base_url, sid, name, comment, enabled=True):
    payload = {
        "name": name,
        "comment": comment if comment is not None else "",
        "enabled": enabled
    }

    url = f"{base_url}/api/groups"
    return make_request(url, "POST", headers={"sid": sid}, data=payload)
        
def delete_group(base_url, sid, name):
    url = f"{base_url}/api/groups/{name}"
    return make_request(url, "DELETE", headers={"sid": sid})

def map_group_ids(prim_groups, sec_groups, list_groups):
    """Returns a block/allowlist-compatible list of group ids converted for the secondary server's group ids"""
    mapped_list = []
    for group_id in list_groups:
        prim_group = next((d for d in prim_groups if d.get("id") == group_id), None)
        if prim_group is None:
            continue
        sec_group = next((d for d in sec_groups if d.get("name") == prim_group["name"]), None)
        if sec_group is None:
            continue
        mapped_list.append(sec_group["id"])
    return mapped_list
        

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

def arrays_equal(arr1, arr2):
    if len(arr1) != len(arr2):
        return False
    
    # Copy lists so we don't modify the originals
    l1, l2 = list(arr1), list(arr2)
    
    for item in l1:
        if item in l2:
            l2.remove(item)  # Removes first occurrence
        else:
            return False
            
    return len(l2) == 0

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
        
        p_map = {item["address"].strip().lower(): (item.get("id"), item.get("comment", ""), item.get("enabled"), item.get("type"), item.get("groups")) for item in p_lists}
        s_map = {item["address"].strip().lower(): (item.get("id"), item.get("comment", ""), item.get("enabled"), item.get("type"), item.get("groups")) for item in s_lists}

        p_groups = get_groups(PRIMARY_PI, p_sid)
        s_groups = get_groups(SECONDARY_PI, s_sid)
        
        groups_to_create = []
        groups_to_delete = []
        
        if not arrays_equal(p_groups, s_groups):
            print("\n\n")
            missing_groups = [d for d in p_groups if d["name"] not in {item["name"] for item in s_groups}]
            superfluous_groups = [d for d in s_groups if d["name"] not in {item["name"] for item in p_groups}]
            for group in missing_groups:
                groups_to_create.append(group)
            for group in superfluous_groups:
                groups_to_delete.append(group)
                
        if groups_to_create or groups_to_delete:
            print("Synchronizing server groups...")
            for group in groups_to_create:
                print(f"-> Creating group: {group["name"]}")
                create_group(SECONDARY_PI, s_sid, group["name"], group["comment"], group["enabled"])
                print(f"-> Group created: {group["name"]}")
            for group in groups_to_delete:
                print(f"-> Deleting group: {group["name"]}")
                delete_group(SECONDARY_PI, s_sid, group["name"])
                print(f"-> Group deleted: {group["name"]}")
        

        if LOG_LEVEL == "debug":
            # Debugging: Print addresses to see any hidden mismatch
            print("\n--- DEBUG ADDRESS COMPARISON ---")
            print(f"Primary list addresses: {list(p_map.keys())}")
            print(f"Secondary list addresses: {list(s_map.keys())}")
            print("--------------------------------\n")
        
        to_add = []
        to_delete = []
        to_disable = []
        to_enable = []
        to_allow = []
        to_block = []
        to_update_groups = []
        
        # We preserve the original casing from p_lists for the actual addition
        for item in p_lists:
            addr_raw = item["address"]
            addr_key = addr_raw.strip().lower()
            lists_added_to = 0
            if addr_key not in s_map:
                to_add.append((addr_raw, item.get("comment", ""), item.get("enabled", True), item.get("type"), item.get("groups")))
                lists_added_to += 1
            else:  
                if item.get("enabled") == False and s_map.get(addr_key)[2] == True:
                    to_disable.append((addr_raw, item.get("comment", ""), item.get("type")))
                    lists_added_to += 1
                if item.get("type") == "allow" and s_map.get(addr_key)[3] == "block":
                    to_allow.append((addr_raw))
                    lists_added_to += 1
                if not arrays_equal(item.get("groups"), s_map.get(addr_key)[4]) and lists_added_to < 1:
                    to_update_groups.append((addr_raw, item.get("type"), item.get("groups")))
                
        # We preserve the original casing from s_lists for deletion
        for item in s_lists:
            addr_raw = item["address"]
            addr_key = addr_raw.strip().lower()
            lists_added_to = 0

            if addr_key not in p_map:
                to_delete.append(addr_raw, item.get("type"))
                lists_added_to += 1
            else:
                if item.get("enabled") == False and p_map.get(addr_key)[2] == True:
                    to_enable.append((addr_raw, item.get("comment", ""), item.get("type")))
                    lists_added_to += 1
                if item.get("type") == "allow" and s_map.get(addr_key)[3] == "block":
                    to_block.append((addr_raw))
                    lists_added_to += 1
        
        changes_made = False

        if to_delete:
            print(f"Removing {len(to_delete)} stale list(s) from Secondary...")
            for addr, listType in to_delete:
                print(f"-> Deleting: {addr}")
                delete_adlist(SECONDARY_PI, s_sid, addr, listType)
                print(f"-> Deleted: {addr}")
            changes_made = True
            
        if to_add:
            print(f"Adding {len(to_add)} missing list(s) to Secondary...")
            for addr, comment, enabled, listType, listGroups in to_add:
                print(f"-> Adding: {addr}")
                add_adlist(SECONDARY_PI, s_sid, addr, comment, enabled, listType, listGroups)
                print(f"-> Added: {addr}")
            changes_made = True
            
        if to_disable:
            print(f"Disabling {len(to_disable)} lists in Secondary...")
            for addr, comment, listType in to_disable:
                print(f"-> Disabling: {addr}")
                disable_adlist(SECONDARY_PI, s_sid, addr, comment, listType)
                print(f"-> Disabled: {addr}")
            changes_made = True
        
        if to_enable:
            print(f"Enabling {len(to_enable)} lists in Secondary...")
            for addr, comment, listType in to_enable:
                print(f"-> Enabling: {addr}")
                enable_adlist(SECONDARY_PI, s_sid, addr, comment, listType)
                print(f"-> Enabled {addr}")
            changes_made = True
            
        if to_allow:
            print(f"Changing {len(to_allow)} lists to allowed in Secondary...")
            for addr in to_allow:
                print(f"-> Allowing: {addr}")
                allow_adlist(SECONDARY_PI, s_sid, addr)
                print(f"-> Allowed: {addr}")
            changes_made = True
            
        if to_block:
            print(f"Changing {len(to_block)} lists to blocked in Secondary...")
            for addr in to_allow:
                print(f"-> Blocking: {addr}")
                block_adlist(SECONDARY_PI, s_sid, addr)
                print(f"-> Blocked: {addr}")
            changes_made = True
            
        if to_update_groups:
            print(f"Updating groups for {len(to_update_groups)} lists in Secondary...")
            for addr, listType, groups in to_update_groups:
                print(f"Groups: {groups}")
                mapped_groups = map_group_ids(p_groups, s_groups, groups)
                print(f"Mapped Groups: {mapped_groups}")
                print(f"-> Updating list groups: {addr}")
                update_adlist_groups(SECONDARY_PI, s_sid, addr, listType, mapped_groups, p_groups, s_groups)
                print(f"-> List groups Updated")
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
