"""Timestamp the pre-registration on Solana, and verify it later.

A git commit's date can be set to anything on your own machine. Writing a hash of the frozen
plan and code into a Solana transaction proves they existed before any real data were analysed:
the blockchain records the time, and anyone can check it.

  python timestamp_solana.py keygen                      # make a keypair OUTSIDE this folder
  python timestamp_solana.py airdrop                     # free devnet SOL for a practice run
  python timestamp_solana.py stamp --network devnet      # practice run; writes nothing
  python timestamp_solana.py stamp --network mainnet     # the real, permanent timestamp
  python timestamp_solana.py verify                      # re-hash files, fetch the transaction, compare
  python timestamp_solana.py stamp --network mainnet --label stage2   # a second, separate stamp

Writes PREREG_MANIFEST.txt (one SHA-256 per frozen file) and PREREG_STAMP.json (network,
transaction signature, manifest hash). Commit both. A mainnet stamp costs about 0.000005 SOL.
Files are hashed with Windows line endings normalised, so checkouts on any OS verify the same.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
RPC = {"devnet": "https://api.devnet.solana.com", "mainnet": "https://api.mainnet-beta.solana.com"}
EXPLORER = "https://explorer.solana.com/tx/{sig}{suffix}"
DEFAULT_KEY = os.path.join(os.path.expanduser("~"), ".config", "solana", "fed-prereg.json")
FROZEN_EXTRA = ["PREREGISTRATION.md", "STAGE2_PREREGISTRATION.md", "LIQUIDITY_PREREGISTRATION.md", "CLAUDE.md",
                "Makefile", "requirements.txt"]
NOT_FROZEN = {"timestamp_solana.py"}          # the stamping tool itself may be fixed later
MANIFEST, STAMP = "PREREG_MANIFEST.txt", "PREREG_STAMP.json"


def files_for(label):
    """Stage 1 uses the plain names; a labelled stamp (e.g. stage2) gets its own pair of files."""
    return (MANIFEST, STAMP) if not label else (f"PREREG_MANIFEST.{label}.txt", f"PREREG_STAMP.{label}.json")


# ---------------------------------------------------------------- hashing
def file_sha256(path):
    data = open(path, "rb").read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def frozen_files():
    files = [f for f in sorted(glob.glob("*.py")) if f not in NOT_FROZEN]
    return files + [f for f in FROZEN_EXTRA if os.path.exists(f)]


def manifest_text(files):
    return "".join(f"{file_sha256(f)}  {f}\n" for f in files)


def text_sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_dirty():
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, text=True)
        return bool(out.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def memo_for(manifest_hash, commit, label=None):
    tag = "fed-liveness-prereg" + (f"-{label}" if label else "")
    return f"{tag} v1 manifest-sha256:{manifest_hash} git:{commit or 'none'}"


# ---------------------------------------------------------------- RPC
def rpc(url, method, params):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    r.raise_for_status()
    js = r.json()
    if "error" in js:
        raise RuntimeError(f"{method}: {js['error']}")
    return js["result"]


def load_keypair(path):
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.load(open(path))))


def build_memo_tx(keypair, memo, blockhash_str):
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    ix = Instruction(Pubkey.from_string(MEMO_PROGRAM), memo.encode(), [AccountMeta(keypair.pubkey(), True, False)])
    bh = Hash.from_string(blockhash_str)
    return Transaction([keypair], Message.new_with_blockhash([ix], keypair.pubkey(), bh), bh)


def memo_from_transaction(result):
    """Pull the memo text out of a getTransaction(jsonParsed) result."""
    instructions = (((result or {}).get("transaction") or {}).get("message") or {}).get("instructions") or []
    for ix in instructions:
        if ix.get("program") == "spl-memo" or ix.get("programId") == MEMO_PROGRAM:
            parsed = ix.get("parsed")
            if isinstance(parsed, str):
                return parsed
    for line in ((result or {}).get("meta") or {}).get("logMessages") or []:
        if "Memo (len" in line and '"' in line:
            return line.split('"', 1)[1].rsplit('"', 1)[0]
    return None


# ---------------------------------------------------------------- commands
def cmd_manifest(_args):
    text = manifest_text(frozen_files())
    sys.stdout.write(text)
    print(f"\nManifest SHA-256: {text_sha256(text)}")


def cmd_keygen(args):
    from solders.keypair import Keypair
    out = os.path.abspath(args.out)
    if out.startswith(os.path.abspath(".") + os.sep):
        raise SystemExit("Refusing to write a keypair inside the project folder: it could get committed.")
    if os.path.exists(out):
        raise SystemExit(f"{out} already exists; not overwriting it.")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    kp = Keypair()
    with open(out, "w") as fh:
        json.dump(list(bytes(kp)), fh)
    os.chmod(out, 0o600)
    print(f"Wrote {out}\nPublic address: {kp.pubkey()}\n"
          "Fund this address with a little SOL for mainnet (a few cents' worth is plenty).")


def cmd_airdrop(args):
    kp = load_keypair(args.keypair)
    sig = rpc(args.rpc or RPC["devnet"], "requestAirdrop", [str(kp.pubkey()), 100_000_000])
    print(f"Requested 0.1 devnet SOL for {kp.pubkey()} (signature {sig}). It arrives within a minute; "
          "if the public faucet is rate-limited, try faucet.solana.com.")


def cmd_stamp(args):
    url = args.rpc or RPC[args.network]
    label = getattr(args, "label", None)
    manifest_path, stamp_path = files_for(label)
    practice = args.network == "devnet"
    if git_dirty():
        raise SystemExit("Uncommitted changes: commit everything first, so the stamp matches a commit.")
    if git_commit() is None:
        print("Note: no git commit found, so the stamp covers file hashes only. Run git init and commit first.")
    if not practice and os.path.exists(stamp_path) and not args.force:
        raise SystemExit(f"{stamp_path} already exists. Re-stamping means the plan changed: log a deviation "
                         "in PREREGISTRATION.md, then rerun with --force.")
    text = manifest_text(frozen_files())
    mhash, commit = text_sha256(text), git_commit()
    memo = memo_for(mhash, commit, label)
    kp = load_keypair(args.keypair)
    blockhash = rpc(url, "getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    import base64
    tx = build_memo_tx(kp, memo, blockhash)
    sig = rpc(url, "sendTransaction", [base64.b64encode(bytes(tx)).decode(),
                                       {"encoding": "base64", "preflightCommitment": "confirmed"}])
    status = None
    for _ in range(40):
        st = rpc(url, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        if st and st.get("err"):
            raise SystemExit(f"Transaction failed: {st['err']}")
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            status = st["confirmationStatus"]
            break
        time.sleep(1.5)
    if not status:
        print("Sent, but not yet confirmed; run `verify` in a minute.")
    suffix = "" if args.network == "mainnet" else f"?cluster={args.network}"
    if practice:
        print(f"Practice stamp on devnet: {EXPLORER.format(sig=sig, suffix=suffix)}\n"
              "Nothing was written. When ready, run `make stamp` for the real mainnet timestamp.")
        return
    with open(manifest_path, "w") as fh:
        fh.write(text)
    stamp = {"network": args.network, "signature": sig, "manifest_sha256": mhash, "git_commit": commit,
             "memo": memo, "signer": str(kp.pubkey()), "sent_at_utc": datetime.now(timezone.utc).isoformat(),
             "explorer": EXPLORER.format(sig=sig, suffix=suffix)}
    with open(stamp_path, "w") as fh:
        json.dump(stamp, fh, indent=2)
    print(f"Stamped on {args.network}: {stamp['explorer']}\n"
          f"Now commit {manifest_path} and {stamp_path}. Do this before downloading the data this plan covers.")


def cmd_verify(args):
    manifest_path, stamp_path = files_for(getattr(args, "label", None))
    stamp = json.load(open(stamp_path))
    recorded = open(manifest_path).read()
    ok = True
    if text_sha256(recorded) != stamp["manifest_sha256"]:
        print(f"FAIL: {manifest_path} does not match the hash in {stamp_path}.")
        ok = False
    expected = dict(line.split("  ", 1)[::-1] for line in recorded.strip().splitlines())
    expected = {k.strip(): v for k, v in expected.items()}
    changed = [f for f, h in expected.items() if not os.path.exists(f) or file_sha256(f) != h]
    added = [f for f in frozen_files() if f not in expected]
    url = args.rpc or RPC[stamp["network"]]
    result = rpc(url, "getTransaction", [stamp["signature"], {"encoding": "jsonParsed",
                                                               "maxSupportedTransactionVersion": 0,
                                                               "commitment": "confirmed"}])
    if not result:
        print("FAIL: transaction not found on chain (devnet may have been reset, or it is not confirmed yet).")
        sys.exit(1)
    memo = memo_from_transaction(result)
    if not memo or stamp["manifest_sha256"] not in memo:
        print(f"FAIL: on-chain memo does not contain the manifest hash. Memo: {memo!r}")
        ok = False
    when = datetime.fromtimestamp(result["blockTime"], timezone.utc) if result.get("blockTime") else None
    print(f"On-chain memo: {memo}")
    print(f"Recorded in slot {result.get('slot')} at {when.isoformat() if when else 'unknown time'} "
          f"({stamp['network']}): the frozen plan existed by then.")
    if changed or added:
        print("Files changed since the stamp (check each is a logged deviation or a data-plumbing fix):")
        for f in changed:
            print(f"  changed: {f}")
        for f in added:
            print(f"  new:     {f}")
    else:
        print("Every frozen file is unchanged since the stamp.")
    print("VERIFIED" if ok else "NOT VERIFIED")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest")
    kg = sub.add_parser("keygen"); kg.add_argument("--out", default=DEFAULT_KEY)
    ad = sub.add_parser("airdrop"); ad.add_argument("--keypair", default=DEFAULT_KEY); ad.add_argument("--rpc")
    st = sub.add_parser("stamp")
    st.add_argument("--network", choices=["devnet", "mainnet"], required=True)
    st.add_argument("--keypair", default=DEFAULT_KEY)
    st.add_argument("--rpc", help="custom RPC URL, e.g. from a sponsor's RPC provider")
    st.add_argument("--force", action="store_true")
    st.add_argument("--label", help="separate stamp for a later plan, e.g. stage2")
    vf = sub.add_parser("verify"); vf.add_argument("--rpc"); vf.add_argument("--label")
    args = ap.parse_args()
    {"manifest": cmd_manifest, "keygen": cmd_keygen, "airdrop": cmd_airdrop,
     "stamp": cmd_stamp, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
