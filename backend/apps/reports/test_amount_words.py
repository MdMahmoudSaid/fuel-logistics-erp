from decimal import Decimal

import pytest

from apps.reports.services.amount_words import amount_in_words


@pytest.mark.parametrize(
    "amount,lang,expected",
    [
        (0, "fr", "Zéro FCFA"),
        (1, "fr", "Un FCFA"),
        (21, "fr", "Vingt et un FCFA"),
        (71, "fr", "Soixante et onze FCFA"),
        (80, "fr", "Quatre-vingts FCFA"),
        (81, "fr", "Quatre-vingt-un FCFA"),
        (200, "fr", "Deux cents FCFA"),
        (1000, "fr", "Mille FCFA"),
        (1000000, "fr", "Un million FCFA"),
        (387500000, "fr", "Trois cent quatre-vingt-sept millions cinq cent mille FCFA"),
        (Decimal("135000000.00"), "fr", "Cent trente-cinq millions FCFA"),
        (1, "en", "One FCFA"),
        (387500000, "en", "Three hundred eighty-seven million five hundred thousand FCFA"),
        (2001, "en", "Two thousand one FCFA"),
        (1000, "ar", "ألف فرنك"),
        (2000, "ar", "ألفان فرنك"),
        (25, "ar", "خمسة وعشرون فرنك"),
        (387500000, "ar", "ثلاثمائة وسبعة وثمانون مليونا وخمسمائة ألف فرنك"),
    ],
)
def test_amount_in_words(amount, lang, expected):
    assert amount_in_words(amount, lang) == expected


def test_amount_in_words_rounds_like_the_printed_total():
    # The total prints rounded half-up (1 234 568 XOF): the words must match.
    assert amount_in_words(Decimal("1234567.60"), "fr").startswith("Un million deux cent trente-quatre mille cinq cent soixante-huit")
