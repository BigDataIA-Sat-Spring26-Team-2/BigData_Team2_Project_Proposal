"""
MedSignal — FAERS PRR POC
No Kafka. No Spark. No Docker.

Run:
    pip install pandas requests
    python faers_prr_poc.py
"""

import zipfile, io, os, urllib.request, ssl
import pandas as pd
import numpy as np

ZIP_PATH = "faers_ascii_2023q1.zip"
URL = "https://fis.fda.gov/content/Exports/faers_ascii_2023q1.zip"
OUTPUT_CSV = "prr_results_2023q1.csv"
PRR_THRESHOLD = 2.0
MIN_CASES = 3


# ── STEP 1: Download ───────────────────────────────────────────────────────────

def download_faers():
    if os.path.exists(ZIP_PATH):
        print(f"[STEP 1] Found {ZIP_PATH} — skipping download.")
        return
    print("[STEP 1] Downloading FAERS 2023 Q1 (~60MB)...")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(URL, context=ctx) as r, open(ZIP_PATH, "wb") as f:
        f.write(r.read())
    print("         Done.")


# ── STEP 2: Parse ZIP ──────────────────────────────────────────────────────────

def find_and_read(zf, prefix):
    # Must be a .txt file — skip PDFs and readme files
    match = next(
        (n for n in zf.namelist()
         if os.path.basename(n).upper().startswith(prefix)
         and n.upper().endswith(".TXT")),
        None
    )
    if not match:
        print(f"         All files in ZIP: {zf.namelist()}")
        raise FileNotFoundError(f"No .txt file starting with '{prefix}' found in ZIP")
    print(f"         Reading: {match}")
    with zf.open(match) as f:
        df = pd.read_csv(
            io.TextIOWrapper(f, encoding="latin-1"),
            sep="$",
            dtype=str,
            on_bad_lines="skip",
            low_memory=False,
        )
    # Normalize column names immediately after reading
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def load_faers():
    print("[STEP 2] Reading files from ZIP...")
    with zipfile.ZipFile(ZIP_PATH) as zf:
        demo = find_and_read(zf, "DEMO")
        drug = find_and_read(zf, "DRUG")
        reac = find_and_read(zf, "REAC")
        outc = find_and_read(zf, "OUTC")

    print(f"\n         Raw row counts:")
    print(f"           DEMO : {len(demo):>10,}")
    print(f"           DRUG : {len(drug):>10,}")
    print(f"           REAC : {len(reac):>10,}")
    print(f"           OUTC : {len(outc):>10,}")
    return demo, drug, reac, outc


# ── STEP 3: Clean ──────────────────────────────────────────────────────────────

def clean(demo, drug, reac):
    print("\n[STEP 3] Cleaning and filtering...")

    # Print actual columns so we can see exactly what FAERS gave us
    print(f"         DRUG columns : {list(drug.columns)}")
    print(f"         DEMO columns : {list(demo.columns)}")
    print(f"         REAC columns : {list(reac.columns)}")

    # FAERS 2023 Q1 uses 'role_cod' not 'drugcharacterization'
    # PS = Primary Suspect, SS = Secondary Suspect, C = Concomitant, I = Interacting
    # We want PS only — equivalent to drugcharacterization = 1
    if "role_cod" in drug.columns:
        drug_char_col = "role_cod"
        suspect_val = "PS"
    elif "drugcharacterization" in drug.columns:
        drug_char_col = "drugcharacterization"
        suspect_val = "1"
    else:
        raise KeyError(f"Cannot find suspect drug column. DRUG columns: {list(drug.columns)}")

    drug_name_col = next((c for c in drug.columns if "drugname" in c or "drug_name" in c), None)
    if not drug_name_col:
        raise KeyError(f"Cannot find drugname column. DRUG columns: {list(drug.columns)}")

    print(f"         Using drug char col : '{drug_char_col}' (filter = '{suspect_val}')")
    print(f"         Using drug name col : '{drug_name_col}'")

    # Keep only PRIMARY SUSPECT drugs — critical filter, prevents cartesian explosion
    drug_clean = drug[drug[drug_char_col] == suspect_val][["primaryid", drug_name_col]].copy()
    drug_clean = drug_clean.rename(columns={drug_name_col: "drugname"})
    drug_clean["drugname"] = drug_clean["drugname"].str.upper().str.strip()
    print(f"         Suspect drug rows : {len(drug_clean):,}  (was {len(drug):,})")

    # Normalize MedDRA reactions
    reac_clean = reac[["primaryid", "pt"]].copy()
    reac_clean["pt"] = reac_clean["pt"].str.upper().str.strip()

    # Deduplicate DEMO — keep latest version per case
    if "caseversion" in demo.columns:
        demo["caseversion"] = pd.to_numeric(demo["caseversion"], errors="coerce").fillna(0)
        demo_clean = demo.sort_values("caseversion", ascending=False).drop_duplicates("caseid")
    else:
        demo_clean = demo.drop_duplicates("primaryid")
    print(f"         Unique cases      : {len(demo_clean):,}")

    return demo_clean, drug_clean, reac_clean


