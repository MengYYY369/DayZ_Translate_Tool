import dataclasses
import unittest

from translator_service import (
    TranslationCancelled,
    TranslationJob,
    TranslationRequestError,
    TranslationService,
    TranslatorConfig,
)


class RecordingTranslator:
    """按 (source, target) 返回译文；可以配置成抛错或部分失败。"""

    def __init__(self, mapping, fail_texts=(), error=None):
        self.mapping = mapping
        self.fail_texts = set(fail_texts)
        self.error = error
        self.calls = []

    def translate_batch(self, texts):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [self.mapping.get(text, f"[{text}]") for text in texts]


class FallbackTests(unittest.TestCase):
    def build(self, translators):
        """translators: {provider: RecordingTranslator}"""
        service = TranslationService(
            provider_factory=lambda source, target, config: translators[config.provider]
        )
        return service

    def configs(self, *providers):
        return [
            TranslatorConfig(provider=p, label=p, parallel_batches=1, min_interval=0.0)
            for p in providers
        ]

    def test_first_source_handles_everything_when_it_works(self):
        first = RecordingTranslator({"Knife": "刀"})
        second = RecordingTranslator({"Knife": "X"})
        service = self.build({"google": first, "microsoft": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(jobs, self.configs("google", "microsoft"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(second.calls, [])
        self.assertEqual(results.failed, 0)

    def test_falls_back_when_the_probe_fails(self):
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        good = RecordingTranslator({"Knife": "刀"})
        service = self.build({"microsoft": broken, "google": good})
        seen = []
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(
            jobs, self.configs("microsoft", "google"), on_fallback=lambda a, b: seen.append((a, b))
        )
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(seen, [("microsoft", "google")])

    def test_fallback_only_retries_the_failed_cells(self):
        # 第一个源只有部分文本能翻：整批会被记失败，但已成功的那条应保留
        partial = RecordingTranslator({"Knife": "刀", "Gun": "枪"})
        original = partial.translate_batch

        def flaky(texts):
            if "Gun" in texts:
                raise TranslationRequestError("boom", status=503)
            return original(texts)

        partial.translate_batch = flaky
        good = RecordingTranslator({"Gun": "枪（备）"})
        service = self.build({"microsoft": partial, "google": good})
        jobs = [
            TranslationJob(0, 1, "Knife", "en", "zh-CN"),
            TranslationJob(0, 2, "Gun", "en", "zh-CN"),
        ]
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(results.cell_results[(0, 2)], "枪（备）")
        self.assertEqual(good.calls, [["Gun"]])

    def test_probe_result_is_reused_through_the_cache(self):
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        good = RecordingTranslator({"Knife": "刀", "Gun": "枪"})
        service = self.build({"microsoft": broken, "google": good})
        jobs = [
            TranslationJob(0, 1, "Knife", "en", "zh-CN"),
            TranslationJob(0, 2, "Gun", "en", "zh-CN"),
        ]
        service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        # 试翻只发 Knife；整份只补 Gun。Knife 靠缓存命中，不再发请求。
        self.assertEqual(good.calls, [["Knife"], ["Gun"]])

    def test_all_sources_failing_reports_every_remaining_job(self):
        first = RecordingTranslator({}, error=TranslationRequestError("a", status=503))
        second = RecordingTranslator({}, error=TranslationRequestError("b", status=503))
        service = self.build({"microsoft": first, "google": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertEqual(results.cell_results, {})
        self.assertEqual(results.failed, 1)
        self.assertTrue(results.errors)

    def test_empty_config_list_raises(self):
        service = self.build({})
        with self.assertRaises(ValueError):
            service.translate_jobs_with_fallback([TranslationJob(0, 1, "Knife", "en", "zh-CN")], [])

    def test_cancellation_stops_the_chain(self):
        class CancelOnSecond:
            def __init__(self):
                self.calls = 0

            def translate_batch(self, texts):
                self.calls += 1
                raise TranslationCancelled()

        service = self.build({"google": CancelOnSecond()})
        state = {"cancelled": False}
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        results = service.translate_jobs_with_fallback(
            jobs, self.configs("google", "microsoft"), should_cancel=lambda: state["cancelled"]
        )
        self.assertTrue(results.cancelled)

    def test_a_second_source_takes_over_when_the_first_is_dead(self):
        # 第二个源**故意不用 AI provider**（openai / claude / codex）：AI 源走
        # `_translate_openai_jobs` → `_translate_one_openai_batch`，那里调的是
        # `translator.translate_job_batch(...)` 而不是 `translate_batch(...)`
        # （`translator_service.py:583`），RecordingTranslator 没实现那个方法。
        # 「AI 源也参与降级」由 Task 5 的
        # `test_ai_source_config_uses_its_own_concurrency_and_interval` 覆盖
        # （它证明 AI 源确实会出现在 configs 列表里、顺序不变）。
        broken = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        second = RecordingTranslator({"Knife": "刀"})
        service = self.build({"google": broken, "deepl": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        configs = self.configs("google", "deepl")
        # DeepL 是唯一要密钥的免费源，不补会被 validate_translator_config 拦下
        configs[1] = dataclasses.replace(configs[1], api_key="k")
        results = service.translate_jobs_with_fallback(jobs, configs)
        self.assertEqual(results.cell_results[(0, 1)], "刀")

    def test_fallback_is_not_remembered(self):
        """第二次调用仍然从列表第一个源开始试。"""
        first = RecordingTranslator({}, error=TranslationRequestError("boom", status=503))
        second = RecordingTranslator({"Knife": "刀"})
        service = self.build({"microsoft": first, "google": second})
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        first.error = None
        first.mapping["Knife"] = "刀（首选）"
        first.calls.clear()
        results = service.translate_jobs_with_fallback(jobs, self.configs("microsoft", "google"))
        self.assertTrue(first.calls)
        self.assertEqual(results.cell_results[(0, 1)], "刀（首选）")
