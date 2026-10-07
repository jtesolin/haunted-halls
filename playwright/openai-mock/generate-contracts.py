"""Run with the engine's Python environment and its source on PYTHONPATH."""

import json
import os
import tempfile
from pathlib import Path

from openai.lib._parsing._responses import type_to_text_format_param


def generate():
    # Director imports runtime settings; never load an operator's .env.
    original_directory = Path.cwd()
    os.environ["OPENAI_API_KEY"] = "e2e-only-fake-openai-key-not-a-secret"
    with tempfile.TemporaryDirectory(prefix="e2e-schema-") as directory:
        os.chdir(directory)
        try:
            from app.agents.director import DirectorProposalResponse
            from app.schemas.chat import ActionParserOutput
            from app.schemas.starter_ability_provider import StarterAbilityProviderGeneration

            models = (StarterAbilityProviderGeneration, ActionParserOutput, DirectorProposalResponse)
            return {
                model.__name__: type_to_text_format_param(model)["schema"]
                for model in models
            }
        finally:
            os.chdir(original_directory)


if __name__ == "__main__":
    Path(__file__).with_name("structured-contracts.json").write_text(
        json.dumps(generate(), indent=2) + "\n"
    )
