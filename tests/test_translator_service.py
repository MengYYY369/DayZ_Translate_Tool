import io
import json
import threading
import time
import unittest
import urllib.error
from unittest import mock

from translator_service import DEFAULT_CHAR_BUDGET, DEFAULT_OUTPUT_CHAR_CAP, AdaptiveGate, OpenAICompatibleTranslator, RETRY_MAX_ATTEMPTS, RateLimiter, RetryPolicy, TranslationCancelled, TranslationJob, TranslationRequestError, TranslationService, TranslatorConfig, TranslationResults, assign_batch_ids, matching_glossary_entries, parse_numbered_translations, parse_retry_after, retry_call, salvage_truncated_object, validate_translator_config


class FakeBatchTranslator:
    def __init__(self):
        self.calls = []

    def translate_batch(self, texts):
        self.calls.append(list(texts))
        return [f"translated:{text}" for text in texts]


class TranslationServiceTests(unittest.TestCase):
    def test_batches_by_language_direction_and_dedupes_texts(self):
        fake = FakeBatchTranslator()
        created = []

        def factory(source, target):
            created.append((source, target))
            return fake

        # char_budget=10：3 行分 2 批（行 0,1 + 行 2），批内去重
        service = TranslationService(provider_factory=factory)
        config = TranslatorConfig(provider="google", char_budget=10)
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Knife", "en", "de"),
            TranslationJob(2, 3, "Gun", "en", "de"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(created, [("en", "de")])
        # 批 1（行 0,1）去重后 ["Knife"]，批 2（行 2）["Gun"]
        self.assertEqual(fake.calls, [["Knife"], ["Gun"]])
        self.assertEqual(results.translated, 3)
        self.assertEqual(results.failed, 0)
        self.assertEqual(results.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(1, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(2, 3)], "translated:Gun")

    def test_char_budget_groups_jobs_by_row_count(self):
        """char_budget 按字数封批：短行可以共享一批。"""
        fake = FakeBatchTranslator()
        service = TranslationService(provider_factory=lambda source, target: fake)
        # 4 行 × 1 字，char_budget=2 → 2 批，每批 2 行
        config = TranslatorConfig(provider="google", char_budget=2)
        jobs = [
            TranslationJob(0, 3, "A", "en", "de"),
            TranslationJob(1, 3, "B", "en", "de"),
            TranslationJob(2, 3, "C", "en", "de"),
            TranslationJob(3, 3, "D", "en", "de"),
        ]

        service.translate_jobs(jobs, config)

        # 批1 [A,B]，批2 [C,D]
        self.assertEqual(fake.calls, [["A", "B"], ["C", "D"]])

    def test_char_budget_rows_groups_multi_target_per_row(self):
        """OpenAI 多语言场景：一行多个语言单元格必须落在同一批里。"""
        calls = []

        class FakeOpenAITranslator:
            def __init__(self, source, target, api_key, model, base_url, glossary,
                         glossary_source_key="", timeout=60.0, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):

                pass

            def translate_job_batch(self, jobs, assigned=None):
                calls.append(list(jobs))
                return {
                    item_id: {job.target_code: f"{job.target_code}:{job.text}" for job in row_jobs}
                    for item_id, row_jobs in (assigned or assign_batch_ids(jobs)).items()
                }

        service = TranslationService()
        service.openai_translator_class = FakeOpenAITranslator
        config = TranslatorConfig(provider="openai", api_key="key", model="m", char_budget=5)
        # 2 行，每行 2 个语言 → char_budget=5 → 2 批，每批 1 行 2 个 job
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
            TranslationJob(1, 4, "Gun", "en", "de"),
            TranslationJob(1, 5, "Gun", "en", "ru"),
        ]

        results = service.translate_jobs(jobs, config)

        # 2 批，每批 1 行的 2 个 job
        self.assertEqual(len(calls), 2)
        self.assertEqual([j.row for j in calls[0]], [0, 0])
        self.assertEqual([j.row for j in calls[1]], [1, 1])
        self.assertEqual(results.cell_results[(0, 4)], "de:Knife")
        self.assertEqual(results.cell_results[(1, 5)], "ru:Gun")

    def test_cache_prevents_second_batch_call(self):
        fake = FakeBatchTranslator()
        service = TranslationService(provider_factory=lambda source, target: fake)
        config = TranslatorConfig(provider="google")
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first = service.translate_jobs(jobs, config)
        second = service.translate_jobs(jobs, config)

        self.assertEqual(fake.calls, [["Knife"]])
        self.assertEqual(first.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cache_hits, 1)

    def test_shared_cache_reused_across_service_instances(self):
        # 模拟窗口多次翻译：每次运行新建 service 但共享同一个缓存字典
        fake = FakeBatchTranslator()
        shared_cache = {}
        config = TranslatorConfig(provider="google")
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        first = first_service.translate_jobs(jobs, config)
        second_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        second = second_service.translate_jobs(jobs, config)

        self.assertEqual(fake.calls, [["Knife"]])
        self.assertEqual(first.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cache_hits, 1)

    def test_cache_miss_when_model_changes(self):
        class FakeJobBatchTranslator:
            def __init__(self):
                self.calls = []

            def translate_job_batch(self, jobs, assigned=None):
                self.calls.append([job.text for job in jobs])
                return {
                    item_id: {job.target_code: f"translated:{job.text}" for job in row_jobs}
                    for item_id, row_jobs in (assigned or assign_batch_ids(jobs)).items()
                }

        fake = FakeJobBatchTranslator()
        shared_cache = {}
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        first = first_service.translate_jobs(jobs, TranslatorConfig(provider="openai", api_key="k", model="gpt-4o-mini"))
        # 相同 model 命中缓存
        same_model_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        same_model = same_model_service.translate_jobs(jobs, TranslatorConfig(provider="openai", api_key="k", model="gpt-4o-mini"))
        # 更换 model 不命中旧缓存
        changed_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        changed = changed_service.translate_jobs(jobs, TranslatorConfig(provider="openai", api_key="k", model="gpt-4o"))

        self.assertEqual(first.translated, 1)
        self.assertEqual(same_model.cache_hits, 1)
        self.assertEqual(changed.cache_hits, 0)
        self.assertEqual(fake.calls, [["Knife"], ["Knife"]])

    def test_cache_hit_when_glossary_changes(self):
        """决定 6：改单词本不作废已有译文，缓存照常命中。"""
        fake = FakeBatchTranslator()
        shared_cache = {}
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        first_service.translate_jobs(jobs, TranslatorConfig(provider="google"))
        second_service = TranslationService(provider_factory=lambda source, target: fake, cache=shared_cache)
        second = second_service.translate_jobs(
            jobs,
            TranslatorConfig(provider="google", glossary=[{"english": "Knife", "german": "Messer"}]),
        )

        self.assertEqual(second.cache_hits, 1)

    def test_batch_failure_records_error_and_continues_next_direction(self):
        class FailingTranslator:
            def translate_batch(self, texts):
                raise RuntimeError("network down")

        ok = FakeBatchTranslator()

        def factory(source, target):
            if target == "de":
                return FailingTranslator()
            return ok

        service = TranslationService(provider_factory=factory)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(0, 4, "Knife", "en", "fr"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(results.failed, 1)
        self.assertEqual(results.cell_results[(0, 4)], "translated:Knife")
        self.assertTrue(results.errors)

    def test_cancel_stops_before_processing_later_groups(self):
        fake = FakeBatchTranslator()
        calls = 0

        def should_cancel():
            nonlocal calls
            calls += 1
            return calls > 1

        service = TranslationService(provider_factory=lambda source, target: fake)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(0, 4, "Knife", "en", "fr"),
        ]

        results = service.translate_jobs(jobs, config, should_cancel=should_cancel)

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(results.translated, 1)

    def test_cancel_stops_between_batches_in_single_thread_mode(self):
        """单线程模式下批次之间检查 should_cancel，取消后不处理后续批次。"""
        fake = FakeBatchTranslator()
        translate_count = 0

        def should_cancel():
            # 第一批翻译完成后返回 True
            return translate_count >= 1

        service = TranslationService(provider_factory=lambda source, target: fake)
        config = TranslatorConfig(provider="google", char_budget=5)
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Gun", "en", "de"),
            TranslationJob(2, 3, "Hat", "en", "de"),
        ]

        original_translate = fake.translate_batch

        def counting_translate(texts):
            nonlocal translate_count
            translate_count += 1
            return original_translate(texts)

        fake.translate_batch = counting_translate
        results = service.translate_jobs(jobs, config, should_cancel=should_cancel)

        # 第一批处理后 should_cancel 返回 True，后续批次不处理
        self.assertEqual(translate_count, 1)
        self.assertEqual(results.translated, 1)

    def test_parallel_batches_run_more_than_one_batch_at_a_time(self):
        class BlockingTranslator:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def translate_batch(self, texts):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self.lock:
                    self.active -= 1
                return [f"translated:{text}" for text in texts]

        fake = BlockingTranslator()
        service = TranslationService(provider_factory=lambda source, target, config: fake)
        config = TranslatorConfig(provider="google", parallel_batches=3, char_budget=5)
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Gun", "en", "de"),
            TranslationJob(2, 3, "Hat", "en", "de"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertGreaterEqual(fake.max_active, 2)
        self.assertEqual(results.translated, 3)

    def test_provider_factory_receives_config_for_keyed_engines(self):
        seen = []

        def factory(source, target, config):
            seen.append((source, target, config.provider, config.api_key, config.region, config.model, config.email, config.base_url))
            return FakeBatchTranslator()

        service = TranslationService(provider_factory=factory)
        config = TranslatorConfig(
            provider="microsoft",
            api_key="key",
            region="eastus",
            model="gpt-test",
            email="me@example.com",
            base_url="https://example.test/v1",
        )

        service.translate_jobs([TranslationJob(0, 3, "Knife", "en", "de")], config)

        self.assertEqual(seen, [("en", "de", "microsoft", "key", "eastus", "gpt-test", "me@example.com", "https://example.test/v1")])

    def test_validate_translator_config_requires_keys_for_keyed_engines(self):
        with self.assertRaises(ValueError):
            validate_translator_config(TranslatorConfig(provider="deepl"))
        with self.assertRaises(ValueError):
            validate_translator_config(TranslatorConfig(provider="openai"))

        validate_translator_config(TranslatorConfig(provider="google"))
        validate_translator_config(TranslatorConfig(provider="mymemory"))
        validate_translator_config(TranslatorConfig(provider="deepl", api_key="key"))
        validate_translator_config(TranslatorConfig(provider="openai", api_key="key"))
        validate_translator_config(TranslatorConfig(provider="chatgpt", api_key="key"))

    def test_openai_provider_uses_base_url(self):
        seen = {}

        class FakeOpenAITranslator:
            def __init__(self, source, target, api_key, model, base_url, glossary,
                         glossary_source_key="", timeout=60.0, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):

                seen.update(
                    {
                        "source": source,
                        "target": target,
                        "api_key": api_key,
                        "model": model,
                        "base_url": base_url,
                        "glossary": glossary,
                    }
                )

        service = TranslationService(provider_factory=None)
        service.openai_translator_class = FakeOpenAITranslator
        config = TranslatorConfig(
            provider="openai",
            api_key="key",
            model="gpt-4o-mini",
            base_url="https://example.test/v1",
            glossary=[{"english": "Knife", "german": "Messer"}],
        )

        provider = service.create_provider("en", "zh-CN", config)

        self.assertIsInstance(provider, FakeOpenAITranslator)
        self.assertEqual(seen["source"], "en")
        self.assertEqual(seen["target"], "zh-CN")
        self.assertEqual(seen["api_key"], "key")
        self.assertEqual(seen["model"], "gpt-4o-mini")
        self.assertEqual(seen["base_url"], "https://example.test/v1")
        self.assertEqual(seen["glossary"], [{"english": "Knife", "german": "Messer"}])

    def test_openai_translator_posts_batch_to_chat_completions(self):
        calls = []

        def fake_post(url, headers, payload):
            calls.append((url, headers, payload))
            return {"choices": [{"message": {"content": json.dumps(["刀", "枪"])}}]}

        translator = OpenAICompatibleTranslator(
            source="en",
            target="zh-CN",
            api_key="key",
            model="gpt-4o-mini",
            base_url="https://example.test/v1",
            post_json=fake_post,
        )

        result = translator.translate_batch(["Knife", "Gun"])

        self.assertEqual(result, ["刀", "枪"])
        self.assertEqual(calls[0][0], "https://example.test/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer key")
        self.assertEqual(calls[0][2]["model"], "gpt-4o-mini")
        self.assertIn('"Knife"', calls[0][2]["messages"][1]["content"])

    def test_openai_translator_accepts_full_chat_completions_url(self):
        seen_urls = []

        def fake_post(url, headers, payload):
            seen_urls.append(url)
            return {"choices": [{"message": {"content": json.dumps(["刀"])}}]}

        translator = OpenAICompatibleTranslator(
            source="en",
            target="zh-CN",
            api_key="key",
            model="gpt-4o-mini",
            base_url="https://example.test/openai/deployments/model/chat/completions",
            post_json=fake_post,
        )

        self.assertEqual(translator.translate_batch(["Knife"]), ["刀"])
        self.assertEqual(seen_urls, ["https://example.test/openai/deployments/model/chat/completions"])

    def test_openai_translator_posts_mixed_target_job_batch(self):
        calls = []

        def fake_post(url, headers, payload):
            calls.append(payload)
            return {"choices": [{"message": {"content": json.dumps({"1": {"de": "Messer", "ru": "Нож"}})}}]}

        translator = OpenAICompatibleTranslator(
            source="auto",
            target="multi",
            api_key="key",
            model="gpt-4o-mini",
            base_url="https://example.test/v1",
            post_json=fake_post,
        )
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
        ]

        result = translator.translate_job_batch(jobs)

        self.assertEqual(result, {1: {"de": "Messer", "ru": "Нож"}})
        self.assertIn('"targets": ["de", "ru"]', calls[0]["messages"][1]["content"])

    def test_openai_translator_includes_glossary_in_job_batch_prompt(self):
        calls = []

        def fake_post(url, headers, payload):
            calls.append(payload)
            return {"choices": [{"message": {"content": json.dumps({"1": {"de": "Messer"}})}}]}

        translator = OpenAICompatibleTranslator(
            source="auto",
            target="multi",
            api_key="key",
            model="gpt-4o-mini",
            base_url="https://example.test/v1",
            glossary=[{"english": "Knife", "german": "Messer"}],
            post_json=fake_post,
        )

        translator.translate_job_batch([TranslationJob(0, 4, "Knife", "en", "de")])

        content = calls[0]["messages"][1]["content"]
        self.assertIn('"glossary"', content)
        self.assertIn('"english": "Knife"', content)
        self.assertIn('"german": "Messer"', content)

    def test_openai_service_batches_mixed_targets_together(self):
        calls = []

        class FakeOpenAITranslator:
            def __init__(self, source, target, api_key, model, base_url, glossary,
                         glossary_source_key="", timeout=60.0, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):

                pass

            def translate_job_batch(self, jobs, assigned=None):
                calls.append(list(jobs))
                return {
                    item_id: {job.target_code: f"{job.target_code}:{job.text}" for job in row_jobs}
                    for item_id, row_jobs in (assigned or assign_batch_ids(jobs)).items()
                }

        service = TranslationService()
        service.openai_translator_class = FakeOpenAITranslator
        config = TranslatorConfig(provider="openai", api_key="key", model="gpt-4o-mini")
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(len(calls), 1)
        self.assertEqual([job.target_code for job in calls[0]], ["de", "ru"])
        self.assertEqual(results.cell_results[(0, 4)], "de:Knife")
        self.assertEqual(results.cell_results[(0, 5)], "ru:Knife")

    def test_progress_contains_cell_results_after_each_finished_batch(self):
        fake = FakeBatchTranslator()
        service = TranslationService(provider_factory=lambda source, target, config: fake)
        config = TranslatorConfig(provider="google", parallel_batches=1, char_budget=5)
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Gun", "en", "de"),
        ]
        snapshots = []

        service.translate_jobs(jobs, config, progress_callback=lambda results: snapshots.append(dict(results.cell_results)))

        self.assertEqual(snapshots[0], {(0, 3): "translated:Knife"})
        self.assertEqual(snapshots[-1], {(0, 3): "translated:Knife", (1, 3): "translated:Gun"})

    def test_translator_config_default_timeout_is_60_seconds(self):
        config = TranslatorConfig(provider="openai")
        self.assertEqual(config.timeout, 60.0)

    def test_openai_translator_stores_configured_timeout(self):
        translator = OpenAICompatibleTranslator(
            source="auto", target="multi", api_key="key", model="m", timeout=42.0,
        )
        self.assertEqual(translator.timeout, 42.0)

    def test_openai_post_json_raises_translation_cancelled(self):
        translator = OpenAICompatibleTranslator(
            source="auto", target="multi", api_key="key", model="m",
            should_cancel=lambda: True,
        )
        with self.assertRaises(TranslationCancelled):
            translator.translate_batch(["Knife"])

    def test_translate_jobs_marks_cancelled_on_translation_cancelled(self):
        class CancellingTranslator:
            def __init__(self, *args, **kwargs):
                pass

            def translate_job_batch(self, jobs, assigned=None):
                raise TranslationCancelled()

        service = TranslationService()
        service.openai_translator_class = CancellingTranslator
        config = TranslatorConfig(provider="openai", api_key="key", model="m")
        jobs = [TranslationJob(0, 4, "Knife", "en", "de")]

        results = service.translate_jobs(jobs, config)

        self.assertTrue(results.cancelled)


