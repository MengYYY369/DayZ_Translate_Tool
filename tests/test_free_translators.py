import json
import unittest
import urllib.parse

from free_translators import (
    FREE_SOURCE_SPECS,
    FREE_TRANSLATOR_CLASSES,
    GoogleWebTranslator,
    LaraTranslator,
    MicrosoftEdgeTranslator,
    MyMemoryTranslator,
    TencentInteractiveTranslator,
    VolcanoTranslator,
    map_language,
)


class FakeHttp:
    """记录请求并返回预置响应；用来替代 urllib，不碰网络。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, method, body, headers):
        self.calls.append({"url": url, "method": method, "body": body, "headers": headers or {}})
        if not self.responses:
            raise AssertionError("FakeHttp ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def body_json(self, index=0):
        return json.loads(self.calls[index]["body"].decode("utf-8"))

    def body_form(self, index=0):
        return urllib.parse.parse_qs(self.calls[index]["body"].decode("utf-8"))


def make(cls, responses, **kwargs):
    http = FakeHttp(responses)
    translator = cls(request_func=http, **kwargs)
    return translator, http


class LanguageMappingTests(unittest.TestCase):
    def test_zh_cn_maps_to_zh_for_tencent_and_volcano(self):
        self.assertEqual(map_language("tencent", "zh-CN", "target"), "zh")
        self.assertEqual(map_language("volcano", "zh-CN", "target"), "zh")
        self.assertEqual(map_language("microsoft", "zh-CN", "target"), "zh-CN")
        self.assertEqual(map_language("lara", "zh-CN", "target"), "zh-CN")
        self.assertEqual(map_language("mymemory", "zh-CN", "target"), "zh-CN")

    def test_plain_codes_pass_through(self):
        for source_id in FREE_TRANSLATOR_CLASSES:
            self.assertEqual(map_language(source_id, "pt", "target"), "pt")
            self.assertEqual(map_language(source_id, "ja", "target"), "ja")

    def test_auto_is_omitted_for_microsoft_and_lara(self):
        self.assertIsNone(map_language("microsoft", "auto", "source"))
        self.assertIsNone(map_language("lara", "auto", "source"))

    def test_auto_is_literal_for_google_tencent_volcano(self):
        self.assertEqual(map_language("google", "auto", "source"), "auto")
        self.assertEqual(map_language("tencent", "auto", "source"), "auto")
        self.assertEqual(map_language("volcano", "auto", "source"), "auto")

    def test_auto_falls_back_to_english_for_mymemory(self):
        self.assertEqual(map_language("mymemory", "auto", "source"), "en")

    def test_empty_code_returns_none(self):
        self.assertIsNone(map_language("google", "", "source"))
        self.assertIsNone(map_language("google", None, "source"))


class SplitTextTests(unittest.TestCase):
    def test_short_text_is_not_split(self):
        translator, _ = make(VolcanoTranslator, [])
        self.assertEqual(translator.split_text("Knife"), ["Knife"])

    def test_text_over_char_limit_splits_on_line_boundaries(self):
        translator, _ = make(VolcanoTranslator, [])
        text = "a" * 600 + "\n" + "b" * 600
        pieces = translator.split_text(text)
        self.assertEqual(len(pieces), 2)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece), 1000)

    def test_single_long_line_is_hard_split(self):
        translator, _ = make(VolcanoTranslator, [])
        text = "x" * 2500
        pieces = translator.split_text(text)
        self.assertEqual(len(pieces), 3)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece), 1000)

    def test_byte_limit_uses_utf8_length(self):
        translator, _ = make(MyMemoryTranslator, [])
        text = "刀" * 200          # 600 UTF-8 字节
        pieces = translator.split_text(text)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece.encode("utf-8")), 500)

    def test_empty_text_returns_single_empty_piece(self):
        translator, _ = make(VolcanoTranslator, [])
        self.assertEqual(translator.split_text(""), [""])


class MicrosoftEdgeTranslatorTests(unittest.TestCase):
    def test_batch_posts_json_array_and_reads_translations(self):
        translator, http = make(
            MicrosoftEdgeTranslator,
            [[{"translations": [{"text": "刀"}]}, {"translations": [{"text": "枪"}]}]],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertIn("edge.microsoft.com/translate/translatetext", call["url"])
        self.assertIn("to=zh-CN", call["url"])
        self.assertIn("from=en", call["url"])
        self.assertEqual(http.body_json(), ["Knife", "Gun"])

    def test_auto_source_omits_from_parameter(self):
        translator, http = make(
            MicrosoftEdgeTranslator,
            [[{"translations": [{"text": "刀"}]}]],
            source="auto", target="zh-CN",
        )
        translator.translate_batch(["Knife"])
        self.assertNotIn("from=", http.calls[0]["url"])


class GoogleWebTranslatorTests(unittest.TestCase):
    def test_batch_posts_form_and_reads_flat_array(self):
        translator, http = make(
            GoogleWebTranslator, [["刀", "枪"]], source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        call = http.calls[0]
        self.assertIn("translate_a/t", call["url"])
        self.assertEqual(call["method"], "POST")
        self.assertIn("Content-Type", call["headers"])
        form = http.body_form()
        self.assertEqual(form["client"], ["gtx"])
        self.assertEqual(form["sl"], ["en"])
        self.assertEqual(form["q"], ["Knife", "Gun"])

    def test_auto_source_reads_nested_array(self):
        translator, _ = make(
            GoogleWebTranslator, [[["刀", "en"], ["枪", "en"]]], source="auto", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])


class TencentInteractiveTranslatorTests(unittest.TestCase):
    def test_batch_posts_text_list(self):
        translator, http = make(
            TencentInteractiveTranslator,
            [{"header": {"ret_code": "succ"}, "auto_translation": ["刀", "枪"]}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        payload = http.body_json()
        self.assertEqual(payload["source"]["text_list"], ["Knife", "Gun"])
        self.assertEqual(payload["source"]["lang"], "en")
        self.assertEqual(payload["target"]["lang"], "zh")
        self.assertEqual(payload["header"]["fn"], "auto_translation")

    def test_non_succ_ret_code_raises(self):
        translator, _ = make(
            TencentInteractiveTranslator,
            [{"header": {"ret_code": "outOfLimit", "message": "too many"}}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife"])
        self.assertIn("outOfLimit", str(ctx.exception))


class VolcanoTranslatorTests(unittest.TestCase):
    def test_single_text_request(self):
        translator, http = make(
            VolcanoTranslator,
            [{"translation": "刀", "base_resp": {"status_code": 0}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        payload = http.body_json()
        self.assertEqual(payload["text"], "Knife")
        self.assertEqual(payload["target_language"], "zh")

    def test_non_zero_status_code_raises(self):
        translator, _ = make(
            VolcanoTranslator,
            [{"translation": "", "base_resp": {"status_code": 100, "status_message": "bad"}}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception):
            translator.translate_batch(["Knife"])

    def test_batch_issues_one_request_per_text(self):
        translator, http = make(
            VolcanoTranslator,
            [{"translation": "刀", "base_resp": {"status_code": 0}},
             {"translation": "枪", "base_resp": {"status_code": 0}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife", "Gun"]), ["刀", "枪"])
        self.assertEqual(len(http.calls), 2)


class LaraTranslatorTests(unittest.TestCase):
    def test_reads_nested_translation(self):
        translator, http = make(
            LaraTranslator,
            [{"status": 200, "content": {"translations": [{"translation": "刀"}]}}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        payload = http.body_json()
        self.assertEqual(payload["q"], "Knife")
        self.assertEqual(payload["source"], "en")
        self.assertEqual(payload["source_hint"], "")
        self.assertIn("X-Lara-Client", http.calls[0]["headers"])

    def test_auto_source_omits_source_and_source_hint(self):
        translator, http = make(
            LaraTranslator,
            [{"status": 200, "content": {"translations": [{"translation": "刀"}]}}],
            source="auto", target="zh-CN",
        )
        translator.translate_batch(["Knife"])
        payload = http.body_json()
        self.assertNotIn("source", payload)
        self.assertNotIn("source_hint", payload)


class MyMemoryTranslatorTests(unittest.TestCase):
    def test_reads_response_data(self):
        translator, http = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "刀"}, "responseStatus": 200, "quotaFinished": False}],
            source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        self.assertIn("langpair=en%7Czh-CN", http.calls[0]["url"])

    def test_quota_finished_raises_rate_limit_error(self):
        translator, _ = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"},
              "responseStatus": 200, "quotaFinished": True}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife"])
        self.assertEqual(getattr(ctx.exception, "status", None), 429)

    def test_error_status_raises(self):
        translator, _ = make(
            MyMemoryTranslator,
            [{"responseData": {"translatedText": "INVALID SOURCE LANGUAGE"}, "responseStatus": "403"}],
            source="en", target="zh-CN",
        )
        with self.assertRaises(Exception):
            translator.translate_batch(["Knife"])


class ResponseShapeTests(unittest.TestCase):
    def test_wrong_translation_count_raises(self):
        translator, _ = make(
            GoogleWebTranslator, [["刀"]], source="en", target="zh-CN",
        )
        with self.assertRaises(Exception) as ctx:
            translator.translate_batch(["Knife", "Gun"])
        self.assertIn("2", str(ctx.exception))

    def test_translate_single_wraps_batch(self):
        translator, _ = make(
            GoogleWebTranslator, [["刀"]], source="en", target="zh-CN",
        )
        self.assertEqual(translator.translate("Knife"), "刀")


class RegistryTests(unittest.TestCase):
    def test_every_spec_has_a_class(self):
        self.assertTrue(set(FREE_TRANSLATOR_CLASSES) <= set(FREE_SOURCE_SPECS))

    def test_class_specs_match_registry(self):
        for source_id, cls in FREE_TRANSLATOR_CLASSES.items():
            spec = FREE_SOURCE_SPECS[source_id]
            self.assertEqual(cls.MAX_ITEMS, spec["items"])
            self.assertEqual(cls.MAX_CHARS, spec["chars"])
            self.assertEqual(cls.MAX_BYTES, spec["bytes"])
            self.assertEqual(cls.MIN_INTERVAL, spec["interval"])
            self.assertEqual(cls.CONCURRENCY, spec["concurrency"])
