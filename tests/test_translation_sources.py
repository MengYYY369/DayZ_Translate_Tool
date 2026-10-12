import json
import unittest

from translation_sources import (
    ALL_RULES,
    DEFAULT_SOURCE_ORDER,
    RULE_ALL,
    RULE_SELECTION,
    SourceEntry,
    SourceList,
)


class DefaultsTests(unittest.TestCase):
    def test_default_order_matches_the_interview_decision(self):
        sources = SourceList()
        self.assertEqual([e.source_id for e in sources.entries], list(DEFAULT_SOURCE_ORDER))
        self.assertEqual(
            [e.source_id for e in sources.entries][:6],
            ["google", "microsoft", "tencent", "volcano", "lara", "mymemory"],
        )

    def test_first_three_are_batch_sources_with_all_rules(self):
        sources = SourceList()
        for source_id in ("google", "microsoft", "tencent"):
            entry = sources.find(source_id)
            self.assertEqual(sorted(entry.rules), sorted(ALL_RULES))

    def test_single_item_sources_default_to_selection_only(self):
        sources = SourceList()
        for source_id in ("volcano", "lara", "mymemory"):
            self.assertEqual(sources.find(source_id).rules, [RULE_SELECTION])

    def test_no_ai_source_out_of_the_box(self):
        sources = SourceList()
        self.assertFalse([e for e in sources.entries if e.is_ai])


class RuleFilterTests(unittest.TestCase):
    def test_candidates_follow_list_order(self):
        sources = SourceList()
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_ALL)],
            ["google", "microsoft", "tencent"],
        )
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_SELECTION)],
            ["google", "microsoft", "tencent", "volcano", "lara", "mymemory"],
        )

    def test_reordering_changes_priority(self):
        sources = SourceList()
        sources.move_up("mymemory")
        # move_up 只换一格：mymemory 从第 6 位挪到第 5 位（lara 前面），前两名不变
        self.assertEqual(
            [e.source_id for e in sources.entries][4:6], ["mymemory", "lara"]
        )
        for _ in range(5):
            sources.move_up("mymemory")
        self.assertEqual(
            [e.source_id for e in sources.candidates(RULE_SELECTION)][:2],
            ["mymemory", "google"],
        )

    def test_empty_rules_are_excluded(self):
        sources = SourceList()
        self.assertEqual(sources.candidates(RULE_ALL)[-1].source_id, "tencent")
        self.assertEqual([e.source_id for e in sources.candidates("nope")], [])


class EditTests(unittest.TestCase):
    def test_move_up_and_down_swap_neighbours(self):
        sources = SourceList()
        sources.move_up("tencent")
        self.assertEqual(
            [e.source_id for e in sources.entries][:3], ["google", "tencent", "microsoft"]
        )
        sources.move_down("google")
        self.assertEqual(
            [e.source_id for e in sources.entries][:3], ["tencent", "google", "microsoft"]
        )

    def test_move_at_edges_is_a_noop(self):
        sources = SourceList()
        sources.move_up("google")
        sources.move_down("deepl")
        self.assertEqual([e.source_id for e in sources.entries], list(DEFAULT_SOURCE_ORDER))

    def test_remove_drops_the_entry(self):
        sources = SourceList()
        sources.remove("lara")
        self.assertIsNone(sources.find("lara"))

    def test_add_ai_source_assigns_a_unique_id(self):
        sources = SourceList()
        entry = SourceEntry(kind="ai", name="我的 GPT", api_type="openai",
                            rules=[RULE_SELECTION], api_key="k", model="gpt-4o-mini")
        sources.add_ai(entry)
        self.assertTrue(entry.source_id.startswith("ai:"))
        other = SourceEntry(kind="ai", name="另一个", api_type="claude", rules=[RULE_SELECTION])
        sources.add_ai(other)
        self.assertNotEqual(entry.source_id, other.source_id)

    def test_add_ai_source_appends_to_the_end(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="X", api_type="openai"))
        self.assertTrue(sources.entries[-1].is_ai)

    def test_has_name_detects_duplicates(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="同名", api_type="openai"))
        self.assertTrue(sources.has_name("同名"))
        self.assertFalse(sources.has_name("别的"))

    def test_set_rule_toggles_membership(self):
        sources = SourceList()
        sources.set_rule("volcano", RULE_ALL, True)
        self.assertIn(RULE_ALL, sources.find("volcano").rules)
        sources.set_rule("volcano", RULE_ALL, False)
        self.assertNotIn(RULE_ALL, sources.find("volcano").rules)


