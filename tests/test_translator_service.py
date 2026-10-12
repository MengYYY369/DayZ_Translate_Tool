import json
import threading
import time
import unittest

from translator_service import GoogleTranslateTranslator, OpenAICompatibleTranslator, TranslationCancelled, TranslationJob, TranslationService, TranslatorConfig, TranslationResults, validate_translator_config


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

        # batch_size=2 行：3 行分 2 批（行 0,1 + 行 2），批内去重
        service = TranslationService(provider_factory=factory, batch_size=2)
        config = TranslatorConfig(provider="google")
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

    def test_batch_size_groups_jobs_by_row_count(self):
        """batch_size 按 行数 切分：每批包含 N 行的所有单元格。"""
        fake = FakeBatchTranslator()
        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=2)
        config = TranslatorConfig(provider="google")
        # 4 行，每行 2 个不同 target 列 → 按 (source,target) 分组后每组 4 个 job（4 行）
        # batch_size=2 行 → 每组 2 批，每批 2 行
        jobs = [
            TranslationJob(0, 3, "A", "en", "de"),
            TranslationJob(1, 3, "B", "en", "de"),
            TranslationJob(2, 3, "C", "en", "de"),
            TranslationJob(3, 3, "D", "en", "de"),
        ]

        service.translate_jobs(jobs, config)

        # 4 行 / batch_size=2 = 2 批：批1 [A,B]，批2 [C,D]
        self.assertEqual(fake.calls, [["A", "B"], ["C", "D"]])

    def test_batch_size_rows_groups_multi_target_per_row(self):
        """OpenAI 多语言场景：batch_size 按行切分，每批包含 N 行的所有语言单元格。"""
        calls = []

        class FakeOpenAITranslator:
            def __init__(self, source, target, api_key, model, base_url, glossary, timeout=60.0, should_cancel=None):
                pass

            def translate_job_batch(self, jobs):
                calls.append(list(jobs))
                return [f"{job.target_code}:{job.text}" for job in jobs]

        service = TranslationService(batch_size=1)
        service.openai_translator_class = FakeOpenAITranslator
        config = TranslatorConfig(provider="openai", api_key="key", model="m")
        # 2 行，每行 2 个语言 → batch_size=1 行 → 2 批，每批 1 行 2 个 job
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
        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30)
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

        first_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
        first = first_service.translate_jobs(jobs, config)
        second_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
        second = second_service.translate_jobs(jobs, config)

        self.assertEqual(fake.calls, [["Knife"]])
        self.assertEqual(first.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cache_hits, 1)

    def test_cache_miss_when_model_changes(self):
        class FakeJobBatchTranslator:
            def __init__(self):
                self.calls = []

            def translate_job_batch(self, jobs):
                self.calls.append([job.text for job in jobs])
                return [f"translated:{job.text}" for job in jobs]

        fake = FakeJobBatchTranslator()
        shared_cache = {}
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
        first = first_service.translate_jobs(jobs, TranslatorConfig(provider="openai", api_key="k", model="gpt-4o-mini"))
        # 相同 model 命中缓存
        same_model_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
        same_model = same_model_service.translate_jobs(jobs, TranslatorConfig(provider="openai", api_key="k", model="gpt-4o-mini"))
        # 更换 model 不命中旧缓存
        changed_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
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

        first_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
        first_service.translate_jobs(jobs, TranslatorConfig(provider="google"))
        second_service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30, cache=shared_cache)
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

        service = TranslationService(provider_factory=factory, batch_size=30)
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

        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30)
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

        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=1)
        config = TranslatorConfig(provider="google")
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
        service = TranslationService(provider_factory=lambda source, target, config: fake, batch_size=1)
        config = TranslatorConfig(provider="google", parallel_batches=3)
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

        service = TranslationService(provider_factory=factory, batch_size=30)
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
            validate_translator_config(TranslatorConfig(provider="microsoft", api_key="key"))
        with self.assertRaises(ValueError):
            validate_translator_config(TranslatorConfig(provider="openai"))

        validate_translator_config(TranslatorConfig(provider="google"))
        validate_translator_config(TranslatorConfig(provider="mymemory"))
        validate_translator_config(TranslatorConfig(provider="deepl", api_key="key"))
        validate_translator_config(TranslatorConfig(provider="microsoft", api_key="key", region="eastus"))
        validate_translator_config(TranslatorConfig(provider="openai", api_key="key"))
        validate_translator_config(TranslatorConfig(provider="chatgpt", api_key="key"))

    def test_openai_provider_uses_base_url(self):
        seen = {}

        class FakeOpenAITranslator:
            def __init__(self, source, target, api_key, model, base_url, glossary, timeout=60.0, should_cancel=None):
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
            return {"choices": [{"message": {"content": json.dumps(["Messer", "Нож"])}}]}

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

        self.assertEqual(result, ["Messer", "Нож"])
        self.assertIn('"target_language": "de"', calls[0]["messages"][1]["content"])
        self.assertIn('"target_language": "ru"', calls[0]["messages"][1]["content"])

    def test_openai_translator_includes_glossary_in_job_batch_prompt(self):
        calls = []

        def fake_post(url, headers, payload):
            calls.append(payload)
            return {"choices": [{"message": {"content": json.dumps(["Messer"])}}]}

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
            def __init__(self, source, target, api_key, model, base_url, glossary, timeout=60.0, should_cancel=None):
                pass

            def translate_job_batch(self, jobs):
                calls.append(list(jobs))
                return [f"{job.target_code}:{job.text}" for job in jobs]

        service = TranslationService(batch_size=10)
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
        service = TranslationService(provider_factory=lambda source, target, config: fake, batch_size=1)
        config = TranslatorConfig(provider="google", parallel_batches=1)
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

            def translate_job_batch(self, jobs):
                raise TranslationCancelled()

        service = TranslationService(batch_size=10)
        service.openai_translator_class = CancellingTranslator
        config = TranslatorConfig(provider="openai", api_key="key", model="m")
        jobs = [TranslationJob(0, 4, "Knife", "en", "de")]

        results = service.translate_jobs(jobs, config)

        self.assertTrue(results.cancelled)


