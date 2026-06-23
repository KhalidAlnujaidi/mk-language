# swarm-drafted (node=kinox-swarm-1, model=Nemotron-14B); curated locally
# Behavioral: a real AWS key (AKIA + 16 upper/digit chars) is redacted and
# reported; secret-free text passes through untouched. (Fixed: the draft's
# example used lowercase hex, which the AKIA[0-9A-Z]{16} pattern rejects.)
from products.groom.stages.redact import redact


def test_redact_aws_key():
    secret = "AKIAIOSFODNN7EXAMPLE"  # AKIA + 16 uppercase/digit chars
    result = redact(secret)
    assert secret not in result.text
    assert "REDACTED:aws_key" in result.text
    assert "aws_key" in result.found


def test_redact_clean_text():
    clean_text = "No secrets here."
    result = redact(clean_text)
    assert result.text == clean_text
    assert not result.found
