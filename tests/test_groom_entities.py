from products.groom.stages.entities import extract_entities

def test_extract_entities_empty() -> None:
    res = extract_entities("")
    assert res.clean
    assert not res.found

def test_extract_entities_generic_ignored() -> None:
    text = "Follow @google and @github for updates."
    res = extract_entities(text)
    assert res.clean
    assert not res.found

def test_extract_entities_found() -> None:
    text = "Hey @LocalLLaMA, check out r/MachineLearning and #AI! Also @someone."
    res = extract_entities(text)
    assert not res.clean
    # Should be sorted
    assert res.found == ("#ai", "@localllama", "@someone", "r/machinelearning")

def test_extract_entities_dedupe() -> None:
    text = "Hey @localllama, did you see @LocalLLaMA post #ai #AI?"
    res = extract_entities(text)
    assert res.found == ("#ai", "@localllama")
