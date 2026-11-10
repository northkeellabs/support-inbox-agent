from support_agent.grounding import check_grounding, parse_citations

CHUNKS = {"webhooks#3": "Webhooks > Verify the signature\nEach request carries an X-Ledgerline-Signature header. Reject any request whose signature does not match.",
          "api-rate-limits#1": "API rate limits > Limits\nThe API allows 120 requests per minute per key."}


def test_valid_paraphrase_and_quote():
    r = check_grounding('Check the signature header [webhooks#3]. The docs say "reject any request whose signature does not match" [webhooks#3].', CHUNKS)
    assert r.ok and r.cited_ids == ["webhooks#3"] and len(r.quotes) == 1


def test_multi_id_bracket():
    assert [ids for _, _, ids in parse_citations("x [webhooks#3, api-rate-limits#1] y")] == [["webhooks#3", "api-rate-limits#1"]]
    assert check_grounding("Limits apply [webhooks#3; api-rate-limits#1].", CHUNKS).ok


def test_invalid_citation_fails():
    r = check_grounding("Signatures matter [webhooks#3]. Refunds take 3 days [refunds-policy#2].", CHUNKS)
    assert not r.ok and r.invalid_citations == ["refunds-policy#2"]


def test_quote_not_in_cited_chunk_fails():
    r = check_grounding('The docs say "signatures are optional" [webhooks#3].', CHUNKS)
    assert not r.ok and any("word for word" in p for p in r.problems)


def test_quote_in_other_chunk_than_cited_fails():
    r = check_grounding('"The API allows 120 requests per minute" [webhooks#3].', CHUNKS)
    assert not r.ok


def test_quote_without_following_citation_fails():
    r = check_grounding('Headers [webhooks#3]. Then "reject any request".', CHUNKS)
    assert not r.ok and any("no citation" in p for p in r.problems)


def test_quote_longer_than_25_words_fails():
    q = " ".join(["word"] * 26)
    r = check_grounding(f'"{q}" [webhooks#3]', {"webhooks#3": q})
    assert not r.ok and any("longer than 25" in p for p in r.problems)


def test_zero_citations_fails():
    r = check_grounding("Just check the header, it is easy.", CHUNKS)
    assert not r.ok and r.problems == ["no valid citations"]


def test_smart_quotes_normalised():
    assert check_grounding("\u201cReject any request\u201d [webhooks#3].", CHUNKS).ok