class FreeProviderTests(unittest.TestCase):
    def test_config_carries_label_and_min_interval(self):
        config = TranslatorConfig(provider="microsoft", label="微软翻译", min_interval=0.1)
        self.assertEqual(config.label, "微软翻译")
        self.assertEqual(config.min_interval, 0.1)

    def test_free_providers_need_no_api_key(self):
        for provider in ("google", "microsoft", "tencent", "volcano", "lara", "mymemory"):
            validate_translator_config(TranslatorConfig(provider=provider))

    def test_deepl_still_requires_api_key(self):
        with self.assertRaises(ValueError):
            validate_translator_config(TranslatorConfig(provider="deepl"))

    def test_create_provider_returns_free_client_for_every_free_source(self):
        from free_translators import FREE_TRANSLATOR_CLASSES
        service = TranslationService()
        for source_id, cls in FREE_TRANSLATOR_CLASSES.items():
            provider = service.create_provider("en", "zh-CN", TranslatorConfig(provider=source_id))
            self.assertIsInstance(provider, cls)

    def test_rate_limiter_is_cleared_after_a_run(self):
        service = TranslationService(provider_factory=lambda *a, **k: FakeBatchTranslator())
        config = TranslatorConfig(provider="volcano", min_interval=1.0, parallel_batches=1)
        service.translate_jobs([TranslationJob(0, 1, "Knife", "en", "de")], config)
        self.assertIsNone(service.rate_limiter)     # translate_jobs 结束后清空

    def test_translate_jobs_wires_min_interval_into_rate_limiter(self):
        seen = {}

        class ProbeService(TranslationService):
            def _translate_batches(self, *args, **kwargs):
                seen["interval"] = self.rate_limiter.min_interval
                return None

        service = ProbeService(provider_factory=lambda *a, **k: FakeBatchTranslator())
        service.translate_jobs(
            [TranslationJob(0, 1, "Knife", "en", "de")],
            TranslatorConfig(provider="volcano", min_interval=1.0),
        )
        self.assertEqual(seen["interval"], 1.0)

    def test_google_provider_no_longer_has_a_hardcoded_interval(self):
        import translator_service
        self.assertFalse(hasattr(translator_service, "GOOGLE_MIN_INTERVAL"))


