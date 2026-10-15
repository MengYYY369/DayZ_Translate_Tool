import unittest

from quality_check import (
    DEFAULT_DISABLED_RULES,
    DEFAULT_SIMILARITY,
    FINDERS,
    RULE_GROUPS,
    QualityCheckConfig,
    all_rules,
    check_table,
    default_enabled_rules,
    target_columns,
)

HEADERS = ["Language", "original", "english", "czech", "german", "russian", "chinese", "japanese", "chinesesimp", ""]


def make_row(**values):
    row = [""] * len(HEADERS)
    for header, text in values.items():
        row[HEADERS.index(header)] = text
    return row


def check_one(rule, rows, source_header="english", headers=None, glossary=None, similarity=DEFAULT_SIMILARITY):
    config = QualityCheckConfig(enabled={rule}, similarity=similarity)
    return check_table(headers or HEADERS, rows, source_header, config=config, glossary=glossary)


class QualityCheckConfigTests(unittest.TestCase):
    def test_every_rule_has_a_finder(self):
        group_rules = [rule for _group, rules in RULE_GROUPS for rule in rules]
        finder_rules = [rule for rule, _finder in FINDERS]
        self.assertEqual(group_rules, finder_rules)
        self.assertEqual(len(all_rules()), 27)

    def test_empty_translation_is_off_by_default(self):
        self.assertIn("empty_translation", DEFAULT_DISABLED_RULES)
        self.assertNotIn("empty_translation", default_enabled_rules())
        self.assertEqual(len(default_enabled_rules()), 26)

    def test_json_round_trip(self):
        config = QualityCheckConfig(enabled={"numbers", "garbage"}, similarity=0.7)
        restored = QualityCheckConfig.from_json(config.to_json())
        self.assertEqual(restored.enabled, {"numbers", "garbage"})
        self.assertAlmostEqual(restored.similarity, 0.7)

    def test_json_fallback_on_bad_input(self):
        restored = QualityCheckConfig.from_json("nonsense")
        self.assertEqual(restored.enabled, set(default_enabled_rules()))
        self.assertAlmostEqual(restored.similarity, DEFAULT_SIMILARITY)
        self.assertAlmostEqual(QualityCheckConfig(similarity=9).similarity, 1.0)

    def test_target_columns_skip_source_and_copy_columns(self):
        # chinese 与 original 一样是照抄列，永远不检查
        self.assertEqual(target_columns(HEADERS, "english"), [3, 4, 5, 7, 8])
        # 源语言换成 chinesesimp 时，english 反过来要检查
        self.assertEqual(target_columns(HEADERS, "chinesesimp"), [2, 3, 4, 5, 7])


class QualityCheckRunnerTests(unittest.TestCase):
    def test_progress_reaches_total(self):
        calls = []
        rows = [make_row(english="Take the knife")]
        check_table(HEADERS, rows, "english", config=QualityCheckConfig(), progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls[-1], (27, 27))
        self.assertEqual(len(calls), 27)

    def test_cancel_stops_early(self):
        calls = []
        rows = [make_row(english="Take the knife")]
        issues = check_table(
            HEADERS, rows, "english", config=QualityCheckConfig(),
            progress=lambda d, t: calls.append((d, t)), should_cancel=lambda: True,
        )
        self.assertEqual(calls, [(1, 27)])
        self.assertEqual(issues, {})

    def test_source_and_copy_columns_are_never_checked(self):
        rows = [make_row(original="\ufffd", english="\ufffd", chinese="\ufffd")]
        self.assertEqual(check_table(HEADERS, rows, "english", config=QualityCheckConfig()), {})

    def test_multiple_rules_accumulate_on_one_cell(self):
        rows = [make_row(english="Take %1 knife", czech="Vezmi nuz\ufffd")]
        issues = check_table(HEADERS, rows, "english", config=QualityCheckConfig())
        self.assertEqual(issues[(0, 3)], ("placeholder_missing", "garbage"))


