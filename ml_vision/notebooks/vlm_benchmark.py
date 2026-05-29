"""
Phase 2 Experiment A — VLM Benchmark
Tests frontier VLMs (Google, OpenAI, Anthropic) on Phase 0 golden data.
Measures CER zero-shot and 5-shot for each model.
"""
import base64
import os
import time
from pathlib import Path

import anthropic
from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from jiwer import cer
from openai import OpenAI

load_dotenv()

GOLDEN_DIR = Path("data/golden/page_0001")
REPORTS_DIR = Path("reports")

SYSTEM_PROMPT = (
    "You are an expert paleographer specializing in Classical Armenian (Grabar) manuscripts. "
    "The image shows a single line of text written in Bolorgir script — a printed calligraphic "
    "style used in Armenian liturgical books from the 17th–19th centuries.\n\n"
    "Transcribe the text exactly as written, using Armenian Unicode characters (U+0531–U+058F). "
    "Output ONLY the Armenian text. Do not transliterate. Do not expand abbreviations. "
    "Use ՚ (U+055A) for elision marks if visible. Use ։ (U+0589) for full stops."
)


def load_samples() -> list[tuple[Path, str]]:
    return [
        (p.with_suffix(".png"), p.read_text(encoding="utf-8").strip())
        for p in sorted(GOLDEN_DIR.glob("*.txt"))
    ]


def img_to_b64(img_path: Path) -> str:
    return base64.b64encode(img_path.read_bytes()).decode()


# ── Anthropic ──────────────────────────────────────────────────────────────────

def call_anthropic(model: str, img_path: Path, examples: list[tuple[Path, str]] | None) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list = [{"type": "text", "text": SYSTEM_PROMPT}]
    if examples:
        for ex_img, ex_text in examples:
            content += [
                {"type": "text", "text": "Example:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_to_b64(ex_img)}},
                {"type": "text", "text": ex_text},
            ]
        content.append({"type": "text", "text": "Now transcribe this line:"})
    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_to_b64(img_path)}})
    resp = client.messages.create(model=model, max_tokens=100, messages=[{"role": "user", "content": content}])
    return resp.content[0].text.strip()


# ── OpenAI ─────────────────────────────────────────────────────────────────────

def call_openai(model: str, img_path: Path, examples: list[tuple[Path, str]] | None) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    user_content: list = []
    if examples:
        for ex_img, ex_text in examples:
            user_content += [
                {"type": "text", "text": "Example:"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_to_b64(ex_img)}"}},
                {"type": "text", "text": ex_text},
            ]
        user_content.append({"type": "text", "text": "Now transcribe this line:"})
    user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_to_b64(img_path)}"}})
    resp = client.chat.completions.create(
        model=model, max_completion_tokens=100,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}],
    )
    return resp.choices[0].message.content.strip()


# ── Gemini ─────────────────────────────────────────────────────────────────────

def img_to_part(img_path: Path) -> genai_types.Part:
    return genai_types.Part.from_bytes(data=img_path.read_bytes(), mime_type="image/png")


def call_gemini(model: str, img_path: Path, examples: list[tuple[Path, str]] | None) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    parts: list = [SYSTEM_PROMPT]
    if examples:
        for ex_img, ex_text in examples:
            parts += ["Example:", img_to_part(ex_img), ex_text]
        parts.append("Now transcribe this line:")
    parts.append(img_to_part(img_path))
    resp = client.models.generate_content(model=model, contents=parts)
    return resp.text.strip()


# ── Runner ─────────────────────────────────────────────────────────────────────

MODELS = [
    ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "claude-haiku-4-5"),
    ("openai",    "gpt-5.4"),
    ("openai",    "gpt-5.4-mini"),
    ("gemini",    "gemini-2.5-pro"),
    ("gemini",    "gemini-3.1-flash"),
]

CALL_FN = {"anthropic": call_anthropic, "openai": call_openai, "gemini": call_gemini}