class GoogleProviderIntegrationTests(unittest.TestCase):
    """走真实 urllib 路径（mock.patch urlopen），验证 POST translate_a/t。"""

    def test_end_to_end_translate_via_urllib(self):
        import json as jsonlib
        from unittest import mock

        captured = {}

        class FakeResponse:
            def __init__(self, payload):
                self.payload = jsonlib.dumps(payload).encode("utf-8")

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = request.data
            return FakeResponse(["刀"])

        service = TranslationService()
        jobs = [TranslationJob(0, 1, "Knife", "en", "zh-CN")]
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            results = service.translate_jobs(jobs, TranslatorConfig(provider="google"))
        self.assertEqual(results.cell_results[(0, 1)], "刀")
        self.assertEqual(captured["method"], "POST")
        self.assertIn("translate_a/t", captured["url"])
        self.assertIn(b"q=Knife", captured["body"])

class _FakeSleeper:
    """记录等待时长，不真的睡。"""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds, should_cancel=None):
        self.waits.append(seconds)


class RetryPolicyTests(unittest.TestCase):
    def test_fatal_status_not_retryable(self):
        policy = RetryPolicy()
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                self.assertFalse(policy.is_retryable(TranslationRequestError("bad", status=status)))

    def test_retryable_status(self):
        policy = RetryPolicy()
        for status in (408, 409, 413, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertTrue(policy.is_retryable(TranslationRequestError("again", status=status)))

    def test_url_error_retryable(self):
        # 没有状态码 = 超时 / 连接断 / URLError，一律可重试
        self.assertTrue(RetryPolicy().is_retryable(TranslationRequestError("timeout")))

    def test_delay_grows_and_caps(self):
        policy = RetryPolicy(base_delay=2.0, max_delay=60.0)

        self.assertGreater(policy.delay_for(1), 1.5)
        self.assertLessEqual(policy.delay_for(1), 2.0)
        self.assertGreater(policy.delay_for(3), 6.0)
        self.assertLessEqual(policy.delay_for(3), 8.0)
        self.assertLessEqual(policy.delay_for(10), 60.0)

    def test_retry_after_header_wins(self):
        policy = RetryPolicy(base_delay=2.0, max_delay=60.0)

        self.assertEqual(policy.delay_for(1, retry_after=7.0), 7.0)
        # 0 与超出上限的值都不采信，回落到指数退避
        self.assertLessEqual(policy.delay_for(1, retry_after=0), 2.0)
        self.assertLessEqual(policy.delay_for(1, retry_after=999), 2.0)

    def test_parse_retry_after_milliseconds(self):
        self.assertEqual(parse_retry_after({"retry-after-ms": "1500"}), 1.5)

    def test_parse_retry_after_seconds(self):
        self.assertEqual(parse_retry_after({"Retry-After": "12"}), 12.0)

    def test_parse_retry_after_http_date(self):
        target_epoch = 1792567680.0  # 2026-10-21 07:28:00 UTC
        with mock.patch("translator_service.time.time", return_value=target_epoch - 90.0):
            seconds = parse_retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})

        self.assertAlmostEqual(seconds, 90.0, places=3)

    def test_parse_retry_after_handles_missing(self):
        self.assertIsNone(parse_retry_after(None))
        self.assertIsNone(parse_retry_after({}))
        self.assertIsNone(parse_retry_after({"Retry-After": "not-a-date"}))


