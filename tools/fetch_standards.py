"""Fetch a curated set of public space standards and store them under data/standards.

This script downloads a set of known standards pages (HTML) and saves them
as text/html and plain text to make them easy to ingest.
"""
import os
import requests
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "standards"
OUT.mkdir(parents=True, exist_ok=True)

SEED_URLS = [
    # NASA SEH / SE standards pages
    "https://sma.nasa.gov/resources/technical-standards",
    "https://standards.nasa.gov/",
    # ESA standards hub
    "https://esass.org/",
    # COSPAR
    "https://cosparhq.cnes.fr/",
    # Artemis Accords (hosted by NASA)
    "https://www.nasa.gov/specials/artemis-accords/",
]


def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    # remove scripts/styles
    for s in soup(["script", "style"]):
        s.decompose()
    return soup.get_text(separator=" \n ", strip=True)


def fetch_all():
    for url in SEED_URLS:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            slug = url.replace("https://", "").replace("http://", "").replace("/", "_")
            html_file = OUT / f"{slug}.html"
            txt_file = OUT / f"{slug}.txt"
            html_file.write_text(r.text, encoding="utf-8")
            text = text_from_html(r.text)
            txt_file.write_text(text, encoding="utf-8")
            print("Fetched", url, "->", html_file, txt_file)
        except Exception as e:
            print("Failed to fetch", url, e)


if __name__ == "__main__":
    fetch_all()
