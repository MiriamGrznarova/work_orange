"""
manage_step_seq.py  —  Manage sequences.json for Cucumber-like exec steps.

File format (single source of truth):
{
  "version": 1,
  "map": {
    "DOWN,DOWN": ["open menu", "scroll to bottom"],
    "DOWN,DOWN,ENTER": ["select first item"]
  }
}

Commands:
  add
  reassign
  rename
  rm <step>
  list
  show <step|seq>
  lint
  gc

example command:
 python .\manage_step_seq.py rename

Rules:
- Step names must be lowercase letters/digits with a single space between words.
  (No punctuation: no commas, dots, slashes, underscores, hyphens, quotes, etc.)
- Sequences are canonicalized to UPPER tokens joined by commas: TOKEN,TOKEN,...
- Allowed tokens list is configurable (ALLOWED_TOKENS).
"""

import json
import os
import re
import sys
import tempfile
from typing import Dict, List

DEFAULT_FILE = "sequences.json"
VERSION = 1

# Allowed tokens — adjust to your project needs
ALLOWED_TOKENS = {
    "UP","DOWN","LEFT","RIGHT","ENTER","OK","ESC","BACK","TAB","SPACE",
    "WAIT","WAIT1","WAIT2","WAIT3","WAIT5","WAIT10"
}

# ===== Validation & canonicalization =====

# only lowercase letters/digits with a single space between words
_STEP_NAME_RE = re.compile(r"^[a-z0-9]+(?: [a-z0-9]+)*$")

def normalize_step_name(raw: str) -> str:
    """
    Requirements:
      - lowercase letters and digits only
      - single spaces between words
      - no punctuation (.,;:/_-"')
    """
    s = " ".join(raw.strip().split())  # collapse multiple spaces to one
    if not s:
        raise ValueError("Step name cannot be empty.")
    if not _STEP_NAME_RE.fullmatch(s):
        # Helpful hints:
        has_upper = any(ch.isupper() for ch in raw)
        has_forbidden = any(not (ch.islower() or ch.isdigit() or ch.isspace()) for ch in raw)
        if has_upper and has_forbidden:
            raise ValueError("Use lowercase only and remove punctuation (letters/digits + single spaces).")
        if has_upper:
            raise ValueError("Use lowercase only (letters/digits + single spaces).")
        if has_forbidden:
            raise ValueError("Remove punctuation; allowed: letters/digits + single spaces.")
        raise ValueError("Invalid step name; allowed: lowercase letters/digits with single spaces.")
    return s

def prompt_valid_step_name(prompt_text: str = "Step name (lowercase letters/digits, single spaces): ") -> str:
    while True:
        raw = input(prompt_text).strip()
        try:
            return normalize_step_name(raw)
        except ValueError as e:
            print(f"❌ {e} Please rename the scenario and try again.")

def prompt_sequence(prompt_text: str = "New sequence (e.g. DOWN, DOWN, ENTER): ") -> str:
    while True:
        raw = input(prompt_text).strip()
        try:
            return canonicalize_sequence(raw)
        except ValueError as e:
            print(f"❌ {e}")

def prompt_step(prompt_text: str = "Step name (lowercase letters/digits, single spaces): ") -> str:
    return prompt_valid_step_name(prompt_text)


def canonicalize_sequence(seq_str: str) -> str:
    """
    - split by commas or whitespace
    - trim each token, uppercase it
    - join with commas: TOKEN,TOKEN
    - validate against ALLOWED_TOKENS (if provided)
    """
    tokens = [t.strip().upper() for t in re.split(r"[,\s]+", seq_str) if t.strip()]
    if not tokens:
        raise ValueError("Sequence cannot be empty.")
    if ALLOWED_TOKENS:
        unknown = [t for t in tokens if t not in ALLOWED_TOKENS]
        if unknown:
            raise ValueError(
                f"Unknown tokens: {', '.join(unknown)}. "
                f"Allowed: {', '.join(sorted(ALLOWED_TOKENS))}"
            )
    return ",".join(tokens)
def confirm(prompt: str, default_no: bool = True) -> bool:
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")

# ===== IO helpers =====

def load_db(path: str) -> Dict:
    if not os.path.exists(path):
        return {"version": VERSION, "map": {}}
    with open(path, "r", encoding="utf-8") as f:
        db = json.load(f)
    db.setdefault("version", VERSION)
    db.setdefault("map", {})
    return db

