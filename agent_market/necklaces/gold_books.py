"""Gold set for book-author-brief (100-necklace plan 7-2, workflow 11-15).

The task: who wrote a book, when it first came out, and the author's birth year from an encyclopedia entry on the
author. Truth comes from Wikidata through the book's English Wikipedia article: author (P50, one author only),
publication date (P577, the earliest year) and the author's date of birth (P569). Three requests per book, spaced
one second. A book whose author's English Wikipedia summary does not carry the birth year is left out: the
encyclopedia step could not answer it, so it would grade the source, not the necklace.

Strata are eras of first publication. Cases go into tuning / holdout-r1 / holdout-r2 by gold.split (30 each).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

from .gold import Fetcher, _now, split, write_set
from .judge import DEFAULT_ROOT

SLUG = "book-author-brief"
ANSWER_SET = "book-author-brief-v1"
ENTITY_BY_TITLE = "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims&sites=enwiki&titles="
ENTITY_BY_ID = ("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims|labels|sitelinks"
                "&languages=en&sitefilter=enwiki&ids=")
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# (title as a person types it, English Wikipedia article of the book)
BOOKS = [
    ("Pride and Prejudice", "Pride and Prejudice"), ("Emma", "Emma (novel)"), ("Jane Eyre", "Jane Eyre"),
    ("Wuthering Heights", "Wuthering Heights"), ("Moby-Dick", "Moby-Dick"), ("Great Expectations", "Great Expectations"),
    ("Oliver Twist", "Oliver Twist"), ("Middlemarch", "Middlemarch"), ("Frankenstein", "Frankenstein"),
    ("Dracula", "Dracula"), ("Crime and Punishment", "Crime and Punishment"), ("War and Peace", "War and Peace"),
    ("Anna Karenina", "Anna Karenina"), ("Madame Bovary", "Madame Bovary"), ("Les Misérables", "Les Misérables"),
    ("The Count of Monte Cristo", "The Count of Monte Cristo"), ("Twenty Thousand Leagues Under the Seas",
     "Twenty Thousand Leagues Under the Seas"), ("The Adventures of Tom Sawyer", "The Adventures of Tom Sawyer"),
    ("Adventures of Huckleberry Finn", "Adventures of Huckleberry Finn"), ("The Scarlet Letter", "The Scarlet Letter"),
    ("Little Women", "Little Women"), ("The Picture of Dorian Gray", "The Picture of Dorian Gray"),
    ("Treasure Island", "Treasure Island"), ("The Time Machine", "The Time Machine"),
    ("Heart of Darkness", "Heart of Darkness"), ("The Brothers Karamazov", "The Brothers Karamazov"),
    ("Alice's Adventures in Wonderland", "Alice's Adventures in Wonderland"), ("Walden", "Walden"),
    ("Uncle Tom's Cabin", "Uncle Tom's Cabin"), ("The Strange Case of Dr Jekyll and Mr Hyde",
                                                 "Strange Case of Dr Jekyll and Mr Hyde"),
    ("Nineteen Eighty-Four", "Nineteen Eighty-Four"), ("Animal Farm", "Animal Farm"),
    ("Brave New World", "Brave New World"), ("The Great Gatsby", "The Great Gatsby"),
    ("Ulysses", "Ulysses (novel)"), ("Mrs Dalloway", "Mrs Dalloway"), ("To the Lighthouse", "To the Lighthouse"),
    ("The Sun Also Rises", "The Sun Also Rises"), ("The Old Man and the Sea", "The Old Man and the Sea"),
    ("The Grapes of Wrath", "The Grapes of Wrath"), ("Of Mice and Men", "Of Mice and Men"),
    ("The Sound and the Fury", "The Sound and the Fury"), ("The Trial", "The Trial"),
    ("The Metamorphosis", "The Metamorphosis"), ("The Stranger", "The Stranger (Camus novel)"),
    ("The Hobbit", "The Hobbit"), ("Rebecca", "Rebecca (novel)"), ("Gone with the Wind", "Gone with the Wind (novel)"),
    ("The Maltese Falcon", "The Maltese Falcon (novel)"), ("Murder on the Orient Express", "Murder on the Orient Express"),
    ("The Catcher in the Rye", "The Catcher in the Rye"), ("To Kill a Mockingbird", "To Kill a Mockingbird"),
    ("Fahrenheit 451", "Fahrenheit 451"), ("Lord of the Flies", "Lord of the Flies"),
    ("One Hundred Years of Solitude", "One Hundred Years of Solitude"), ("Lolita", "Lolita"),
    ("On the Road", "On the Road"), ("Catch-22", "Catch-22"), ("Slaughterhouse-Five", "Slaughterhouse-Five"),
    ("Things Fall Apart", "Things Fall Apart"), ("Beloved", "Beloved (novel)"), ("Dune", "Dune (novel)"),
    ("Foundation", "Foundation (Isaac Asimov novel)"), ("Solaris", "Solaris (novel)"),
    ("A Clockwork Orange", "A Clockwork Orange (novel)"), ("The Bell Jar", "The Bell Jar"),
    ("Invisible Man", "Invisible Man"), ("Midnight's Children", "Midnight's Children"),
    ("The Name of the Rose", "The Name of the Rose"), ("Norwegian Wood", "Norwegian Wood (novel)"),
    ("The Handmaid's Tale", "The Handmaid's Tale"), ("Blood Meridian", "Blood Meridian"),
    ("The Remains of the Day", "The Remains of the Day"), ("Neuromancer", "Neuromancer"),
    ("The Left Hand of Darkness", "The Left Hand of Darkness"), ("Do Androids Dream of Electric Sheep?",
                                                                  "Do Androids Dream of Electric Sheep?"),
    ("The Color Purple", "The Color Purple"), ("Song of Solomon", "Song of Solomon (novel)"),
    ("The Unbearable Lightness of Being", "The Unbearable Lightness of Being"), ("Doctor Zhivago", "Doctor Zhivago (novel)"),
    ("The Master and Margarita", "The Master and Margarita"), ("Atlas Shrugged", "Atlas Shrugged"),
    ("The Road", "The Road"), ("Never Let Me Go", "Never Let Me Go (novel)"), ("Life of Pi", "Life of Pi"),
    ("The Kite Runner", "The Kite Runner"), ("Atonement", "Atonement (novel)"), ("White Teeth", "White Teeth"),
    ("Wolf Hall", "Wolf Hall"), ("The Corrections", "The Corrections"), ("Gilead", "Gilead (novel)"),
    ("The Da Vinci Code", "The Da Vinci Code"), ("The Hunger Games", "The Hunger Games (novel)"),
    ("Gone Girl", "Gone Girl (novel)"), ("The Girl with the Dragon Tattoo", "The Girl with the Dragon Tattoo"),
    ("Station Eleven", "Station Eleven"), ("The Martian", "The Martian (Weir novel)"),
    ("Americanah", "Americanah"), ("A Little Life", "A Little Life"), ("Normal People", "Normal People"),
    ("The Three-Body Problem", "The Three-Body Problem (novel)"), ("Klara and the Sun", "Klara and the Sun"),
    ("Pachinko", "Pachinko (novel)"), ("The Underground Railroad", "The Underground Railroad (novel)"),
]


def era(year: int) -> str:
    return "before-1900" if year < 1900 else "1900-1949" if year < 1950 else "1950-1999" if year < 2000 else "2000-on"


def _claim_ids(entity: dict, prop: str) -> list[str]:
    out = []
    for claim in ((entity or {}).get("claims") or {}).get(prop) or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
    return out


def _years(entity: dict, prop: str) -> list[int]:
    out = []
    for claim in ((entity or {}).get("claims") or {}).get(prop) or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        stamp = value.get("time") if isinstance(value, dict) else None      # "+1949-06-08T00:00:00Z"
        if isinstance(stamp, str) and len(stamp) > 5 and stamp[0] == "+" and stamp[1:5].isdigit():
            out.append(int(stamp[1:5]))
    return out


def _entity(body: dict | None) -> dict | None:
    return next((e for qid, e in ((body or {}).get("entities") or {}).items() if not qid.startswith("-")), None)


def book_cases(f: Fetcher) -> tuple[list[dict], dict]:
    cases, dropped = [], {}
    for typed, title in BOOKS:
        book = _entity(f.json(ENTITY_BY_TITLE + quote(title, safe="")))
        authors, years = _claim_ids(book, "P50"), _years(book, "P577")
        if len(authors) != 1 or not years:
            dropped[title] = "not one author or no publication date"
            continue
        person = _entity(f.json(ENTITY_BY_ID + authors[0]))
        births = _years(person, "P569")
        name = (((person or {}).get("labels") or {}).get("en") or {}).get("value")
        wiki_title = (((person or {}).get("sitelinks") or {}).get("enwiki") or {}).get("title")
        if not births or not name or not wiki_title:
            dropped[title] = "author without birth year, English label or article"
            continue
        summary = f.json(SUMMARY + quote(wiki_title.replace(" ", "_"), safe="")) or {}
        text = f"{summary.get('description') or ''} {summary.get('extract') or ''}"
        if str(births[0]) not in text:
            dropped[title] = "the author's encyclopedia summary does not carry the birth year"
            continue
        year = min(years)
        cases.append({"case_id": "book:" + title, "task_type": "whole_task", "stratum": era(year),
                      "input": {"title": typed},
                      "truth": {"author": name, "author_qid": authors[0], "year": year, "birth_year": births[0],
                                "author_wiki_title": wiki_title, "book_qid": book.get("id")},
                      "truth_sources": [{"name": "Wikidata P50, P577 and P569",
                                         "url": f"https://www.wikidata.org/wiki/{book.get('id')}", "fetched_at": _now()},
                                        {"name": "Wikipedia REST summary of the author (birth year present)",
                                         "url": SUMMARY + quote(wiki_title.replace(" ", "_"), safe=""),
                                         "fetched_at": _now()}]})
    return cases, dropped


def build(root: Path = DEFAULT_ROOT, fetcher: Fetcher | None = None, raw_dir: Path | None = None) -> dict:
    f = fetcher or Fetcher(spacing={"www.wikidata.org": 1.0, "en.wikipedia.org": 1.0})
    cases, dropped = book_cases(f)
    if raw_dir:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "book-cases.json").write_text(json.dumps({"cases": cases, "dropped": dropped}, ensure_ascii=False))
    manifest = write_set(Path(root), SLUG, split(cases), {"answer_set": ANSWER_SET, "built_from": len(cases),
                                                         "listed": len(BOOKS)})
    return {"manifest": manifest, "calls": f.calls, "dropped": dropped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.root, raw_dir=args.raw_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