class FormatRuleTests(unittest.TestCase):
    def test_placeholder_missing(self):
        issues = check_one("placeholder_missing", [make_row(english="Take %1 items", czech="Vezmi predmety")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_placeholder_extra(self):
        issues = check_one("placeholder_extra", [make_row(english="Take items", czech="Vezmi %1 predmety")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_placeholder_order(self):
        issues = check_one("placeholder_order", [make_row(english="%1 of %2", czech="%2 z %1")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_line_breaks(self):
        issues = check_one("line_breaks", [make_row(english="Line1\\nLine2", czech="Line1Line2")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_rich_tags(self):
        issues = check_one("rich_tags", [make_row(english="Hello<br/>World", czech="Hello World")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_color_markup(self):
        issues = check_one("color_markup", [make_row(english="#(0.5,0,0,1)Red", czech="Cervena")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_numbers(self):
        issues = check_one("numbers", [make_row(english="Take 3 items", czech="Vezmi 4 predmety")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_brackets(self):
        issues = check_one("brackets", [make_row(english="Take (knife)", czech="Vezmi (nuz")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_spaces(self):
        issues = check_one("spaces", [make_row(english="Take knife", czech=" Vezmi nuz")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_invisible_chars(self):
        issues = check_one("invisible_chars", [make_row(english="Take knife", czech="Vezmi nuz\u200b")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_csv_unsafe(self):
        issues = check_one("csv_unsafe", [make_row(english="Take knife", czech="Vezmi\nnuz")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_empty_translation(self):
        issues = check_one("empty_translation", [make_row(english="Take knife", czech="")])
        # 空译文按格报，这一行 5 个目标列全空
        self.assertEqual(set(issues), {(0, 3), (0, 4), (0, 5), (0, 7), (0, 8)})


class LanguageRuleTests(unittest.TestCase):
    def test_script_missing(self):
        issues = check_one("script_missing", [make_row(english="Hello world", russian="Privet mir")])
        self.assertEqual(set(issues), {(0, 5)})

    def test_script_missing_accepts_matching_script(self):
        rows = [make_row(english="Hello world", russian="Privet mir", japanese="\u6771\u4eac\u306e\u8857")]
        issues = check_one("script_missing", rows)
        self.assertEqual(set(issues), {(0, 5)})

    def test_script_unexpected(self):
        issues = check_one("script_unexpected", [make_row(english="Hello world", czech="\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_copied_source(self):
        issues = check_one("copied_source", [make_row(english="Take the knife", czech="Take the knife")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_punctuation(self):
        rows = [make_row(english="Take knife, run", chinesesimp="\u62ff\u8d77\u5200,\u7136\u540e\u8d70")]
        issues = check_one("punctuation", rows)
        self.assertEqual(set(issues), {(0, 8)})

    def test_fullwidth(self):
        issues = check_one("fullwidth", [make_row(english="Take knife", czech="Vezmi\uff0cnuz")])
        self.assertEqual(set(issues), {(0, 3)})


class SimilarityRuleTests(unittest.TestCase):
    def test_row_similarity(self):
        rows = [make_row(english="Take the knife", czech="Vezmi nuz a bez", german="Vezmi nuz a bez")]
        issues = check_one("row_similarity", rows)
        self.assertEqual(set(issues), {(0, 3), (0, 4)})

    def test_row_similarity_ignores_chinese_and_chinesesimp(self):
        rows = [make_row(english="Take the knife", chinese="\u62ff\u8d77\u5200\u5b50", chinesesimp="\u62ff\u8d77\u5200\u5b50")]
        self.assertEqual(check_one("row_similarity", rows), {})

    def test_row_similarity_respects_threshold(self):
        # 只差大小写和重音：相似率约 0.6，默认 0.85 不报，门槛降到 0.5 就报
        rows = [make_row(english="Take the knife", czech="Vezmi nuz a bez", german="VÉZMI NÚZ A BÉZ")]
        self.assertEqual(check_one("row_similarity", rows), {})
        self.assertEqual(set(check_one("row_similarity", rows, similarity=0.5)), {(0, 3), (0, 4)})

    def test_row_similarity_ignores_cognates_with_different_spelling(self):
        # 西语/葡语、捷克语/波兰语这类近亲语言译对了也会很像，不能当成偷懒
        rows = [make_row(english="Hurricane", czech="Hurikán", german="Hurrikan")]
        self.assertEqual(check_one("row_similarity", rows), {})

    def test_column_duplicate(self):
        rows = [make_row(english=f"Take the knife {index}", czech="Vezmi nuz a bez", german="Vezmi nuz a bez")
                for index in range(6)]
        issues = check_one("column_duplicate", rows)
        self.assertEqual(len(issues), 12)
        self.assertIn((0, 3), issues)
        self.assertIn((5, 4), issues)

    def test_column_duplicate_needs_enough_rows(self):
        rows = [make_row(english="Take the knife", czech="Vezmi nuz a bez", german="Vezmi nuz a bez")]
        self.assertEqual(check_one("column_duplicate", rows), {})

    def test_column_duplicate_ignores_proper_noun_passthrough(self):
        rows = [make_row(english="DevilHunt", czech="DevilHunt", german="DevilHunt") for _ in range(5)]
        self.assertEqual(check_one("column_duplicate", rows), {})

    def test_row_similarity_ignores_proper_noun_passthrough(self):
        rows = [make_row(english="DevilHunt", czech="DevilHunt", german="DevilHunt")]
        self.assertEqual(check_one("row_similarity", rows), {})

    def test_row_similarity_still_flags_repeated_translation(self):
        rows = [make_row(english="Take the knife", czech="Vezmi nuz a bez", german="Vezmi nuz a bez")]
        issues = check_one("row_similarity", rows)
        self.assertIn((0, 3), issues)
        self.assertIn((0, 4), issues)

    def test_script_missing_ignores_proper_noun_passthrough(self):
        self.assertEqual(check_one("script_missing", [make_row(english="DevilHunt", russian="DevilHunt")]), {})
        self.assertEqual(check_one("script_missing", [make_row(english="Take the knife", russian="Take the knife")]), {})

    def test_script_missing_still_flags_latin_text_without_source_match(self):
        rows = [make_row(english="Take the knife", russian="Take the knife now")]
        self.assertIn((0, 5), check_one("script_missing", rows))

    def test_inconsistent_target_marks_the_odd_one(self):
        rows = [
            make_row(english="Take the knife", czech="Vezmi nuz"),
            make_row(english="Take the knife", czech="Vezmi nuz"),
            make_row(english="Take the knife", czech="Vezmi mec"),
        ]
        issues = check_one("inconsistent_target", rows)
        self.assertEqual(set(issues), {(2, 3)})

    def test_duplicate_target(self):
        rows = [
            make_row(english="Take the knife and run away", czech="Vezmi nuz a bez pryc"),
            make_row(english="Press the red button twice", czech="Vezmi nuz a bez pryc"),
        ]
        issues = check_one("duplicate_target", rows)
        self.assertEqual(set(issues), {(0, 3), (1, 3)})


class ModelOutputRuleTests(unittest.TestCase):
    def test_prompt_leak(self):
        issues = check_one("prompt_leak", [make_row(english="Take knife", czech="Here is the translation: Vezmi nuz")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_prompt_leak_json_residue(self):
        issues = check_one("prompt_leak", [make_row(english="Take knife", czech='{"text": "Vezmi nuz"}')])
        self.assertEqual(set(issues), {(0, 3)})

    def test_length_ratio_too_long(self):
        issues = check_one("length_ratio", [make_row(english="Knife", czech="V" * 45)])
        self.assertEqual(set(issues), {(0, 3)})

    def test_length_ratio_too_short(self):
        rows = [make_row(english="Take the knife and run away now", czech="Ok")]
        issues = check_one("length_ratio", rows)
        self.assertEqual(set(issues), {(0, 3)})

    def test_untranslated_sentence(self):
        rows = [make_row(english="Take the knife", chinesesimp="Take the knife and run")]
        issues = check_one("untranslated_sentence", rows)
        self.assertEqual(set(issues), {(0, 8)})

    def test_garbage(self):
        issues = check_one("garbage", [make_row(english="Take knife", czech="Vezmi nuz\ufffd")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_garbage_url(self):
        issues = check_one("garbage", [make_row(english="Take knife", czech="Vezmi https://example.com nuz")])
        self.assertEqual(set(issues), {(0, 3)})

    def test_parenthetical_notes(self):
        rows = [make_row(english="Take the knife", czech="Vezmi nuz (doslovne: vezmi nuz)")]
        issues = check_one("parenthetical_notes", rows)
        self.assertEqual(set(issues), {(0, 3)})


class GlossaryRuleTests(unittest.TestCase):
    def test_glossary_missing(self):
        glossary = [{"english": "Knife", "czech": "Nuz"}]
        rows = [make_row(english="Take the knife", czech="Vezmi cepel")]
        issues = check_one("glossary_missing", rows, glossary=glossary)
        self.assertEqual(set(issues), {(0, 3)})

    def test_glossary_present(self):
        glossary = [{"english": "Knife", "czech": "Nuz"}]
        rows = [make_row(english="Take the knife", czech="Vezmi nuz")]
        self.assertEqual(check_one("glossary_missing", rows, glossary=glossary), {})

    def test_no_glossary_means_no_findings(self):
        rows = [make_row(english="Take the knife", czech="Vezmi cepel")]
        self.assertEqual(check_one("glossary_missing", rows, glossary=[]), {})


if __name__ == "__main__":
    unittest.main()
