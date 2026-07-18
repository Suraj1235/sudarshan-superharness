import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from providers import (
    AnthropicProvider,
    CommandProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderError,
)


class _ProviderHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        type(self).requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": json.loads(body),
            }
        )
        status, headers, payload = type(self).responses.pop(0)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        return


class TestOpenAICompatibleProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _ProviderHandler.responses = []
        _ProviderHandler.requests = []

    def test_sends_chat_request_and_normalizes_usage(self):
        _ProviderHandler.responses.append(
            (
                200,
                {},
                {
                    "choices": [{"message": {"content": '{"action":"finish"}'}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
                },
            )
        )
        provider = OpenAICompatibleProvider(
            api_key="secret-value",
            base_url=self.base_url,
            model="test-model",
            timeout_seconds=2,
        )

        response = provider.complete([{"role": "user", "content": "hello"}])

        self.assertEqual(response.text, '{"action":"finish"}')
        self.assertEqual(response.input_tokens, 120)
        self.assertEqual(response.output_tokens, 30)
        request = _ProviderHandler.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["body"]["model"], "test-model")
        self.assertEqual(request["body"]["messages"][0]["content"], "hello")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-value")
        self.assertNotIn("secret-value", repr(provider))

    def test_rate_limit_is_retryable_and_honors_retry_after(self):
        _ProviderHandler.responses.append(
            (429, {"Retry-After": "7"}, {"error": {"message": "slow down secret-value"}})
        )
        provider = OpenAICompatibleProvider(
            api_key="secret-value", base_url=self.base_url, model="test-model"
        )

        with self.assertRaises(ProviderError) as raised:
            provider.complete([{"role": "user", "content": "hello"}])

        error = raised.exception
        self.assertTrue(error.retryable)
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.retry_after_seconds, 7.0)
        self.assertNotIn("secret-value", str(error))

    def test_authentication_failure_is_permanent(self):
        _ProviderHandler.responses.append((401, {}, {"error": {"message": "bad key"}}))
        provider = OpenAICompatibleProvider(
            api_key="bad-key", base_url=self.base_url, model="test-model"
        )

        with self.assertRaises(ProviderError) as raised:
            provider.complete([{"role": "user", "content": "hello"}])

        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.status_code, 401)

    def test_malformed_success_response_fails_without_retry(self):
        _ProviderHandler.responses.append((200, {}, {"choices": []}))
        provider = OpenAICompatibleProvider(
            api_key="key", base_url=self.base_url, model="test-model"
        )

        with self.assertRaises(ProviderError) as raised:
            provider.complete([{"role": "user", "content": "hello"}])

        self.assertFalse(raised.exception.retryable)
        self.assertIn("malformed", str(raised.exception).lower())

    def test_response_body_is_bounded(self):
        _ProviderHandler.responses.append((200, {}, b"{" + (b"x" * 500) + b"}"))
        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url=self.base_url,
            model="test-model",
            max_response_bytes=100,
        )

        with self.assertRaisesRegex(ProviderError, "size limit"):
            provider.complete([{"role": "user", "content": "hello"}])

    def test_plain_http_is_limited_to_local_endpoints(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            OpenAICompatibleProvider(
                api_key="key", base_url="http://example.com/v1", model="test-model"
            )

    def test_provider_base_url_rejects_missing_hosts_queries_and_fragments(self):
        for base_url in (
            "https:///v1",
            "https://example.com/v1?token=value",
            "https://example.com/v1#fragment",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                OpenAICompatibleProvider(
                    api_key="key", base_url=base_url, model="test-model"
                )

    def test_provider_timeouts_must_be_finite(self):
        factories = (
            lambda: OpenAICompatibleProvider(
                api_key="key",
                base_url="https://example.com/v1",
                model="test-model",
                timeout_seconds=float("nan"),
            ),
            lambda: AnthropicProvider(
                api_key="key", model="test-model", timeout_seconds=float("inf")
            ),
            lambda: GeminiProvider(
                api_key="key", model="test-model", timeout_seconds=float("nan")
            ),
            lambda: CommandProvider(
                command=[sys.executable, "-V"],
                model="test-model",
                timeout_seconds=float("inf"),
            ),
        )
        for factory in factories:
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()


class TestCommandProvider(unittest.TestCase):
    def test_non_finite_retry_delay_is_discarded(self):
        error = ProviderError("bad delay", retryable=True, retry_after_seconds=float("inf"))
        self.assertIsNone(error.retry_after_seconds)

    def test_bridge_response_is_rejected_at_the_streaming_size_limit(self):
        provider = CommandProvider(
            command=[sys.executable, "-c", "print('x' * 10000)"],
            model="framework-model",
            timeout_seconds=2,
            max_response_chars=100,
        )
        with self.assertRaisesRegex(ProviderError, "size limit"):
            provider.complete([{"role": "user", "content": "hello"}])

    def test_normalizes_framework_bridge_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = os.path.join(temp_dir, "bridge.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json, sys\n"
                    "request = json.load(sys.stdin)\n"
                    "print(json.dumps({'text': json.dumps({'action': 'finish', 'summary': request['model']}), "
                    "'input_tokens': 12, 'output_tokens': 4}))\n"
                )
            provider = CommandProvider(
                command=[sys.executable, script], model="framework-model", timeout_seconds=2
            )

            response = provider.complete([{"role": "user", "content": "hello"}])

            self.assertIn("framework-model", response.text)
            self.assertEqual(response.input_tokens, 12)
            self.assertEqual(response.output_tokens, 4)
            self.assertEqual(response.provider, "command-bridge")

    def test_bridge_can_report_retryable_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = os.path.join(temp_dir, "bridge.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "import json, sys\n"
                    "print(json.dumps({'error': 'framework busy', 'retryable': True, "
                    "'status_code': 429, 'retry_after_seconds': 2}), file=sys.stderr)\n"
                    "raise SystemExit(75)\n"
                )
            provider = CommandProvider(
                command=[sys.executable, script], model="framework-model", timeout_seconds=2
            )

            with self.assertRaises(ProviderError) as raised:
                provider.complete([{"role": "user", "content": "hello"}])

            self.assertTrue(raised.exception.retryable)
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.retry_after_seconds, 2.0)


class TestNativeProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _ProviderHandler.responses = []
        _ProviderHandler.requests = []

    def test_anthropic_messages_contract_and_usage(self):
        _ProviderHandler.responses.append(
            (
                200,
                {},
                {
                    "content": [{"type": "text", "text": '{"action":"list_files"}'}],
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 10,
                        "cache_read_input_tokens": 5,
                        "output_tokens": 25,
                    },
                },
            )
        )
        provider = AnthropicProvider(
            api_key="anthropic-secret",
            base_url=self.origin,
            model="claude-test",
            timeout_seconds=2,
        )

        response = provider.complete(
            [
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "Build it."},
            ],
            max_output_tokens=500,
        )

        request = _ProviderHandler.requests[0]
        headers = {key.lower(): value for key, value in request["headers"].items()}
        self.assertEqual(request["path"], "/v1/messages")
        self.assertEqual(headers["x-api-key"], "anthropic-secret")
        self.assertEqual(request["body"]["system"], "Return JSON.")
        self.assertEqual(request["body"]["messages"], [{"role": "user", "content": "Build it."}])
        self.assertEqual(request["body"]["max_tokens"], 500)
        self.assertEqual(response.input_tokens, 115)
        self.assertEqual(response.output_tokens, 25)
        self.assertNotIn("anthropic-secret", repr(provider))

    def test_gemini_generate_content_contract_and_usage(self):
        _ProviderHandler.responses.append(
            (
                200,
                {},
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": '{"action":"list_files"}'}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 90,
                        "candidatesTokenCount": 20,
                        "thoughtsTokenCount": 7,
                    },
                },
            )
        )
        provider = GeminiProvider(
            api_key="gemini-secret",
            base_url=f"{self.origin}/v1beta",
            model="gemini-test",
            timeout_seconds=2,
        )

        response = provider.complete(
            [
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "Build it."},
            ],
            max_output_tokens=500,
        )

        request = _ProviderHandler.requests[0]
        headers = {key.lower(): value for key, value in request["headers"].items()}
        self.assertEqual(request["path"], "/v1beta/models/gemini-test:generateContent")
        self.assertEqual(headers["x-goog-api-key"], "gemini-secret")
        self.assertEqual(request["body"]["systemInstruction"]["parts"][0]["text"], "Return JSON.")
        self.assertEqual(request["body"]["contents"][0]["role"], "user")
        self.assertEqual(request["body"]["generationConfig"]["maxOutputTokens"], 500)
        self.assertEqual(response.input_tokens, 90)
        self.assertEqual(response.output_tokens, 27)
        self.assertNotIn("gemini-secret", repr(provider))


if __name__ == "__main__":
    unittest.main()