def atomic_save(path: str, db: Dict) -> None:
    # safe write: write to temp, then rename
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".sequences.", suffix=".tmp", dir=d, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def build_reverse_cache(db: Dict) -> Dict[str, str]:
    """RAM-only cache: step -> seq"""
    rev = {}
    for seq, steps in db["map"].items():
        for s in steps:
            if s in rev and rev[s] != seq:
                raise ValueError(f"Inconsistent JSON: step '{s}' appears under '{rev[s]}' and '{seq}'.")
            rev[s] = seq
    return rev

# ===== Operations =====

def op_add(db_path: str):
    db = load_db(db_path)
    step_to_seq = build_reverse_cache(db)

    print("=== Add step ===")
    step = prompt_valid_step_name()
    raw_seq = input("Sequence (e.g. DOWN, DOWN, ENTER): ").strip()

    try:
        seq = canonicalize_sequence(raw_seq)
    except ValueError as e:
        print(f"❌ {e}")
        return

    existing = step_to_seq.get(step)
    if existing == seq:
        print(f"✅ '{step}' already exists under [{seq}]. No change.")
        return
    if existing and existing != seq:
        print(f"⚠️ Step '{step}' already exists under [{existing}]. Please choose a new name.")
        while True:
            new_name = prompt_valid_step_name("New step name: ")
            if new_name in step_to_seq:
                print("This name already exists. Pick another.")
                continue
            step = new_name
            break

    lst = db["map"].setdefault(seq, [])
    if step not in lst:
        lst.append(step)
        lst.sort()

    atomic_save(db_path, db)
    print(f"✅ Added: '{step}' → [{seq}]")
    print(f"💾 Saved to {db_path}")

def op_reassign(db_path: str, step: str = None, new_seq_raw: str = None):
    db = load_db(db_path)
    step_to_seq = build_reverse_cache(db)

    # Step: if not provided (or looks like it's been split), ask interactively
    if not step:
        step_n = prompt_step("Step to reassign: ")
    else:
        try:
            step_n = normalize_step_name(step)
        except ValueError as e:
            print(f"❌ {e}")
            step_n = prompt_step("Step to reassign: ")

    if step_n not in step_to_seq:
        print(f"Step '{step_n}' not found. Let's enter it again.")
        step_n = prompt_step("Step to reassign: ")
        if step_n not in step_to_seq:
            print(f"Step '{step_n}' not found.")
            return

    # Sequence: if not provided, ask interactively
    if not new_seq_raw:
        new_seq = prompt_sequence()
    else:
        try:
            new_seq = canonicalize_sequence(new_seq_raw)
        except ValueError as e:
            print(f"❌ {e}")
            new_seq = prompt_sequence()

    old_seq = step_to_seq[step_n]
    if old_seq == new_seq:
        print(f"'{step_n}' is already under [{new_seq}]. No change.")
        return

    # move
    db["map"][old_seq] = [s for s in db["map"][old_seq] if s != step_n]
    lst = db["map"].setdefault(new_seq, [])
    if step_n not in lst:
        lst.append(step_n)
        lst.sort()

    atomic_save(db_path, db)
    print(f"✅ Reassigned: '{step_n}'  [{old_seq}] → [{new_seq}]")
    print(f"💾 Saved to {db_path}")

def op_rename(db_path: str, old: str = None, new: str = None):
    db = load_db(db_path)
    step_to_seq = build_reverse_cache(db)
    if not old:
        old_n = prompt_step("Old step name: ")
    else:
        try:
            old_n = normalize_step_name(old)
        except ValueError as e:
            print(f"❌ {e}")
            old_n = prompt_step("Old step name: ")

    if old_n not in step_to_seq:
        print(f"Step '{old_n}' not found. Let's enter it again.")
        old_n = prompt_step("Old step name: ")
        if old_n not in step_to_seq:
            print(f"Step '{old_n}' not found.")
            return
    if not new:
        new_n = prompt_step("New step name: ")
    else:
        try:
            new_n = normalize_step_name(new)
        except ValueError as e:
            print(f"❌ {e}")
            new_n = prompt_step("New step name: ")

    if new_n in step_to_seq:
        print(f"Step '{new_n}' already exists. Please choose another name.")
        new_n = prompt_step("New step name: ")
        if new_n in step_to_seq:
            print(f"Step '{new_n}' already exists.")
            return

    seq = step_to_seq[old_n]
    db["map"][seq] = [new_n if s == old_n else s for s in db["map"][seq]]
    db["map"][seq].sort()

    atomic_save(db_path, db)
    print(f"✅ Renamed: {old_n} → {new_n}")
    print(f"💾 Saved to {db_path}")

