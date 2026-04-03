# -*- coding: utf-8 -*-
"""
Created on Thu Apr  2 14:22:11 2026

@author: siddh
"""

import requests
import time
import json
from pathlib import Path

API_KEY = "419263b44c6c869d79417df30421ff7c5108"

# These MeSH terms cover ALL drug safety literature
# regardless of specific drug name
MESH_TERMS = [
    "Drug-Related Side Effects and Adverse Reactions[MeSH]",
    "Pharmacovigilance[MeSH]",
    "Drug Toxicity[MeSH]",
    "Chemical and Drug Induced Liver Injury[MeSH]",
    "Drug Hypersensitivity[MeSH]",
    "Drug Interactions[MeSH]",
    "Medication Errors[MeSH]",
    "Postmarketing Surveillance, Product[MeSH]",
    "Drug Monitoring[MeSH]",
    "Cardiotoxicity[MeSH]",
    "Nephrotoxicity[MeSH]",
    "Neurotoxicity Syndromes[MeSH]",
    "Drug Eruptions[MeSH]",
    "Anaphylaxis[MeSH]",
    "Teratogenesis[MeSH]"
]

print(f"{'MeSH Term':<55} {'Total Available':>15} {'Downloadable':>14}")
print("-" * 86)

grand_total = 0
for term in MESH_TERMS:
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "api_key": API_KEY
        },
        timeout=30
    )
    data = r.json()
    count = int(data["esearchresult"]["count"])
    downloadable = min(count, 100000)
    grand_total += downloadable
    print(f"{term:<55} {count:>15,} {downloadable:>14,}")
    time.sleep(0.2)

print("-" * 86)
print(f"{'TOTAL PAPERS AVAILABLE TO DOWNLOAD':<55} {grand_total:>15,}")
print(f"{'Already downloaded':<55} {'28,014':>15}")
print(f"{'Additional papers we can get':<55} {grand_total - 28014:>15,}")