class RetryCallTests(unittest.TestCase):
    def test_retry_call_retries_then_succeeds(self):
        sleeper = _FakeSleeper()
        retries = []
        state = {"calls": 0}

        def func():
            state["calls"] += 1
            if state["calls"] < 3:
                raise TranslationRequestError("rate limited", status=429)
            return "ok"

        result = retry_call(
            func,
            RetryPolicy(sleep=sleeper),
            on_retry=lambda attempt, max_attempts, wait: retries.append((attempt, max_attempts, wait)),
        )

        self.assertEqual(result, "ok")
        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(retries), 2)
        self.assertEqual(retries[0][0], 1)
        self.assertEqual(retries[0][1], RETRY_MAX_ATTEMPTS)
        self.assertEqual(len(sleeper.waits), 2)

    def test_retry_call_gives_up_after_max_attempts(self):
        sleeper = _FakeSleeper()
        state = {"calls": 0}

        def func():
            state["calls"] += 1
            raise TranslationRequestError("rate limited", status=429)

        with self.assertRaises(TranslationRequestError):
            retry_call(func, RetryPolicy(max_attempts=5, sleep=sleeper))

        self.assertEqual(state["calls"], 5)

    def test_retry_call_does_not_retry_fatal(self):
        sleeper = _FakeSleeper()
        state = {"calls": 0}

        def func():
            state["calls"] += 1
            raise TranslationRequestError("bad key", status=401)

        with self.assertRaises(TranslationRequestError):
            retry_call(func, RetryPolicy(sleep=sleeper))

        self.assertEqual(state["calls"], 1)

    def test_retry_call_cancel_interrupts_wait(self):
        state = {"calls": 0, "cancelled": False}

        def func():
            state["calls"] += 1
            state["cancelled"] = True
            raise TranslationRequestError("rate limited", status=429)

        # 用真实的 interruptible_sleep：base_delay=60 若真睡就会明显超过 1 秒
        policy = RetryPolicy(base_delay=60.0, max_delay=60.0)
        started = time.monotonic()
        with self.assertRaises(TranslationCancelled):
            retry_call(func, policy, should_cancel=lambda: state["cancelled"])
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(state["calls"], 1)

    def test_before_attempt_runs_on_every_attempt(self):
        """重试不能绕过节流：before_attempt 必须在每次尝试前都跑（含重试）。"""
        sleeper = _FakeSleeper()
        state = {"calls": 0, "before": 0}

        def func():
            state["calls"] += 1
            if state["calls"] < 3:
                raise TranslationRequestError("rate limited", status=429)
            return "ok"

        def before_attempt():
            state["before"] += 1

        result = retry_call(func, RetryPolicy(sleep=sleeper), before_attempt=before_attempt)

        self.assertEqual(result, "ok")
        self.assertEqual(state["before"], 3)