class SerializationTests(unittest.TestCase):
    def test_round_trip_keeps_order_rules_and_ai_settings(self):
        sources = SourceList()
        sources.add_ai(SourceEntry(kind="ai", name="我的 GPT", api_type="claude",
                                   rules=[RULE_ALL, RULE_SELECTION], api_key="sk-1",
                                   base_url="https://x.test/v1", model="claude-x",
                                   concurrency=4, interval=0.5))
        sources.move_up("mymemory")
        restored = SourceList.from_json(sources.to_json())
        self.assertEqual(
            [e.source_id for e in restored.entries], [e.source_id for e in sources.entries]
        )
        ai = [e for e in restored.entries if e.is_ai][0]
        self.assertEqual(ai.name, "我的 GPT")
        self.assertEqual(ai.api_type, "claude")
        self.assertEqual(ai.api_key, "sk-1")
        self.assertEqual(ai.base_url, "https://x.test/v1")
        self.assertEqual(ai.model, "claude-x")
        self.assertEqual(ai.concurrency, 4)
        self.assertEqual(ai.interval, 0.5)
        self.assertEqual(sorted(ai.rules), sorted([RULE_ALL, RULE_SELECTION]))

    def test_blank_input_falls_back_to_defaults(self):
        for raw in ("", None, "   "):
            self.assertEqual(
                [e.source_id for e in SourceList.from_json(raw).entries],
                list(DEFAULT_SOURCE_ORDER),
            )

    def test_broken_json_falls_back_to_defaults(self):
        self.assertEqual(
            [e.source_id for e in SourceList.from_json("{not json").entries],
            list(DEFAULT_SOURCE_ORDER),
        )

    def test_unknown_builtin_ids_are_dropped_but_ai_entries_survive(self):
        raw = json.dumps({
            "version": 1,
            "entries": [
                {"id": "google", "kind": "free", "rules": ["all"]},
                {"id": "yandex", "kind": "free", "rules": ["all"]},
                {"id": "ai:abcd1234", "kind": "ai", "name": "X", "api_type": "openai", "rules": []},
            ],
        })
        sources = SourceList.from_json(raw)
        self.assertEqual([e.source_id for e in sources.entries], ["google", "ai:abcd1234"])

    def test_clone_is_independent(self):
        sources = SourceList()
        clone = sources.clone()
        clone.set_rule("google", RULE_ALL, False)
        self.assertIn(RULE_ALL, sources.find("google").rules)
        self.assertNotIn(RULE_ALL, clone.find("google").rules)


class ValidationTests(unittest.TestCase):
    def test_invalid_rules_are_ignored_on_load(self):
        raw = json.dumps({"version": 1, "entries": [
            {"id": "google", "kind": "free", "rules": ["all", "bogus"]},
        ]})
        self.assertEqual(SourceList.from_json(raw).find("google").rules, [RULE_ALL])

    def test_ai_entry_without_name_still_loads(self):
        raw = json.dumps({"version": 1, "entries": [
            {"id": "ai:1", "kind": "ai", "api_type": "openai", "rules": ["all"]},
        ]})
        entry = SourceList.from_json(raw).entries[0]
        self.assertEqual(entry.name, "")
        self.assertEqual(entry.api_type, "openai")
        self.assertEqual(entry.concurrency, 1)
        self.assertEqual(entry.interval, 0.0)