# ── STEP 4: Join ───────────────────────────────────────────────────────────────

def join_files(demo_clean, drug_clean, reac_clean):
    print("\n[STEP 4] Joining files...")

    df = demo_clean[["primaryid"]].merge(drug_clean, on="primaryid", how="inner")
    print(f"         After DEMO x DRUG : {len(df):,}")

    df = df.merge(reac_clean, on="primaryid", how="inner")
    print(f"         After x REAC      : {len(df):,}")

    print(f"\n         Sample rows:")
    print(df.head(3).to_string(index=False))
    return df


# ── STEP 5: Compute PRR ────────────────────────────────────────────────────────

def compute_prr(df):
    print("\n[STEP 5] Computing PRR/ROR for all drug-symptom pairs...")

    total_cases = df["primaryid"].nunique()
    print(f"         Total unique cases: {total_cases:,}")

    A = (
        df.groupby(["drugname", "pt"])["primaryid"]
        .nunique()
        .reset_index(name="A")
    )
    drug_total = (
        df.groupby("drugname")["primaryid"]
        .nunique()
        .reset_index(name="drug_total")
    )
    reac_total = (
        df.groupby("pt")["primaryid"]
        .nunique()
        .reset_index(name="reaction_total")
    )

    prr_df = A.merge(drug_total, on="drugname").merge(reac_total, on="pt")
    prr_df = prr_df[prr_df["A"] >= MIN_CASES].copy()

    eps = 0.5
    prr_df["B"] = prr_df["drug_total"] - prr_df["A"]
    prr_df["C"] = prr_df["reaction_total"] - prr_df["A"]
    prr_df["D"] = total_cases - prr_df["drug_total"] - prr_df["C"]

    prr_df["PRR"] = (
        (prr_df["A"] / (prr_df["A"] + prr_df["B"] + eps)) /
        (prr_df["C"] / (prr_df["C"] + prr_df["D"] + eps))
    ).round(4)

    prr_df["ROR"] = (
        (prr_df["A"] * prr_df["D"]) /
        ((prr_df["B"] + eps) * (prr_df["C"] + eps))
    ).round(4)

    flagged = prr_df[prr_df["PRR"] >= PRR_THRESHOLD].sort_values("PRR", ascending=False)
    print(f"         Pairs above threshold (PRR>={PRR_THRESHOLD}, cases>={MIN_CASES}): {len(flagged):,}")
    return flagged


# ── STEP 6: Checkpoint ─────────────────────────────────────────────────────────

def checkpoint(prr_results):
    print("\n[STEP 6] Checkpoint — finasteride + depression PRR ~3.14")
    print("-" * 60)

    result = prr_results[
        (prr_results["drugname"].str.contains("FINAST", case=False, na=False)) &
        (prr_results["pt"].str.contains("DEPRESS", case=False, na=False))
    ].sort_values("PRR", ascending=False)

    if len(result) == 0:
        print("   No finasteride-depression pair found above threshold.")
        print("   Check [STEP 7] for drug name variants.")
    else:
        print(result[["drugname", "pt", "A", "PRR", "ROR"]].to_string(index=False))
        top_prr = result.iloc[0]["PRR"]
        passed = abs(top_prr - 3.14) <= 1.0
        print(f"\n   Top PRR : {top_prr}")
        print(f"   Expected: ~3.14  (tolerance +/-1.0 for single quarter)")
        print(f"   Result  : {'PASSED' if passed else 'OUTSIDE EXPECTED RANGE — check join logic'}")


# ── STEP 7: Debug drug name variants ──────────────────────────────────────────

def debug_variants(drug_clean):
    print("\n[STEP 7] Finasteride name variants in this quarter:")
    variants = (
        drug_clean[
            drug_clean["drugname"].str.contains("FINAST|PROPECIA|PROSCAR", case=False, na=False)
        ]["drugname"].value_counts()
    )
    if len(variants) == 0:
        print("         None found — try a different quarter.")
    else:
        print(variants.to_string())


# ── STEP 8: Top 20 signals ─────────────────────────────────────────────────────

def show_top_signals(prr_results):
    print("\n[STEP 8] Top 20 signals by PRR:")
    print(
        prr_results[["drugname", "pt", "A", "PRR", "ROR"]]
        .head(20)
        .to_string(index=False)
    )


# ── STEP 9: Save ───────────────────────────────────────────────────────────────

def save(prr_results):
    prr_results.to_csv(OUTPUT_CSV, index=False)
    print(f"\n[STEP 9] Saved {len(prr_results):,} flagged pairs to {OUTPUT_CSV}")
    print("         Hand this CSV to seed Agent 1.")


# ── MAIN ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    download_faers()
    demo, drug, reac, outc = load_faers()
    demo_clean, drug_clean, reac_clean = clean(demo, drug, reac)
    df = join_files(demo_clean, drug_clean, reac_clean)
    prr_results = compute_prr(df)
    checkpoint(prr_results)
    debug_variants(drug_clean)
    show_top_signals(prr_results)
    save(prr_results)