class RateLimiterTests(unittest.TestCase):
    def test_first_acquire_does_not_wait(self):
        limiter = RateLimiter(min_interval=5.0)

        started = time.monotonic()
        limiter.acquire()

        self.assertLess(time.monotonic() - started, 0.05)

    def test_second_acquire_waits_min_interval(self):
        limiter = RateLimiter(min_interval=0.3)

        started = time.monotonic()
        limiter.acquire()
        limiter.acquire()

        self.assertGreaterEqual(time.monotonic() - started, 0.25)

    def test_acquire_honors_cancel(self):
        limiter = RateLimiter(min_interval=5.0)
        limiter.acquire()

        started = time.monotonic()
        with self.assertRaises(TranslationCancelled):
            limiter.acquire(should_cancel=lambda: True)

        self.assertLess(time.monotonic() - started, 1.0)

    def test_set_interval_clamps_negative(self):
        limiter = RateLimiter(min_interval=1.0)
        limiter.set_interval(-5)

        self.assertEqual(limiter.min_interval, 0.0)


class AdaptiveGateTests(unittest.TestCase):
    def test_limit_halves_on_rate_limit(self):
        gate = AdaptiveGate(initial=4, minimum=1, maximum=8)
        self.assertEqual(gate.limit, 4)

        gate.release(rate_limited=True)
        self.assertEqual(gate.limit, 2)
        gate.release(rate_limited=True)
        self.assertEqual(gate.limit, 1)
        gate.release(rate_limited=True)
        self.assertEqual(gate.limit, 1)  # 已到下限，不再降

    def test_limit_recovers_after_successes(self):
        gate = AdaptiveGate(initial=2, minimum=1, maximum=4, recover_after=3)

        for _ in range(3):
            gate.release()
        self.assertEqual(gate.limit, 3)
        for _ in range(3):
            gate.release()
        self.assertEqual(gate.limit, 4)
        for _ in range(3):
            gate.release()
        self.assertEqual(gate.limit, 4)  # 已到上限，不再升

    def test_rate_limit_resets_success_streak(self):
        gate = AdaptiveGate(initial=2, minimum=1, maximum=4, recover_after=3)

        gate.release()
        gate.release()
        gate.release(rate_limited=True)  # 降回 1 并清零连胜
        self.assertEqual(gate.limit, 1)

        gate.release()
        gate.release()
        self.assertEqual(gate.limit, 1)  # 还差一次才回升

    def test_initial_is_clamped_into_range(self):
        self.assertEqual(AdaptiveGate(initial=99, minimum=1, maximum=4).limit, 4)
        self.assertEqual(AdaptiveGate(initial=0, minimum=1, maximum=4).limit, 1)

    def test_acquire_blocks_beyond_limit(self):
        gate = AdaptiveGate(initial=1, minimum=1, maximum=1)
        gate.acquire()

        started = time.monotonic()
        with self.assertRaises(TranslationCancelled):
            gate.acquire(should_cancel=lambda: True)

        self.assertLess(time.monotonic() - started, 1.0)
        gate.release()
        self.assertEqual(gate.active, 0)


