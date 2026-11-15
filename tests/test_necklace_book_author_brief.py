"""book-author-brief: the book normalizer, the staged author lookup, the whole-task grader and the gold builder."""
from agent_market.necklaces import gold_books, model, retest, runner

CASE = {"case_id": "book:Nineteen Eighty-Four", "input": {"title": "Nineteen Eighty-Four"},
        "truth": {"author": "George Orwell", "year": 1949, "birth_year": 1903}}
OPEN_LIBRARY = {"numFound": 301, "docs": [{"author_name": ["George Orwell"], "first_publish_year": 1949,
                                           "title": "Nineteen Eighty-Four"},
                                          {"author_name": ["Fido Nesti"], "first_publish_year": 1984, "title": "1984"}]}
AUTHOR = [{"title": "George Orwell", "description": "English novelist and essayist (1903–1950)", "excerpt": "Eric Blair"}]
BOOK_ARTICLE = [{"title": "Nineteen Eighty-Four", "description": "1949 novel by George Orwell", "excerpt": "dystopian"}]


def test_book_normalizer_stages_the_first_author():
    out = runner.normalize("book.search.v1", OPEN_LIBRARY, {})
    assert (out["author"], out["year"], out["title"]) == ("George Orwell", 1949, "Nineteen Eighty-Four")
    fallback = {"answer": "Nineteen Eighty-Four — 1949 novel (Wikidata Q208460); author George Orwell; published 1949-06-08.",
                "source": "Wikidata"}
    assert runner.normalize("book.search.v1", fallback, {})["author"] == "George Orwell"
    assert runner.normalize("book.search.v1", {"numFound": 0, "docs": []}, {}) is None


def test_search_books_is_a_read_tool_but_booking_is_not():
    assert model.READ_NOUNS.match("search_books")
    defn = model.load("agent_market/necklaces/definitions/book-author-brief.json")
    assert model.validate(defn) == []
    member = dict(defn["slots"][0]["chain"][0], tool="book_room")
    assert any("looks like an action" in e for e in model._member_errors("book", 0, member))


def test_the_author_step_reads_the_staged_author():
    seen = {}

    def caller(member, args, timeout_s):
        seen[member["tool"]] = args
        return OPEN_LIBRARY if member["tool"] == "search_books" else AUTHOR
    defn = model.load("agent_market/necklaces/definitions/book-author-brief.json")
    result = runner.Runner(caller).run(defn, {"title": "Nineteen Eighty-Four"})
    assert seen["wikipedia_search"]["query"] == "George Orwell"
    assert retest.grade(defn, CASE, result["output"])["ok"]
    assert retest.grade_book_task(CASE, result["output"])


def test_task_grader_drops_single_agents_and_wrong_answers():
    book_only = {"book": runner.normalize("book.search.v1", OPEN_LIBRARY, {})}
    assert not retest.grade_book_task(CASE, book_only)                       # no birth year
    article_only = {"author": runner.normalize("encyclopedia.summary.v1", BOOK_ARTICLE, {})}
    assert not retest.grade_book_task(CASE, article_only)                    # the book's entry, not the author's
    wrong_author = {"book": {"author": "Aldous Huxley", "year": 1932, "text": "Huxley 1932"},
                    "author": {"text": "Aldous Huxley English writer (1894–1963)"}}
    assert not retest.grade_book_task(CASE, wrong_author)
    wrong_year = {"book": {"text": "George Orwell 1984"}, "author": {"text": "George Orwell (1903–1950)"}}
    assert not retest.grade_book_task(CASE, wrong_year)
    good = {"book": {"text": "Nineteen Eighty-Four by George Orwell, 1949"}, "author": {"text": "Orwell (1903–1950)"}}
    assert retest.grade_book_task(CASE, good)
    assert retest.grade_book_task(CASE, dict(good, book={"text": "George Orwell 1950"}))   # one year of slack


def test_single_author_lookup_gets_the_typed_title():
    defn = model.load("agent_market/necklaces/definitions/book-author-brief.json")
    lead = defn["slots"][1]["chain"][0]
    one = retest.single_definition(defn, "author", lead)
    assert one["slots"][0]["chain"][0]["input_map"]["query"] == "{{input.title}}"


def test_gold_builder_keeps_books_whose_author_summary_has_the_birth_year():
    class Fake:
        calls = 0

        def json(self, url):
            self.calls += 1
            if "titles=" in url:
                if "Emma" in url:
                    return {"entities": {"Q1": {"id": "Q1", "claims": {"P50": [
                        {"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}, {"mainsnak": {"datavalue": {"value": {"id": "Q3"}}}}]}}}}
                return {"entities": {"Q10": {"id": "Q10", "claims": {
                    "P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q20"}}}}],
                    "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+1949-06-08T00:00:00Z"}}}},
                             {"mainsnak": {"datavalue": {"value": {"time": "+1950-01-01T00:00:00Z"}}}}]}}}}
            if "ids=" in url:
                return {"entities": {"Q20": {"id": "Q20", "labels": {"en": {"value": "George Orwell"}},
                                             "sitelinks": {"enwiki": {"title": "George Orwell"}},
                                             "claims": {"P569": [{"mainsnak": {"datavalue": {"value": {
                                                 "time": "+1903-06-25T00:00:00Z"}}}}]}}}}
            return {"description": "English novelist (1903–1950)", "extract": ""}
    cases, dropped = gold_books.book_cases(Fake())
    assert "Emma (novel)" in dropped and len(cases) == len(gold_books.BOOKS) - 1
    assert cases[0]["truth"]["year"] == 1949 and cases[0]["truth"]["birth_year"] == 1903
    assert cases[0]["stratum"] == "1900-1949"