def run_variant(
    provider: str,
    model: str,
    eval_samples: list[tuple[Path, str]],
    few_shot_examples: list[tuple[Path, str]] | None,
    label: str,
) -> tuple[float, list[str], list[str]]:
    fn = CALL_FN[provider]
    predictions, references, empty_results = [], [], []

    for img_path, gt in eval_samples:
        pred = ""
        for attempt in range(3):
            try:
                pred = fn(model, img_path, few_shot_examples)
                break
            except Exception as e:
                msg = str(e)
                if attempt < 2 and any(code in msg for code in ("503", "429", "UNAVAILABLE", "rate")):
                    wait = (attempt + 1) * 10
                    print(f"  RETRY {img_path.name} in {wait}s ({msg[:80]})")
                    time.sleep(wait)
                else:
                    print(f"  ERROR {img_path.name}: {msg[:120]}")
                    break

        if gt:
            predictions.append(pred)
            references.append(gt)
            print(f"  {img_path.name}: '{pred}' | GT: '{gt}'")
        else:
            status = "correctly empty" if not pred else f"hallucinated: '{pred}'"
            empty_results.append(f"  {img_path.name}: {status}")

        time.sleep(0.3)

    model_cer = cer(references, predictions) if references else 1.0
    print(f"\n  [{label}] CER: {model_cer:.4f} ({model_cer*100:.1f}%), lines evaluated: {len(references)}")
    if empty_results:
        print("  Section markers:")
        for r in empty_results:
            print(r)
    return model_cer, predictions, references


def main() -> None:
    samples = load_samples()
    few_shot_examples = [(p, t) for p, t in samples[:5] if t]  # first 5 non-empty lines
    eval_5shot = samples[5:]                                     # lines 6–36 for 5-shot eval

    results: dict[str, dict] = {}

    for provider, model in MODELS:
        print(f"\n{'='*64}")
        print(f"  {model}")
        print(f"{'='*64}")

        print("\n--- Zero-shot ---")
        try:
            zs_cer, _, _ = run_variant(provider, model, samples, None, f"{model} zero-shot")
        except Exception as e:
            print(f"  SKIPPING {model}: {e}")
            results[model] = {"zero_shot": None, "five_shot": None}
            continue

        print("\n--- 5-shot ---")
        try:
            fs_cer, _, _ = run_variant(provider, model, eval_5shot, few_shot_examples, f"{model} 5-shot")
        except Exception as e:
            print(f"  5-shot FAILED for {model}: {e}")
            fs_cer = None

        results[model] = {"zero_shot": zs_cer, "five_shot": fs_cer}

    # Summary
    print(f"\n{'='*64}")
    print("SUMMARY")
    print(f"{'='*64}")
    print(f"{'Model':<30} {'Zero-shot':>12} {'5-shot':>10}")
    print("-" * 54)
    for model, r in results.items():
        zs = f"{r['zero_shot']*100:.1f}%" if r["zero_shot"] is not None else "FAILED"
        fs = f"{r['five_shot']*100:.1f}%" if r["five_shot"] is not None else "FAILED"
        print(f"{model:<30} {zs:>12} {fs:>10}")
    print(f"\nBaseline (trocr-base-printed, no fine-tuning): 93.4%")

    # Save report
    REPORTS_DIR.mkdir(exist_ok=True)
    report = REPORTS_DIR / "phase_2_vlm_results.md"
    lines = [
        "# Phase 2 — VLM Benchmark Results\n\n",
        "**Date:** 2026-04-14\n",
        "**Baseline (trocr-base-printed):** 93.4% CER\n\n",
        "## CER Summary\n\n",
        "| Model | Zero-shot CER | 5-shot CER |\n",
        "|-------|:------------:|:----------:|\n",
    ]
    for model, r in results.items():
        zs = f"{r['zero_shot']*100:.1f}%" if r["zero_shot"] is not None else "FAILED"
        fs = f"{r['five_shot']*100:.1f}%" if r["five_shot"] is not None else "FAILED"
        lines.append(f"| `{model}` | {zs} | {fs} |\n")
    report.write_text("".join(lines), encoding="utf-8")
    print(f"\nReport saved to {report}")


if __name__ == "__main__":
    main()
