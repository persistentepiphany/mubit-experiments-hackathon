"""Fetches the three papers the mocked research step freezes, from Europe PMC.

Each becomes a text file in the run's frozen corpus, in the form
labloop/toolkit/corpus.py writes for an abstract-only paper (the title, a
blank line, the abstract), which the website's paper reader opens. Only
titles and abstracts are fetched, from Europe PMC's public REST API, and the
files are not committed.

    python seed/fetch_papers.py <out dir>
"""

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PAPERS = {
    "lin2023.txt": "10.1126/science.ade2574",
    "jumper2021.txt": "10.1038/s41586-021-03819-2",
    "xu2010.txt": "10.1093/bioinformatics/btq066",
}
RUNS = ["r-20261021-150212-5d8e3a", "r-20261021-152940-8b1f07"]


def fetch(doi: str) -> dict:
    query = urllib.parse.quote(f'DOI:"{doi}"')
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query}&resultType=core&format=json"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)["resultList"]["result"][0]


def text(record: dict) -> str:
    abstract = record.get("abstractText", "")
    abstract = re.sub(r"<h4>(.*?)</h4>", r"\n\n## \1\n\n", abstract)
    abstract = html.unescape(re.sub(r"<[^>]+>", "", abstract)).strip()
    return f"{record['title'].rstrip('.')}\n\n{abstract}\n"


def main(out: Path) -> None:
    for name, doi in PAPERS.items():
        body = text(fetch(doi))
        for run in RUNS:
            path = out / run / "research_corpus" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, "utf-8")
        print(f"  {name}: {len(body)} chars")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
