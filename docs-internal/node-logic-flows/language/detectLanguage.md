# Detect Language (`detectLanguage`)

| Field | Value |
|------|-------|
| **Category** | language |
| **Backend handler** | [`server/nodes/translate/detect_language.py`](../../../server/nodes/translate/detect_language.py) |
| **Shared helpers** | [`_base.py`](../../../server/nodes/translate/_base.py), [`_unifier.py`](../../../server/nodes/translate/_unifier.py), [`_providers/`](../../../server/nodes/translate/_providers/) |
| **Capabilities config** | [`server/config/translate_defaults.json`](../../../server/config/translate_defaults.json) |
| **Tests** | [`server/tests/nodes/test_translate.py`](../../../server/tests/nodes/test_translate.py) |
| **Skill (if any)** | [`server/skills/language_agent/translation-skill/SKILL.md`](../../../server/skills/language_agent/translation-skill/SKILL.md) |
| **Dual-purpose tool** | yes - tool name `detect_language` |

## Purpose

Identify which language a piece of text is written in, and in which script.
Replaces `sarvamDetectLanguage`.

## Inputs (handles)

| Handle | Connection type | Required | Purpose |
|--------|-----------------|----------|---------|
| `input-main` | main | no | Upstream data injected into params |

Handles are declared visible explicitly (`hide_input_handle = False` /
`hide_output_handle = False`) because `usable_as_tool = True` otherwise
auto-hides both.

## Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `tool_name` | string | `detect_language` | Optional. Override name shown to the LLM when used as a tool |
| `tool_description` | string | `"Identify which language a piece of text is written in, and in which script. Use before translating when the source language is unknown, or to route text by language."` | Optional. Override description shown to the LLM when used as a tool (`rows: 3`) |
| `provider` | enum | registry-driven | `detect_providers()` — `sarvam` / `openai` |
| `text` | string | - | Text to identify (required) |
| `detect_model` | string | provider default | Loader `detectModels` |
| `provider_options` | object | `{}` | Vendor-specific |

## Outputs (handles)

| Handle | Shape | Description |
|--------|-------|-------------|
| `output-main` | object | `DetectLanguageOutput` payload (fields below); visible because `hide_output_handle = False` |
| `output-tool` | - | Auto-appended for `usable_as_tool` |

## Outputs

`language`, `script`, `confidence` (from providers that report it),
`provider`, `request_id`.

## Edge cases

- **Confidence is `None` when the provider does not report one** — never
  fabricated. Sarvam returns a language and script but no score.
- Detection on a single word is unreliable regardless of provider; the skill
  says to give it a sentence.

## Related

- **Peer nodes**: the other two nodes in [`nodes/translate/`](../../../server/nodes/translate/).
- **Pattern**: [Speech Provider RFC §8](../../speech_provider_rfc.md#8-the-pattern-generalised-nodestranslate)
