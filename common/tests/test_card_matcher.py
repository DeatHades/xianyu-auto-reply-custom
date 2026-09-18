import unittest

from common.services.card_matcher import CardMatcher


class CardMatcherFallbackTests(unittest.TestCase):
    def setUp(self):
        self.matcher = CardMatcher(None)

    def test_unique_bound_card_can_fallback_for_no_spec_product(self):
        card = {
            "id": 1,
            "name": "唯一绑定卡券",
            "is_multi_spec": True,
            "card_source": "own",
        }

        self.assertEqual(
            self.matcher._match_card_dicts_by_spec([card], None, None),
            [],
        )
        self.assertEqual(
            self.matcher._get_single_card_fallback([card]),
            [card],
        )

    def test_single_card_fallback_chooses_first_bound_card(self):
        cards = [
            {"id": 1, "name": "规格 A", "is_multi_spec": True},
            {"id": 2, "name": "规格 B", "is_multi_spec": True},
        ]

        self.assertEqual(
            self.matcher._get_single_card_fallback(cards),
            [cards[0]],
        )