class GuardedBatchTests(unittest.TestCase):
    @staticmethod
    def _service_with_gate(gate):
        service = TranslationService()
        service.gate = gate
        service.rate_limiter = None
        return service

    def test_rate_limited_error_halves_gate(self):
        gate = AdaptiveGate(initial=4, minimum=1, maximum=8)
        service = self._service_with_gate(gate)

        def boom():
            raise TranslationRequestError("rate limited", status=429)

        with self.assertRaises(TranslationRequestError):
            service._guarded(boom)

        self.assertEqual(gate.limit, 2)
        self.assertEqual(gate.active, 0)

    def test_non_rate_limit_error_does_not_halve_gate(self):
        gate = AdaptiveGate(initial=4, minimum=1, maximum=8)
        service = self._service_with_gate(gate)

        def boom():
            raise TranslationRequestError("bad key", status=401)

        with self.assertRaises(TranslationRequestError):
            service._guarded(boom)

        self.assertEqual(gate.limit, 4)

    def test_batch_failure_still_counts_jobs_as_failed(self):
        """限速不该让整次运行看起来像被取消。"""

        class RateLimitedTranslator:
            def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                         glossary_source_key="", post_json=None, timeout=60.0, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):
                pass

            def translate_job_batch(self, batch, assigned=None):
                raise TranslationRequestError("rate limited", status=429)

        service = TranslationService()
        service.openai_translator_class = RateLimitedTranslator
        config = TranslatorConfig(provider="openai", api_key="k", model="m")
        jobs = [
            TranslationJob(0, 0, "Knife", "en", "zh-CN"),
            TranslationJob(1, 1, "Axe", "en", "zh-CN"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(results.failed, 2)
        self.assertFalse(results.cancelled)


    def test_google_rate_limit_reaches_gate(self):
        """Google 线路的 429 也必须到达闸门 —— 否则自适应降速对 Google 是死的（修订表问题 18）。"""
        seen = []

        class RecordingGate(AdaptiveGate):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                seen.append(self)

        class RateLimitedGoogle:
            def __init__(self, source, target, timeout=None, should_cancel=None,
                         retry_policy=None, on_retry=None, before_attempt=None):
                pass

            def translate_batch(self, texts):
                raise TranslationRequestError("rate limited", status=429)

        service = TranslationService()
        service.free_translator_classes = {"google": RateLimitedGoogle}
        config = TranslatorConfig(provider="google", parallel_batches=4)
        jobs = [TranslationJob(0, 0, "Knife", "en", "zh-CN")]

        with mock.patch("translator_service.AdaptiveGate", RecordingGate):
            results = service.translate_jobs(jobs, config)

        self.assertEqual(results.failed, 1)
        self.assertFalse(results.cancelled)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].limit, 1)  # initial 2 → 撞 429 → 减半


class RowBatchingTests(unittest.TestCase):
    """按字数预算分批：行永不被劈开，超长行单独成批。"""

    @staticmethod
    def _batches(jobs, char_budget, output_char_cap=DEFAULT_OUTPUT_CHAR_CAP):
        service = TranslationService()
        return list(service.iter_row_batches(jobs, char_budget, output_char_cap))

    def test_short_rows_share_a_batch(self):
        jobs = [TranslationJob(row, 3, "abcde", "en", "de") for row in range(20)]

        batches = self._batches(jobs, 100)

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 20)

    def test_budget_cuts_at_row_boundary(self):
        jobs = [TranslationJob(row, 3, "abcdef", "en", "de") for row in range(5)]

        batches = self._batches(jobs, 10)

        self.assertEqual([len(batch) for batch in batches], [1, 1, 1, 1, 1])

    def test_row_is_never_split(self):
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(0, 4, "Knife", "en", "ru"),
            TranslationJob(0, 5, "Knife", "en", "fr"),
        ]

        batches = self._batches(jobs, 1)

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)

    def test_oversized_row_gets_own_batch(self):
        jobs = [
            TranslationJob(0, 3, "abcde", "en", "de"),
            TranslationJob(1, 3, "x" * 500, "en", "de"),
            TranslationJob(2, 3, "abcde", "en", "de"),
        ]

        batches = self._batches(jobs, 100)

        self.assertEqual([len(batch) for batch in batches], [1, 1, 1])
        self.assertEqual(batches[1][0].row, 1)  # 超长行独占一批，后面的短行不被并进来

    def test_output_cap_cuts_batch(self):
        targets = ["de", "ru", "fr", "es", "it", "pl", "cs", "hu"]
        jobs = [
            TranslationJob(row, 3 + index, "abcdefghij", "en", target)
            for row in range(3)
            for index, target in enumerate(targets)
        ]

        batches = self._batches(jobs, DEFAULT_CHAR_BUDGET, 100)

        # 一行 10 字 × 8 个语言 = 80 字符产出，再加一行就 160 ≥ 100
        self.assertEqual([len(batch) for batch in batches], [8, 8, 8])

    def test_budget_is_not_clamped_upward(self):
        """char_budget=10 时封批阈值就是 10，不是 MIN_CHAR_BUDGET（上一版钳制 bug 的回归闸门）。"""
        jobs = [TranslationJob(row, 3, "abcdef", "en", "de") for row in range(20)]

        batches = self._batches(jobs, 10)

        self.assertEqual(len(batches), 20)

    def test_all_jobs_preserved(self):
        jobs = [
            TranslationJob(row, 3 + index, "w" * (row + 1), "en", target)
            for row in range(7)
            for index, target in enumerate(("de", "ru"))
        ]

        batches = self._batches(jobs, 4, 20)

        flat = [job for batch in batches for job in batch]
        self.assertEqual(len(flat), len(jobs))
        self.assertEqual(
            [(job.row, job.column) for job in flat],
            sorted((job.row, job.column) for job in jobs),
        )


