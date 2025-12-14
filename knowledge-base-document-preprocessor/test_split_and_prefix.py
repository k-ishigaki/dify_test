from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent / "tools" / "knowledge-base-document-preprocessor.py"
SOURCE_PATH = Path("test.md")


def _load_module():
    spec = importlib.util.spec_from_file_location("kb_preprocessor", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _collect_markers(module, lines, source_name: str) -> list[str]:
    output_lines = list(
        module._split_and_prefix(  # type: ignore[attr-defined]
            lines,
            max_chunk_length=10_000,
            split_max_level=3,
            source_name=source_name,
        )
    )
    return [line.strip() for line in output_lines if line.startswith("{ data-path")]


@pytest.fixture(scope="session")
def preprocessor_module():
    return _load_module()


@pytest.fixture(scope="session")
def fixture_markers(preprocessor_module):
    lines = SOURCE_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    return _collect_markers(preprocessor_module, lines, SOURCE_PATH.stem)


def test_split_and_prefix_resets_heading_stack(fixture_markers):
    assert fixture_markers == [
        '{ data-path = "test" > "Intro" }',
        '{ data-path = "test" > "Intro" > "Intro Child" }',
        '{ data-path = "test" > "Intro" > "Intro Child" > "Intro Grandchild" }',
        '{ data-path = "test" > "Intro" > "Intro Sibling" }',
        '{ data-path = "test" > "Middle" }',
        '{ data-path = "test" > "Middle" > "Middle Child" }',
        '{ data-path = "test" > "Middle" > "Middle Child" > "Middle Grandchild" }',
        '{ data-path = "test" > "Outro" }',
        '{ data-path = "test" > "Outro" > "Outro Grandchild" }',
        '{ data-path = "test" > "Outro" > "Outro Child" }',
        '{ data-path = "test" > "Final" }',
        '{ data-path = "test" > "Final" > "Final Child" }',
        '{ data-path = "test" > "Final" > "Final Child" > "Final Grandchild" }',
        '{ data-path = "test" > "Final" > "Final Sibling" }',
        '{ data-path = "test" > "Epilogue" }',
        '{ data-path = "test" > "Epilogue" > "Epilogue Child" }',
        '{ data-path = "test" > "Epilogue" > "Epilogue Child" > "Epilogue Grandchild" }',
    ]


@pytest.mark.parametrize(
    ("anchor", "expected_sequence"),
    [
        (
            '{ data-path = "test" > "Intro" }',
            [
                '{ data-path = "test" > "Intro" }',
                '{ data-path = "test" > "Intro" > "Intro Child" }',
                '{ data-path = "test" > "Intro" > "Intro Child" > "Intro Grandchild" }',
                '{ data-path = "test" > "Intro" > "Intro Sibling" }',
                '{ data-path = "test" > "Middle" }',
            ],
        ),
        (
            '{ data-path = "test" > "Middle" > "Middle Child" }',
            [
                '{ data-path = "test" > "Middle" > "Middle Child" }',
                '{ data-path = "test" > "Middle" > "Middle Child" > "Middle Grandchild" }',
                '{ data-path = "test" > "Outro" }',
            ],
        ),
        (
            '{ data-path = "test" > "Outro" }',
            [
                '{ data-path = "test" > "Outro" }',
                '{ data-path = "test" > "Outro" > "Outro Grandchild" }',
                '{ data-path = "test" > "Outro" > "Outro Child" }',
            ],
        ),
        (
            '{ data-path = "test" > "Final" > "Final Child" > "Final Grandchild" }',
            [
                '{ data-path = "test" > "Final" > "Final Child" > "Final Grandchild" }',
                '{ data-path = "test" > "Final" > "Final Sibling" }',
                '{ data-path = "test" > "Epilogue" }',
            ],
        ),
    ],
    ids=[
        "h1_h2_h3_back_to_h2_then_h1",
        "h2_h3_to_new_h1",
        "h1_to_h3_without_h2_then_h2",
        "h3_to_h2_to_new_h1",
    ],
)
def test_split_and_prefix_heading_sequences(fixture_markers, anchor, expected_sequence):
    start_idx = fixture_markers.index(anchor)
    assert fixture_markers[start_idx : start_idx + len(expected_sequence)] == expected_sequence