def op_remove(db_path: str, step: str, assume_yes: bool = False):
    db = load_db(db_path)
    step_to_seq = build_reverse_cache(db)

    try:
        step_n = normalize_step_name(step)
    except ValueError as e:
        print(f"❌ {e}")
        return

    seq = step_to_seq.get(step_n)
    if not seq:
        print(f"Step '{step_n}' not found.")
        return

    # check
    if not assume_yes:
        if not confirm(f"Delete step '{step_n}' from sequence [{seq}]?"):
            print("Cancelled.")
            return

    db["map"][seq] = [s for s in db["map"][seq] if s != step_n]
    if not db["map"][seq]:
        if assume_yes or confirm(f"Sequence [{seq}] is now empty. Remove it as well?"):
            del db["map"][seq]

    atomic_save(db_path, db)
    print(f"🗑️ Removed: '{step_n}'.")
    print(f"💾 Saved to {db_path}")


def op_list(db_path: str):
    db = load_db(db_path)
    print("=== sequence → steps ===")
    for seq in sorted(db["map"].keys()):
        print(f"[{seq}] -> {', '.join(db['map'][seq])}")

def op_show(db_path: str, query: str):
    db = load_db(db_path)
    q = query.strip()
    # try as a sequence first
    try:
        key = canonicalize_sequence(q)
        steps = db["map"].get(key, [])
        print(f"[{key}] -> {steps}")
        return
    except Exception:
        pass
    # otherwise treat it as a step name
    try:
        qn = normalize_step_name(q)
    except ValueError as e:
        print(f"❌ {e}")
        return
    step_to_seq = build_reverse_cache(db)
    seq = step_to_seq.get(qn)
    print(f"{qn} -> [{seq}]")

def op_lint(db_path: str):
    db = load_db(db_path)
    ok = True

    # 1) duplicate steps across sequences & invalid names
    seen = {}
    for seq, steps in db["map"].items():
        for s in steps:
            try:
                normalize_step_name(s)
            except ValueError as e:
                print(f"[ERR] step '{s}': {e}")
                ok = False
            if s in seen and seen[s] != seq:
                print(f"[ERR] step '{s}' is under [{seen[s]}] and [{seq}]")
                ok = False
            seen[s] = seq

    # 2) validate sequences & tokens
    for seq in db["map"].keys():
        try:
            canonicalize_sequence(seq)
        except ValueError as e:
            print(f"[ERR] sequence '{seq}': {e}")
            ok = False

    # 3) empty lists
    for seq, steps in db["map"].items():
        if not steps:
            print(f"[WARN] empty sequence: [{seq}] (cleanup with gc)")

    if ok:
        print("Lint OK ✅")
    else:
        print("Lint failed ❌")
        sys.exit(1)

def op_gc(db_path: str):
    db = load_db(db_path)
    before = len(db["map"])
    for k in list(db["map"].keys()):
        if not db["map"][k]:
            del db["map"][k]
    after = len(db["map"])
    if before != after:
        atomic_save(db_path, db)
    print(f"GC: removed {before - after} empty sequences.")

# ===== CLI =====

def main():
    args = sys.argv[1:]
    db_path = DEFAULT_FILE
    if "--file" in args:
        i = args.index("--file")
        db_path = args[i+1]
        args = args[:i] + args[i+2:]

    if not args or args[0] == "add":
        op_add(db_path)
    elif args[0] == "reassign":
        step_arg = args[1] if len(args) >= 2 else None
        seq_arg = " ".join(args[2:]) if len(args) >= 3 else None
        op_reassign(db_path, step_arg, seq_arg)
    elif args[0] == "rename":
        old_arg = args[1] if len(args) >= 2 and not args[1].startswith("--") else None
        new_arg = None
        if len(args) >= 3:
            new_arg = " ".join(a for a in args[2:] if not a.startswith("--"))
        op_rename(db_path, old_arg, new_arg)
    elif args[0] == "rm":
        if len(args) < 2:
            print("Usage: rm <step> [--yes]")
            return
        assume_yes = "--yes" in args
        step_arg = " ".join([a for a in args[1:] if not a.startswith("--")])
        op_remove(db_path, step_arg, assume_yes=assume_yes)
    elif args[0] == "list":
        op_list(db_path)
    elif args[0] == "show":
        if len(args) < 2:
            print("Usage: show <step|seq>")
            return
        op_show(db_path, " ".join(args[1:]))
    elif args[0] == "lint":
        op_lint(db_path)
    elif args[0] == "gc":
        op_gc(db_path)
    else:
        print("Commands: add | reassign  | rename  | rm <step> | list | show <q> | lint | gc [--file PATH]")

if __name__ == "__main__":
    main()
