import pytest

from app.agents.conversation_agent import _parse_number_answer


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("vingt-deux", 22),
        ("vingt deux", 22),
        ("quatre-vingt-trois", 83),
        ("quatre-vingt-trois mille", 83_000),
        ("83 000", 83_000),
    ],
)
def test_parse_composite_number_answer(text: str, expected: int) -> None:
    assert _parse_number_answer(text) == expected
