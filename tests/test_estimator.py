import json
import os
import tempfile
import unittest

from estimator import estimate_build, load_project_brief


class TestProjectBriefIntake(unittest.TestCase):
    def test_loads_exactly_one_input_source(self):
        brief = load_project_brief(idea="Build a small issue tracker")
        self.assertEqual(brief.source_kind, "idea")
        self.assertEqual(brief.text, "Build a small issue tracker")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "PRD.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# Product\n\nUsers can create and assign issues.\n")
            brief = load_project_brief(prd_path=path)
            self.assertEqual(brief.source_kind, "prd")
            self.assertIn("assign issues", brief.text)

    def test_rejects_empty_or_ambiguous_input(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            load_project_brief()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            load_project_brief(idea="one", spec_path="two.md")
        with self.assertRaisesRegex(ValueError, "empty"):
            load_project_brief(idea="   ")


class TestBuildEstimator(unittest.TestCase):
    def test_estimate_is_deterministic_ordered_and_json_serializable(self):
        brief = load_project_brief(
            idea=(
                "Build a production SaaS dashboard with React, a PostgreSQL API, "
                "OAuth login, billing webhooks, CI deployment, and end-to-end tests."
            )
        )
        first = estimate_build(
            brief,
            model="example-model",
            input_price_per_million=1.0,
            output_price_per_million=2.0,
            concurrency=2,
        )
        second = estimate_build(
            brief,
            model="example-model",
            input_price_per_million=1.0,
            output_price_per_million=2.0,
            concurrency=2,
        )

        self.assertEqual(first, second)
        json.dumps(first)
        for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "elapsed_minutes"):
            values = first["ranges"][key]
            self.assertLessEqual(values["low"], values["likely"])
            self.assertLessEqual(values["likely"], values["high"])

        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["model"], "example-model")
        self.assertEqual(first["currency"], "USD")
        self.assertIn("coefficients", first["assumptions"])
        self.assertIn("detected_capabilities", first["scope"])
        self.assertIn("backend", first["scope"]["detected_capabilities"])

    def test_larger_scope_estimates_more_work_than_small_idea(self):
        small = estimate_build(load_project_brief(idea="Build a static personal homepage"))
        large = estimate_build(
            load_project_brief(
                idea=(
                    "Build an enterprise multi-tenant commerce platform with React, mobile apps, "
                    "PostgreSQL, OAuth and RBAC, payments, realtime notifications, analytics, "
                    "third-party integrations, Docker deployment, CI/CD, and E2E security tests."
                )
            )
        )

        self.assertGreater(large["scope"]["work_units"], small["scope"]["work_units"])
        self.assertGreater(
            large["ranges"]["total_tokens"]["likely"],
            small["ranges"]["total_tokens"]["likely"],
        )

    def test_common_prd_variants_are_counted_as_scope_signals(self):
        estimate = estimate_build(
            load_project_brief(
                idea=(
                    "Build an issue tracker with user authentication and authorization, "
                    "a PostgreSQL data store, continuous integration, integration testing, "
                    "and production deployment."
                )
            )
        )
        detected = estimate["scope"]["detected_capabilities"]
        for capability in ("authentication", "database", "testing", "deployment"):
            self.assertIn(capability, detected)
        self.assertIn("confidence_reasons", estimate)

    def test_cost_uses_separate_input_and_output_pricing(self):
        estimate = estimate_build(
            load_project_brief(idea="Build a tested command-line calculator"),
            input_price_per_million=2.0,
            output_price_per_million=8.0,
        )
        likely_input = estimate["ranges"]["input_tokens"]["likely"]
        likely_output = estimate["ranges"]["output_tokens"]["likely"]
        expected = round((likely_input * 2.0 + likely_output * 8.0) / 1_000_000, 4)
        self.assertEqual(estimate["ranges"]["cost_usd"]["likely"], expected)

    def test_rejects_invalid_pricing_and_concurrency(self):
        brief = load_project_brief(idea="Build a CLI")
        with self.assertRaisesRegex(ValueError, "pricing"):
            estimate_build(brief, input_price_per_million=-1)
        with self.assertRaisesRegex(ValueError, "pricing"):
            estimate_build(brief, output_price_per_million=float("nan"))
        with self.assertRaisesRegex(ValueError, "concurrency"):
            estimate_build(brief, concurrency=0)


if __name__ == "__main__":
    unittest.main()
