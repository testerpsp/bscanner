import json, requests, bech32, threading, itertools, sys, time
from decimal import Decimal, ROUND_DOWN
from concurrent.futures import ThreadPoolExecutor, as_completed

CHAIN_LIST_URL = "https://raw.githubusercontent.com/blockscout/chainscout/main/data/chains.json"
GITHUB_API = "https://api.github.com/repos/cosmos/chain-registry/contents"
MAX_WORKERS = 20
TIMEOUT = 8
RETRY_PER_NODE = 3
GREEN = "\033[92m"
RESET = "\033[0m"

# ===== Spinner =====
spinner_running = False
def spinner():
    for c in itertools.cycle('|/-\\'):
        if not spinner_running:
            break
        sys.stdout.write('\rScanning... ' + c)
        sys.stdout.flush()
        time.sleep(0.15)
    sys.stdout.write('\r' + ' '*20 + '\r')  # clear line

def start_spinner():
    global spinner_running
    spinner_running = True
    t = threading.Thread(target=spinner)
    t.start()
    return t

def stop_spinner(thread):
    global spinner_running
    spinner_running = False
    thread.join()

# ===== Utils =====
def retry_request(url, params=None, retries=2, timeout=10):
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            return r
        except:
            continue
    return None

def format_balance(balance_str, decimals):
    try:
        bal = Decimal(balance_str)
        d = int(decimals) if decimals is not None else 18
        human = bal / (Decimal(10) ** d)
        human = human.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        text = format(human, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    except:
        return "0"

def format_amount(denom, amount_str):
    try:
        amount = Decimal(amount_str)
    except:
        return amount_str
    if denom.startswith("u"):
        amount /= Decimal(10**6)
    elif denom.startswith("a"):
        amount /= Decimal(10**18)
    return str(amount.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)).rstrip("0").rstrip(".")

# ===== EVM =====
def scan_chain(chain, wallet):
    name = chain['name']
    api_base = chain['explorer'].rstrip("/") + "/api"
    results = []
    try:
        params = {"module": "account", "action": "tokenlist", "address": wallet}
        r = retry_request(api_base, params, 2, 10)
        if r and r.status_code == 200 and r.text.strip().startswith("{"):
            res = r.json().get("result")
            if res:
                for t in res:
                    if t.get("type","").upper()=="ERC-20" and float(t.get("balance","0"))>0:
                        sym = t.get("symbol","?")
                        bal = format_balance(t.get("balance","0"), t.get("decimals",18))
                        results.append(f"{sym}: {bal}")
    except: pass
    try:
        params = {"module": "account", "action": "balance", "address": wallet}
        r = retry_request(api_base, params, 2, 10)
        if r and r.status_code == 200 and r.text.strip().startswith("{"):
            bal_raw = r.json().get("result")
            if bal_raw and bal_raw!="0":
                results.append(f"Native balance: {format_balance(bal_raw,18)}")
    except: pass
    return (name, results if results else None)

def run_evm_scan(wallet):
    resp = retry_request(CHAIN_LIST_URL, None, 2, 20)
    chains_data = json.loads(resp.text)
    active = []
    for c in chains_data.values():
        if isinstance(c, dict) and not c.get("isTestnet", False):
            for exp in c.get("explorers", []):
                url = exp.get("url")
                if url:
                    active.append({"name": c.get("name","Unknown"), "explorer": url})
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(scan_chain, ch, wallet) for ch in active]
        for f in as_completed(futures):
            n, res = f.result()
            if res:
                print(f"{GREEN}--- {n.upper()} ---{RESET}")
                for line in res:
                    print(" ", line)

# ===== IBC =====
def convert_address(address,new_prefix):
    hrp,data = bech32.bech32_decode(address)
    dec = bech32.convertbits(data,5,8,False)
    return bech32.bech32_encode(new_prefix,bech32.convertbits(dec,8,5,True))

def get_chain_folders():
    resp = retry_request(GITHUB_API, None, 2, 20)
    return [i["name"] for i in resp.json() if i["type"]=="dir"]

def load_chain_data(folder):
    url=f"https://raw.githubusercontent.com/cosmos/chain-registry/master/{folder}/chain.json"
    r = retry_request(url, None, 2, 10)
    if r and r.status_code==200:
        return r.json()
    return None

def fetch_balance_from_rest(rest_list,new_addr):
    for api in rest_list:
        url=f"{api['address'].rstrip('/')}/cosmos/bank/v1beta1/balances/{new_addr}"
        for _ in range(RETRY_PER_NODE):
            r = retry_request(url, None, 1, TIMEOUT)
            if r and r.status_code==200:
                try:
                    return r.json().get("balances",[])
                except:
                    pass
    return []

def get_balance_for_chain(folder,address):
    chain=load_chain_data(folder)
    if not chain: return None
    rest_list=chain.get("apis",{}).get("rest",[])
    if not rest_list: return None
    try: new_addr=convert_address(address,chain.get("bech32_prefix","cosmos"))
    except: return None
    balances = fetch_balance_from_rest(rest_list,new_addr)
    if not balances: return None
    tokens=[]
    for b in balances:
        if float(b.get("amount","0"))>0:
            tokens.append(f"{b['denom']}: {format_amount(b['denom'],b['amount'])}")
    if tokens:
        return {"chain": chain.get("chain_name", folder), "tokens": tokens}
    return None

def run_ibc_scan(addr):
    folders = get_chain_folders()
    print(f"Total folder ditemukan: {len(folders)}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(get_balance_for_chain, f, addr) for f in folders]
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                print(f"{GREEN}--- {r['chain'].upper()} ---{RESET}")
                for t in r['tokens']:
                    print(" ", t)

# ===== MAIN LOOP =====
if __name__ == "__main__":
    while True:
        addr = input("\nMasukkan wallet address (0x... / cosmos1... / 0 untuk keluar): ").strip()
        if addr == "0":
            print("Keluar.")
            break

        # Mulai spinner
        t = start_spinner()

        if addr.startswith("0x"):
            # Jalankan scan di thread utama, spinner jalan di thread lain
            print(f"\nMulai scan EVM {addr}...\n")
            run_evm_scan(addr)
            stop_spinner(t)  # stop setelah selesai
            print("\n=== SELESAI SCAN EVM ===")

        elif addr.startswith("cosmos1"):
            print(f"\nMulai scan IBC {addr}...\n")
            run_ibc_scan(addr)
            stop_spinner(t)
            print("\n=== SELESAI SCAN IBC ===")

        else:
            stop_spinner(t)
            print("Alamat tidak dikenali.")
