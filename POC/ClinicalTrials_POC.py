# -*- coding: utf-8 -*-
"""
Created on Wed Apr  1 12:59:52 2026

@author: siddh
"""

import requests
import json
import time
from pathlib import Path

OUT = Path(r"C:\Users\siddh\Documents\NEUBigData\Final_Project_Proposal_Prep\data\clinicaltrials")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

DRUGS = [
    "semaglutide", "dupilumab", "finasteride", "metformin",
    "atorvastatin", "adalimumab", "apixaban", "rivaroxaban",
    "pembrolizumab", "ozempic", "humira", "wegovy",
    "tirzepatide", "clopidogrel", "warfarin", "lisinopril",
    "amlodipine", "omeprazole", "gabapentin", "amoxicillin"
]

for drug in DRUGS:
    all_studies = []
    next_token = None
    page = 0

    while True:
        params = {
            "query.term": drug,
            "fields": "NCTId,BriefTitle,AdverseEventsModule",
            "pageSize": 100
        }
        if next_token:
            params["pageToken"] = next_token

        r = requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params=params,
            headers=HEADERS,
            timeout=30
        )

        if r.status_code != 200:
            print(f"{drug}: Error {r.status_code}, skipping")
            break

        data = r.json()
        all_studies.extend(data.get("studies", []))
        next_token = data.get("nextPageToken")
        page += 1

        if not next_token or page > 20:
            break

        time.sleep(0.3)

    outfile = OUT / f"{drug}.json"
    with open(outfile, "w") as f:
        json.dump(all_studies, f)

    print(f"{drug}: {len(all_studies)} trials saved")
    time.sleep(0.5)

print("ClinicalTrials download complete.")