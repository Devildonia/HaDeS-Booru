"""
Verified Offline Sample Posts and Technical Metadata Card Generator for HaDeS Booru.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from hades_booru.models import CategorizedTags, Post


def _load_scaled_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Loads a legible scaled font using Pillow 10+ load_default(size=...)."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_placeholder_image(title: str, subtitle: str, color_hex: str = "#3b82f6") -> Image.Image:
    """Creates a crisp 960x960 RGB technical card in memory with legible scaled typography (C13a)."""
    img = Image.new("RGB", (960, 960), color="#0f172a")
    draw = ImageDraw.Draw(img)
    title_font = _load_scaled_font(28)
    sub_font = _load_scaled_font(20)
    footer_font = _load_scaled_font(18)

    draw.rectangle([24, 24, 936, 936], outline=color_hex, width=3)
    draw.rectangle([48, 48, 912, 160], fill="#1e293b")
    draw.text((72, 86), title[:44], fill="#f8fafc", font=title_font)
    draw.text((72, 210), subtitle[:64], fill="#94a3b8", font=sub_font)
    draw.text((72, 880), "HaDeS Booru - Metadata Card", fill="#64748b", font=footer_font)
    return img


DEMO_POSTS: list[Post] = [
    Post(
        id="8492011",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/8492011",
        preview_url="",
        medium_url="",
        sample_url="",
        file_url="",
        width=2400,
        height=3200,
        rating="g",
        score=428,
        created_at="2026-10-15",
        tags=CategorizedTags(
            copyright=["vocaloid", "project_sekai"],
            character=["hatsune_miku"],
            artist=["ask_(askzy)"],
            general=[
                "1girl",
                "solo",
                "twintails",
                "aqua_hair",
                "aqua_eyes",
                "long_hair",
                "headset",
                "looking_at_viewer",
                "smile",
                "^_^",
                "cyberpunk",
                "neon_lights",
                "glowing_particles",
                "sleeveless_shirt",
                "detached_sleeves",
                "necktie",
                "masterpiece",
            ],
            meta=["highres", "absurdres", "translated", "commentary_request"],
        ),
        raw_tags=[
            "vocaloid",
            "project_sekai",
            "hatsune_miku",
            "ask_(askzy)",
            "1girl",
            "solo",
            "twintails",
            "aqua_hair",
            "aqua_eyes",
            "^_^",
            "highres",
            "translated",
        ],
        title="Hatsune Miku - Neon Horizon",
        author="ask_(askzy)",
    ),
    Post(
        id="8492055",
        source_id="danbooru",
        source_name="Danbooru",
        source_url="https://danbooru.donmai.us/posts/8492055",
        preview_url="",
        medium_url="",
        sample_url="",
        file_url="",
        width=1920,
        height=1080,
        rating="g",
        score=315,
        created_at="2026-10-16",
        tags=CategorizedTags(
            copyright=["Sousou_no_Frieren"],
            character=["frieren", "fern_(sousou_no_frieren)"],
            artist=["dino_(dinoartforame)"],
            general=[
                "2girls",
                "elf",
                "pointy_ears",
                "white_hair",
                "twintails",
                "purple_hair",
                "magic_staff",
                "starry_sky",
                "aurora",
                "camping",
                "lantern",
                "(o_o)",
                "scenery",
                "night",
            ],
            meta=["highres", "wallpaper", "bad_id"],
        ),
        raw_tags=[
            "Sousou_no_Frieren",
            "frieren",
            "fern_(sousou_no_frieren)",
            "dino_(dinoartforame)",
            "2girls",
            "elf",
            "(o_o)",
            "scenery",
            "highres",
            "bad_id",
        ],
        title="Frieren & Fern Under the Stars",
        author="dino_(dinoartforame)",
    ),
]