class IdAssignmentTests(unittest.TestCase):
    """id 只在 assign_batch_ids 分配一次：同一行共享一个 id，补发不重新编号。"""

    def test_ids_follow_row_order(self):
        jobs = [TranslationJob(row, 3, f"text{row}", "en", "de") for row in range(3)]

        assigned = assign_batch_ids(jobs)

        self.assertEqual(sorted(assigned), [1, 2, 3])
        self.assertEqual([assigned[1][0].row, assigned[2][0].row, assigned[3][0].row], [0, 1, 2])

    def test_same_row_shares_one_id(self):
        jobs = [
            TranslationJob(0, index, "Knife", "en", target)
            for index, target in enumerate(["de", "ru", "fr", "es", "it", "pl", "cs", "hu"])
        ]

        assigned = assign_batch_ids(jobs)

        self.assertEqual(sorted(assigned), [1])
        self.assertEqual(len(assigned[1]), 8)

    def test_subset_keeps_original_ids(self):
        """补发时传入的是同一份映射的子集，id 必须还是 1 和 3（而不是被重编成 1 和 2）。"""
        jobs = [TranslationJob(row, 3, f"text{row}", "en", "de") for row in range(3)]
        assigned = assign_batch_ids(jobs)

        subset = {key: value for key, value in assigned.items() if key in (1, 3)}
        prompt = _openai_translator().build_merged_prompt(subset)

        self.assertIn('"id": 1', prompt)
        self.assertIn('"id": 3', prompt)
        self.assertNotIn('"id": 2', prompt)


class MergedPromptTests(unittest.TestCase):
    """一行多个目标语言合并成一条 item：源文只出现一次。"""

    def test_source_text_appears_once_per_row(self):
        jobs = [
            TranslationJob(0, index, "Knife", "en", target)
            for index, target in enumerate(["de", "ru", "fr", "es", "it", "pl", "cs", "hu"])
        ]

        prompt = _openai_translator().build_merged_prompt(assign_batch_ids(jobs))

        self.assertEqual(prompt.count('"text": "Knife"'), 1)

    def test_targets_listed_per_item(self):
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
        ]

        prompt = _openai_translator().build_merged_prompt(assign_batch_ids(jobs))

        self.assertIn('"targets": ["de", "ru"]', prompt)
        self.assertNotIn('"target_language"', prompt)

    def test_only_requested_cells_included(self):
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
            TranslationJob(0, 6, "Knife", "en", "fr"),
        ]

        prompt = _openai_translator().build_merged_prompt(assign_batch_ids(jobs))

        self.assertIn('"targets": ["de", "ru", "fr"]', prompt)

    def test_prompt_is_deterministic(self):
        """前缀缓存的前提：同一输入两次拼出的提示词必须逐字节相同。"""
        jobs = [
            TranslationJob(0, 4, "Knife", "en", "de"),
            TranslationJob(0, 5, "Knife", "en", "ru"),
            TranslationJob(1, 4, "Gun", "en", "de"),
        ]
        translator = _openai_translator()

        self.assertEqual(
            translator.build_merged_prompt(assign_batch_ids(jobs)),
            translator.build_merged_prompt(assign_batch_ids(jobs)),
        )


class NumberedParsingTests(unittest.TestCase):
    """解析 {"1": {"chinese": "刀"}} 形状的回复；被腰斩时尽力抢救。"""

    def test_parses_clean_object(self):
        parsed = parse_numbered_translations('{"1": {"chinese": "刀"}, "2": {"chinese": "盾"}}')

        self.assertEqual(parsed, {1: {"chinese": "刀"}, 2: {"chinese": "盾"}})

    def test_strips_code_fence(self):
        content = '```json\n{"1": {"chinese": "刀"}}\n```'

        self.assertEqual(parse_numbered_translations(content), {1: {"chinese": "刀"}})

    def test_salvages_truncated_object(self):
        content = '{"1": {"chinese": "刀"}, "2": {"chinese": "盾"'

        parsed = parse_numbered_translations(content)

        self.assertEqual(parsed, {1: {"chinese": "刀"}})

    def test_rejects_non_object(self):
        with self.assertRaises(TranslationRequestError):
            parse_numbered_translations('["刀"]')

    def test_drops_non_string_values(self):
        self.assertEqual(parse_numbered_translations('{"1": {"chinese": 42}}'), {})

    def test_salvage_returns_input_when_nothing_complete(self):
        self.assertEqual(salvage_truncated_object('{"1": {"chinese"'), '{"1": {"chinese"')


class MissingRecoveryTests(unittest.TestCase):
    """某一行没返回译文时，只补发缺的那些，且 id 不重新编号。"""

    def test_missing_assigned_detected(self):
        service = TranslationService()
        jobs = [TranslationJob(row, 3, f"text{row}", "en", "de") for row in range(3)]
        assigned = assign_batch_ids(jobs)
        parsed = {1: {"de": "A"}, 3: {"de": "C"}}

        missing = service._missing_assigned(assigned, parsed)

        self.assertEqual(sorted(missing), [2])
        self.assertEqual(missing[2], [jobs[1]])

    def test_second_request_covers_only_missing(self):
        calls = []
        script = [{1: {"de": "A"}, 3: {"de": "C"}}, {2: {"de": "B"}}]
        service = _scripted_service(script, calls)
        config = TranslatorConfig(provider="openai", api_key="k", model="m")
        jobs = [TranslationJob(row, row, f"text{row}", "en", "de") for row in range(3)]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(len(calls), 2)
        self.assertEqual([job.row for job in calls[1]["jobs"]], [1])
        self.assertEqual(results.failed, 0)
        self.assertEqual(results.cell_results, {(0, 0): "A", (1, 1): "B", (2, 2): "C"})

    def test_recovery_ids_are_not_renumbered(self):
        """补发的提示词里 id 仍是 2；重编成 1 会把译文写到错误的单元格。"""
        calls = []
        script = [{1: {"de": "A"}, 3: {"de": "C"}}, {2: {"de": "B"}}]
        service = _scripted_service(script, calls)
        config = TranslatorConfig(provider="openai", api_key="k", model="m")
        jobs = [TranslationJob(row, row, f"text{row}", "en", "de") for row in range(3)]

        service.translate_jobs(jobs, config)

        self.assertEqual(sorted(calls[1]["assigned"]), [2])

    def test_still_missing_after_recovery_counts_failed(self):
        calls = []
        script = [{1: {"de": "A"}, 3: {"de": "C"}}, {}]
        service = _scripted_service(script, calls)
        config = TranslatorConfig(provider="openai", api_key="k", model="m")
        jobs = [TranslationJob(row, row, f"text{row}", "en", "de") for row in range(3)]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(results.failed, 1)
        self.assertEqual(results.cell_results, {(0, 0): "A", (2, 2): "C"})


