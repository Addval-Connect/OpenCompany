# Translate (`translateText`)

| Field | Value |
|------|-------|
| **Category** | language |
| **Backend handler** | [`server/nodes/translate/translate_text.py`](../../../server/nodes/translate/translate_text.py) |
| **Shared helpers** | [`_base.py`](../../../server/nodes/translate/_base.py), [`_unifier.py`](../../../server/nodes/translate/_unifier.py), [`_providers/`](../../../server/nodes/translate/_providers/) |
| **Capabilities config** | [`server/config/translate_defaults.json`](../../../server/config/translate_defaults.json) |
| **Tests** | [`server/tests/nodes/test_translate.py`](../../../server/tests/nodes/test_translate.py) |
| **Skill (if any)** | [`server/skills/language_agent/translation-skill/SKILL.md`](../../../server/skills/language_agent/translation-skill/SKILL.md) |
| **Dual-purpose tool** | yes - tool name `translate_text` |

## Purpose

Translate text through any configured provider. Replaces the vendor-locked
`sarvamTranslate`: the provider is a parameter, so switching from Sarvam to
DeepL never means swapping the node out of a workflow.

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
| `tool_name` | string | `translate_text` | Optional. Override name shown to the LLM when used as a tool |
| `tool_description` | string | `"Translate text into another language. Use when the user asks for a translation, or when text must be understood in a different language before further processing."` | Optional. Override description shown to the LLM when used as a tool (`rows: 3`) |
| `provider` | enum | registry-driven | `translate_providers()` — `deepl` / `sarvam` / `openai` |
| `text` | string | - | Text to translate (required) |
| `target_language` | string | provider default | Loader `translateLanguages` |
| `source_language` | string | auto-detect | Loader `translateSourceLanguages` |
| `translate_model` | string | provider default | **Not** `model` — see below |
| `formality` | string | - | Register; DeepL formality options / Sarvam modes, unified |
| `context` | string | - | Disambiguating context, not itself translated |
| `preserve_formatting` | boolean | false | Keep line breaks and punctuation |
| `provider_options` | object | `{}` | Vendor-specific, passed through untouched |

## Outputs (handles)

| Handle | Shape | Description |
|--------|-------|-------------|
| `output-main` | object | `TranslateTextOutput` payload (fields below); visible because `hide_output_handle = False` |
| `output-tool` | - | Auto-appended for `usable_as_tool` |

## Outputs

`translated_text`, `detected_source_language`, `provider`, `translate_model`,
`request_id`.

## Edge cases

- **DeepL free vs pro hosts.** A free key ends `:fx` and the pro host rejects
  it with an unhelpful 403. The provider selects the host from the key, so a
  user never has to know which tier they hold.
- **DeepL reports `billed_characters`**, and the node bills that rather than
  counting input — it matches the invoice.
- **Sarvam per-model caps** (`mayura:v1` 1000 chars, `sarvam-translate:v1`
  2000) are enforced before the call, so the LLM gets an actionable message
  instead of an opaque 422.
- **LLM-backed provider records no cost**: it bills tokens, already costed by
  the LLM layer.

## Related

- **Peer nodes**: the other two nodes in [`nodes/translate/`](../../../server/nodes/translate/).
- **Pattern**: [Speech Provider RFC §8](../../speech_provider_rfc.md#8-the-pattern-generalised-nodestranslate)