def _google_response(*pairs):
    """Build a fake googleapis.com /translate_a/single response."""
    return [[list(pair) for pair in pairs]]


class GoogleTranslateTranslatorTests(unittest.TestCase):
    def test_translate_single_text(self):
        calls = []

        def fake_request(url, headers):
            calls.append((url, headers))
            return _google_response(("刀", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="zh-CN", request_func=fake_request,
        )

        result = translator.translate("Knife")

        self.assertEqual(result, "刀")
        self.assertIn("translate.googleapis.com/translate_a/single", calls[0][0])
        self.assertIn("sl=en", calls[0][0])
        self.assertIn("tl=zh-CN", calls[0][0])
        self.assertIn("q=Knife", calls[0][0])
        self.assertIn("client=gtx", calls[0][0])

    def test_translate_batch_returns_translations_in_order(self):
        def fake_request(url, headers):
            return _google_response(("Messer", "Knife"), ("Pistole", "Gun"))

        translator = GoogleTranslateTranslator(
            source="en", target="de", request_func=fake_request,
        )

        result = translator.translate_batch(["Knife", "Gun"])

        self.assertEqual(result, ["Messer", "Pistole"])

    def test_translate_batch_empty_returns_empty(self):
        translator = GoogleTranslateTranslator(
            source="en", target="de", request_func=lambda url, headers: [],
        )
        self.assertEqual(translator.translate_batch([]), [])

    def test_translate_batch_count_mismatch_raises(self):
        def fake_request(url, headers):
            return _google_response(("Messer", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="de", request_func=fake_request,
        )

        with self.assertRaises(RuntimeError) as ctx:
            translator.translate_batch(["Knife", "Gun"])
        self.assertIn("1 translations", str(ctx.exception))

    def test_custom_base_url_is_used(self):
        seen_urls = []

        def fake_request(url, headers):
            seen_urls.append(url)
            return _google_response(("刀", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="zh-CN",
            base_url="https://my-mirror.example.com",
            request_func=fake_request,
        )

        translator.translate("Knife")

        self.assertTrue(
            seen_urls[0].startswith("https://my-mirror.example.com/translate_a/single?"),
            f"Expected custom base URL, got {seen_urls[0]}",
        )

    def test_custom_base_url_with_full_path_is_preserved(self):
        seen_urls = []

        def fake_request(url, headers):
            seen_urls.append(url)
            return _google_response(("刀", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="zh-CN",
            base_url="https://my-mirror.example.com/translate_a/single",
            request_func=fake_request,
        )

        translator.translate("Knife")

        self.assertTrue(
            seen_urls[0].startswith("https://my-mirror.example.com/translate_a/single?"),
            f"Expected full path preserved, got {seen_urls[0]}",
        )

    def test_default_timeout_is_15_seconds(self):
        translator = GoogleTranslateTranslator(source="en", target="de")
        self.assertEqual(translator.timeout, 15.0)

    def test_custom_timeout_is_passed_to_urlopen(self):
        captured = {}

        def fake_request(url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return _google_response(("刀", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="zh-CN",
            timeout=5.0,
            request_func=fake_request,
        )

        translator.translate("Knife")
        self.assertEqual(translator.timeout, 5.0)

    def test_request_error_raises_runtime_error(self):
        def fake_request(url, headers):
            raise RuntimeError("connection timed out")

        translator = GoogleTranslateTranslator(
            source="en", target="de", request_func=fake_request,
        )

        with self.assertRaises(RuntimeError) as ctx:
            translator.translate("Knife")
        self.assertIn("connection timed out", str(ctx.exception))

    def test_unexpected_response_raises_runtime_error(self):
        translator = GoogleTranslateTranslator(
            source="en", target="de",
            request_func=lambda url, headers: {"error": "bad"},
        )

        with self.assertRaises(RuntimeError):
            translator.translate("Knife")

    def test_user_agent_header_is_set(self):
        captured = {}

        def fake_request(url, headers):
            captured.update(headers)
            return _google_response(("刀", "Knife"))

        translator = GoogleTranslateTranslator(
            source="en", target="zh-CN", request_func=fake_request,
        )
        translator.translate("Knife")

        self.assertIn("User-Agent", captured)
        self.assertIn("Mozilla", captured["User-Agent"])


class GoogleProviderIntegrationTests(unittest.TestCase):
    def test_create_provider_returns_google_translator(self):
        service = TranslationService()
        provider = service.create_provider("en", "zh-CN", TranslatorConfig(provider="google"))
        self.assertIsInstance(provider, GoogleTranslateTranslator)

    def test_create_provider_passes_base_url_and_timeout(self):
        service = TranslationService()
        config = TranslatorConfig(provider="google", base_url="https://mirror.test", timeout=8.0)
        provider = service.create_provider("en", "zh-CN", config)
        self.assertIsInstance(provider, GoogleTranslateTranslator)
        self.assertIn("mirror.test", provider.base_url)
        self.assertEqual(provider.timeout, 8.0)

    def test_service_translate_jobs_uses_google_translator(self):
        calls = []

        class FakeGoogle:
            def __init__(self, source, target, base_url, timeout, should_cancel=None):
                calls.append((source, target, base_url, timeout))

            def translate_batch(self, texts):
                return [f"zh:{text}" for text in texts]

        service = TranslationService()
        service.google_translator_class = FakeGoogle
        config = TranslatorConfig(provider="google", base_url="https://mirror.test", timeout=7.0)
        jobs = [TranslationJob(0, 3, "Knife", "en", "zh-CN")]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(calls[0], ("en", "zh-CN", "https://mirror.test", 7.0))
        self.assertEqual(results.cell_results[(0, 3)], "zh:Knife")
        self.assertEqual(results.translated, 1)


if __name__ == "__main__":
    unittest.main()
