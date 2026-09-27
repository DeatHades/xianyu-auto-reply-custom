import unittest

from common.semantic_keyword import parse_semantic_keyword_selection


class SemanticKeywordSelectionTests(unittest.TestCase):
    def test_accepts_candidate_at_threshold(self):
        self.assertEqual(
            parse_semantic_keyword_selection(
                '{"matched":true,"rule_id":12,"confidence":0.9}',
                {12, 13},
            ),
            (12, 0.9, "matched"),
        )

    def test_rejects_low_confidence(self):
        self.assertEqual(
            parse_semantic_keyword_selection(
                '{"matched":true,"rule_id":12,"confidence":0.89}',
                {12},
            ),
            (None, 0.89, "low_confidence"),
        )

    def test_rejects_invented_rule_id(self):
        rule_id, confidence, status = parse_semantic_keyword_selection(
            '{"matched":true,"rule_id":999,"confidence":1}',
            {12},
        )
        self.assertIsNone(rule_id)
        self.assertEqual(confidence, 1.0)
        self.assertEqual(status, "invalid_result")

    def test_rejects_non_finite_confidence(self):
        for confidence in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(confidence=confidence):
                self.assertEqual(
                    parse_semantic_keyword_selection(
                        f'{{"matched":true,"rule_id":12,"confidence":{confidence}}}',
                        {12},
                    )[2],
                    "invalid_result",
                )

    def test_rejects_prose_or_extra_output_field(self):
        self.assertEqual(
            parse_semantic_keyword_selection(
                'answer: {"matched":true,"rule_id":12,"confidence":1}',
                {12},
            )[2],
            "invalid_result",
        )
        self.assertEqual(
            parse_semantic_keyword_selection(
                '{"matched":true,"rule_id":12,"confidence":1,"reply":"unsafe"}',
                {12},
            )[2],
            "invalid_result",
        )

    def test_returns_no_match(self):
        self.assertEqual(
            parse_semantic_keyword_selection(
                '{"matched":false,"rule_id":null,"confidence":0}',
                {12},
            ),
            (None, None, "no_match"),
        )


if __name__ == "__main__":
    unittest.main()
