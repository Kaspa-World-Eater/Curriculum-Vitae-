"""Midjourney prompt templates for every input the pipeline needs.

The description is written once and reused in every prompt: that repetition is
what keeps the character the same across the sheet, the single views and the
direct sprites.
"""

from __future__ import annotations

from dataclasses import dataclass

EXAMPLE_DESCRIPTION = (
    "a gaunt hooded wanderer with a faceless black void under a teal-blue tattered "
    "hooded cloak, gold beads and a gold shoulder ornament, dark leather armor, holding "
    "an ornate gold lantern with a glowing cyan flame in one hand, curled-toe boots"
)

DESCRIPTION_TIPS = (
    "One sentence. Cover the silhouette, the materials, the main colors, and 3-5 "
    "signature details. Use the exact same sentence in every prompt."
)


@dataclass(frozen=True)
class PromptKind:
    key: str
    title: str
    purpose: str
    template: str
    needs_reference: bool = False


PROMPT_KINDS: list[PromptKind] = [
    PromptKind(
        "sheet",
        "A. Character sheet (required for the 3D pipeline)",
        "One image with front, side and back views. All views in one image keeps them "
        "consistent. Upscale it and save the largest PNG, uncropped.",
        "character turnaround reference sheet of {description}, three views side by side: "
        "front view, side view, back view, standing in A-pose with arms slightly away from "
        "the body, feet shoulder-width apart, full body head to toe, same character in every "
        "view, orthographic, flat even lighting, no cast shadows, plain solid white "
        "background, detailed dark fantasy digital painting, muted desaturated colors, "
        "gritty painterly texture --ar 3:2 --style raw --no text, labels, perspective, "
        "scenery, extra characters, cropping",
    ),
    PromptKind(
        "sheet4",
        "A2. Four-view sheet (best 3D model: adds the three-quarter view)",
        "Like A, plus a three-quarter view. The extra outline makes the diagonal "
        "directions (the ones Diablo uses most) carve and paint correctly.",
        "character turnaround reference sheet of {description}, four views side by side: "
        "front view, three-quarter view, side view, back view, standing in A-pose with arms "
        "slightly away from the body, feet shoulder-width apart, full body head to toe, same "
        "character in every view, orthographic, flat even lighting, no cast shadows, plain "
        "solid white background, detailed dark fantasy digital painting, muted desaturated "
        "colors, gritty painterly texture --ar 2:1 --style raw --no text, labels, perspective, "
        "scenery, extra characters, cropping",
    ),
    PromptKind(
        "front",
        "B1. Front view, high-res (optional, nicer texture)",
        "Uses the sheet as a character reference. On Midjourney V7 replace --cref/--cw "
        "with --oref/--ow.",
        "{description}, front view only, standing in A-pose, full body head to toe, "
        "orthographic, flat even lighting, no cast shadows, plain solid white background, "
        "detailed dark fantasy digital painting --ar 2:3 --style raw --cref {reference} "
        "--cw 100 --no text, scenery, perspective",
        needs_reference=True,
    ),
    PromptKind(
        "back",
        "B2. Back view, high-res (optional, nicer texture)",
        "Same as B1 for the back of the character.",
        "{description}, back view only, seen from behind, standing in A-pose, full body "
        "head to toe, orthographic, flat even lighting, no cast shadows, plain solid white "
        "background, detailed dark fantasy digital painting --ar 2:3 --style raw --cref "
        "{reference} --cw 100 --no text, scenery, perspective, face",
        needs_reference=True,
    ),
    PromptKind(
        "sprite",
        "C. Direct pixel sprite (no 3D: bosses, portraits, items, single poses)",
        "Also used by the app to lock the color palette of the rendered frames.",
        "dark fantasy pixel art of {description}, full body, single character centered, "
        "standing, facing slightly to the left, pure black background, high detail, limited "
        "color palette, moody, Dark Souls inspired --ar 3:4 --style raw --no text, "
        "watermark, frame, border, scenery",
    ),
    PromptKind(
        "item",
        "D. Item / pickup sprite",
        "For weapons, potions, loot. Spin them with the rotate tool afterwards.",
        "dark fantasy pixel art of {description}, single object centered, isometric "
        "three-quarter view, pure black background, high detail, limited color palette "
        "--ar 1:1 --style raw --no text, watermark, frame, border, scenery, hands, character",
    ),
]

RULES = [
    "Flat lighting and a white background are not optional for A and B: dramatic light "
    "gets baked into the model's skin and looks wrong from other angles; white makes the "
    "cutout clean.",
    "Do not put 'pixel art' in A or B. The app adds the pixels later; asking for them "
    "here only adds noise to the texture.",
    "Upscale before saving (the U buttons) and save PNG, never a cropped screenshot.",
    "Keep the description sentence identical in every prompt.",
]


def build_prompt(kind: str, description: str, reference: str = "[SHEET IMAGE URL]") -> str:
    for k in PROMPT_KINDS:
        if k.key == kind:
            return k.template.format(description=description.strip() or "[CHARACTER DESCRIPTION]", reference=reference)
    raise ValueError(f"unknown prompt kind {kind!r}; choose from {[k.key for k in PROMPT_KINDS]}")


def build_all(description: str, reference: str = "[SHEET IMAGE URL]") -> dict[str, str]:
    return {k.key: build_prompt(k.key, description, reference) for k in PROMPT_KINDS}
