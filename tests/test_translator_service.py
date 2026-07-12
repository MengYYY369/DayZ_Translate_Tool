import json
import threading
import time
import unittest

from translator_service import OpenAICompatibleTranslator, TranslationJob, TranslationService, TranslatorConfig, validate_translator_config


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

        service = TranslationService(provider_factory=factory, batch_size=2)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Knife", "en", "de"),
            TranslationJob(2, 3, "Gun", "en", "de"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(created, [("en", "de")])
        self.assertEqual(fake.calls, [["Knife", "Gun"]])
        self.assertEqual(results.translated, 3)
        self.assertEqual(results.failed, 0)
        self.assertEqual(results.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(1, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(2, 3)], "translated:Gun")

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
            def __init__(self, source, target, api_key, model, base_url, glossary):
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
            def __init__(self, source, target, api_key, model, base_url, glossary):
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


if __name__ == "__main__":
    unittest.main()
