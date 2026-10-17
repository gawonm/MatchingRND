import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import BaseModel

from app.common.llm_config import DEFAULT_LLM_MODEL
from app.gap_analysis import OpenAIStructuredLLM


class Result(BaseModel):
    answer: str


class SharedLLMRequestTests(unittest.TestCase):
    def client(self):
        parse = Mock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=Result(answer="ok")))],
            usage=None,
        ))
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))), parse

    def test_default_request_omits_temperature_for_luna(self):
        client, parse = self.client()
        result = OpenAIStructuredLLM(client=client)([{"role": "user", "content": "test"}], Result)
        self.assertEqual(result.answer, "ok")
        self.assertEqual(parse.call_args.kwargs["model"], DEFAULT_LLM_MODEL)
        self.assertNotIn("temperature", parse.call_args.kwargs)

    def test_explicit_temperature_is_preserved_for_custom_models(self):
        client, parse = self.client()
        OpenAIStructuredLLM(model="custom-model", temperature=0, client=client)([], Result)
        self.assertEqual(parse.call_args.kwargs["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