def _openai_translator(**kwargs):
    return OpenAICompatibleTranslator(
        source="auto", target="multi", api_key="key", model="m", **kwargs
    )


class GlossaryFilterTests(unittest.TestCase):
    GLOSSARY = [
        {"english": "Knife", "german": "Messer"},
        {"english": "Gun", "german": "Waffe"},
        {"english": "Ammo", "german": "Munition"},
    ]

    def test_only_matching_entries_included(self):
        matched = matching_glossary_entries(self.GLOSSARY, ["Knife"], "english")
        self.assertEqual(matched, [{"english": "Knife", "german": "Messer"}])

    def test_match_is_case_insensitive(self):
        matched = matching_glossary_entries(self.GLOSSARY, ["KNIFE"], "english")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["english"], "Knife")

    def test_no_match_returns_empty(self):
        self.assertEqual(matching_glossary_entries(self.GLOSSARY, ["Spoon"], "english"), [])

    def test_uses_the_given_source_column(self):
        entry = {"english": "Knife", "german": "Messer"}
        self.assertEqual(matching_glossary_entries([entry], ["Knife"], "english"), [entry])
        self.assertEqual(matching_glossary_entries([entry], ["Knife"], "german"), [])

    def test_source_key_missing_from_entry_is_skipped(self):
        entry = {"german": "Messer"}
        self.assertEqual(matching_glossary_entries([entry], ["Messer"], "english"), [])

    def test_empty_source_key_matches_any_column(self):
        entry = {"english": "Knife", "german": "Messer"}
        self.assertEqual(matching_glossary_entries([entry], ["Messer"], ""), [entry])

    def test_respects_max_entries(self):
        glossary = [{"english": f"term{i}"} for i in range(300)]
        texts = [" ".join(f"term{i}" for i in range(300))]
        matched = matching_glossary_entries(glossary, texts, "english", max_entries=200)
        self.assertEqual(len(matched), 200)

    def test_empty_glossary_or_texts_returns_empty(self):
        self.assertEqual(matching_glossary_entries([], ["Knife"], "english"), [])
        self.assertEqual(matching_glossary_entries(self.GLOSSARY, [], "english"), [])


class GlossaryPromptIntegrationTests(unittest.TestCase):
    def test_translator_uses_config_source_key(self):
        config = TranslatorConfig(
            provider="openai",
            api_key="key",
            model="m",
            glossary=[{"english": "Knife", "german": "Messer"}],
            glossary_source_key="english",
        )
        translator = TranslationService().create_provider("en", "de", config)
        self.assertEqual(translator.glossary_source_key, "english")

    def test_only_matching_entries_reach_the_prompt(self):
        captured = []

        def fake_post(url, headers, payload):
            captured.append(payload)
            return {"choices": [{"message": {"content": json.dumps({"1": {"de": "Messer"}})}}]}

        translator = OpenAICompatibleTranslator(
            source="en",
            target="de",
            api_key="key",
            model="m",
            glossary=[
                {"english": "Knife", "german": "Messer"},
                {"english": "Gun", "german": "Waffe"},
            ],
            glossary_source_key="english",
            post_json=fake_post,
        )
        translator.translate_job_batch([TranslationJob(0, 1, "Knife", "en", "de")])

        content = captured[0]["messages"][1]["content"]
        self.assertIn("Messer", content)
        self.assertNotIn("Waffe", content)

    def test_no_matching_entry_omits_the_glossary_section(self):
        captured = []

        def fake_post(url, headers, payload):
            captured.append(payload)
            return {"choices": [{"message": {"content": json.dumps({"1": {"de": "Loeffel"}})}}]}

        translator = OpenAICompatibleTranslator(
            source="en",
            target="de",
            api_key="key",
            model="m",
            glossary=[{"english": "Knife", "german": "Messer"}],
            glossary_source_key="english",
            post_json=fake_post,
        )
        translator.translate_job_batch([TranslationJob(0, 1, "Spoon", "en", "de")])

        content = captured[0]["messages"][1]["content"]
        self.assertNotIn("Glossary", content)


class RetryWiringTests(unittest.TestCase):
    """429 真的会重试，并且 on_retry 真的被调用（UI 倒计时的上游契约）。"""

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def test_rate_limit_is_retried_and_on_retry_is_called(self):
        seen = []
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    "https://example.test", 429, "Too Many Requests",
                    {"Retry-After": "0.01"}, io.BytesIO(b"rate limited"),
                )
            content = json.dumps({"1": {"de": "Messer"}})
            body = json.dumps({"choices": [{"message": {"content": content}}]})
            return self._FakeResponse(body.encode("utf-8"))

        service = TranslationService()
        service.on_retry = lambda attempt, max_attempts, wait: seen.append((attempt, max_attempts, wait))
        config = TranslatorConfig(
            provider="openai", api_key="k", model="m",
            auto_concurrency=False, parallel_batches=1,
        )

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            results = service.translate_jobs([TranslationJob(0, 1, "Knife", "en", "de")], config)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:2], (1, RETRY_MAX_ATTEMPTS))
        self.assertEqual(results.translated, 1)
        self.assertEqual(results.cell_results[(0, 1)], "Messer")
        self.assertEqual(calls["n"], 2)


def _scripted_service(script, calls):
    """返回一个每次调用 translate_job_batch 就弹出 script 下一项的假 translator。"""

    class ScriptedTranslator:
        def __init__(self, source, target, api_key, model, base_url="", glossary=None,
                     glossary_source_key="", timeout=60.0, should_cancel=None,
                     retry_policy=None, on_retry=None, before_attempt=None):
            pass

        def translate_job_batch(self, jobs, assigned=None):
            calls.append({"jobs": list(jobs), "assigned": dict(assigned or {})})
            return script.pop(0)

    service = TranslationService()
    service.openai_translator_class = ScriptedTranslator
    return service


if __name__ == "__main__":
    unittest.main()
