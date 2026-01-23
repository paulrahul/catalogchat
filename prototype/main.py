import requests
import json
import re
from bs4 import BeautifulSoup
from collections import Counter
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------
# Step 1: Fetch HTML
# -------------------------

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (schema-inference-bot)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


# -------------------------
# Step 2: DOM summarization
# -------------------------

def summarize_dom(html: str, max_blocks=20):
    """
    Extracts repeated DOM patterns and text samples.
    This is intentionally lossy — we don't want to dump full HTML to the LLM.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Find candidate repeated blocks
    elements = soup.find_all(True)
    class_counter = Counter()

    for el in elements:
        classes = el.get("class")
        if classes:
            for c in classes:
                class_counter[c] += 1

    common_classes = [
        c for c, count in class_counter.items()
        if count >= 5
    ][:max_blocks]

    samples = []

    for cls in common_classes:
        nodes = soup.select(f".{cls}")[:3]
        for n in nodes:
            text = " ".join(n.stripped_strings)
            text = re.sub(r"\s+", " ", text)
            samples.append({
                "class": cls,
                "tag": n.name,
                "text_sample": text[:300]
            })

    links = [
        a.get("href")
        for a in soup.find_all("a", href=True)
    ][:20]

    return {
        "title": soup.title.string if soup.title else None,
        "common_classes": common_classes,
        "samples": samples,
        "link_samples": links
    }


# -------------------------
# Step 3: Prompt construction
# -------------------------

def build_prompt(url: str, dom_summary: dict) -> str:
    return f"""
You are an expert web data extraction system.

Your task is to analyze a webpage summary and infer whether it represents
a CATALOG (a list of similar objects such as products, movies, articles, books, etc).

If it is a catalog:
- Identify the object type
- Infer a clean, minimal schema for ONE item
- Use generic, reusable field names
- Infer data types
- Prefer universal fields (title, price, author, rating, url, image, etc)
- Do NOT hallucinate fields not strongly suggested by the page

If it is NOT a catalog, clearly say so.

Supported catalog archetypes (v1):
- Card grid
- Vertical list
- Table

Output STRICT JSON in the following format:

{{
  "is_catalog": true | false,
  "catalog_type": "string | null",
  "confidence": 0.0-1.0,
  "archetype": "card_grid | list | table | unknown",
  "item_schema": {{
    "item_name": "string",
    "fields": [
      {{
        "name": "string",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string"
      }}
    ]
  }},
  "reasoning": "short explanation"
}}

DO NOT include markdown.
DO NOT include extra commentary.

Page URL:
{url}

Page title:
{dom_summary.get("title")}

Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2)}

Link samples:
{json.dumps(dom_summary.get("link_samples"), indent=2)}
"""


# -------------------------
# Step 4: Call OpenAI
# -------------------------

def infer_schema(prompt: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract structured schemas from web pages."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content
    return json.loads(content)


# -------------------------
# Step 5: Orchestrator
# -------------------------

def infer_catalog_schema(url: str):
    html = fetch_html(url)
    dom_summary = summarize_dom(html)
    prompt = build_prompt(url, dom_summary)
    schema = infer_schema(prompt)
    return schema


# -------------------------
# CLI usage
# -------------------------

if __name__ == "__main__":
    test_url = input("Enter root URL: ").strip()
    result = infer_catalog_schema(test_url)

    # Create file with the result in a results directory
    os.makedirs("results", exist_ok=True)
    with open(f"results/{test_url.replace('/', '_')}.json", "w") as f:
        json.dump(result, f, indent=2)