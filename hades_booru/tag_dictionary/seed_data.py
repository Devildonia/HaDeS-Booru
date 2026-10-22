"""
Curated offline seed catalog for the HaDeS Booru Tag Dictionary.
Provides foundational Danbooru tag definitions, categories, post counts, and canonical
aliases so offline lookup and DAPI tag categorization work immediately without network calls.
Spanish definitions are included only where genuinely translated and curated; entries without
a verified Spanish translation set body_es=None (never machine-translated).
"""

from __future__ import annotations

from typing import TypedDict

from hades_booru.models import TagCategory


class SeedTagEntry(TypedDict):
    name: str
    category: TagCategory
    post_count: int
    body_en: str
    body_es: str | None
    aliases: list[str]


SEED_TAG_CATALOG: list[SeedTagEntry] = [
    {
        "name": "1girl",
        "category": "general",
        "post_count": 5420000,
        "body_en": (
            "Images featuring a single female character. Used when exactly one girl or woman "
            "is visible in the scene, regardless of whether male characters or non-human "
            "creatures are also present."
        ),
        "body_es": (
            "Imagenes que presentan un unico personaje femenino. Se utiliza cuando aparece "
            "exactamente una chica o mujer en la escena, independientemente de si hay personajes "
            "masculinos o criaturas no humanas presentes."
        ),
        "aliases": ["1_girl", "one_girl", "single_girl", "female_solo"],
    },
    {
        "name": "2girls",
        "category": "general",
        "post_count": 1480000,
        "body_en": "Images featuring exactly two female characters in the composition.",
        "body_es": "Imagenes en las que aparecen exactamente dos personajes femeninos en la composicion.",
        "aliases": ["2_girls", "two_girls"],
    },
    {
        "name": "multiple_girls",
        "category": "general",
        "post_count": 1350000,
        "body_en": "Used when two or more female characters appear in the same image.",
        "body_es": "Se aplica cuando dos o mas personajes femeninos aparecen en la misma imagen.",
        "aliases": ["many_girls", "girls"],
    },
    {
        "name": "1boy",
        "category": "general",
        "post_count": 1620000,
        "body_en": (
            "Images featuring a single male character. Used when exactly one boy or man "
            "is visible in the scene."
        ),
        "body_es": (
            "Imagenes con un unico personaje masculino. Se emplea cuando hay exactamente un "
            "chico u hombre visible en la escena."
        ),
        "aliases": ["1_boy", "one_boy", "single_boy"],
    },
    {
        "name": "solo",
        "category": "general",
        "post_count": 4650000,
        "body_en": (
            "An image featuring a single character as the sole subject, with no other characters "
            "visible in the foreground or background."
        ),
        "body_es": (
            "Imagen con un unico personaje como sujeto exclusivo, sin otros personajes visibles "
            "en primer plano ni en el fondo."
        ),
        "aliases": ["single_character", "alone_subject"],
    },
    {
        "name": "solo_focus",
        "category": "general",
        "post_count": 320000,
        "body_en": (
            "Used when multiple characters are present in the image, but the composition and camera "
            "clearly focus on a single main character."
        ),
        "body_es": (
            "Se usa cuando hay varios personajes en la imagen, pero el encuadre y la composicion "
            "se centran claramente en un unico protagonista."
        ),
        "aliases": ["main_character_focus"],
    },
    {
        "name": "looking_at_viewer",
        "category": "general",
        "post_count": 3180000,
        "body_en": (
            "A character making direct eye contact with the viewer or virtual camera lens."
        ),
        "body_es": (
            "El personaje dirige la mirada directamente hacia el espectador o el objetivo de la camara."
        ),
        "aliases": ["looking_at_camera", "eye_contact_with_viewer", "staring_at_viewer"],
    },
    {
        "name": "twintails",
        "category": "general",
        "post_count": 890000,
        "body_en": (
            "A hairstyle where the hair is divided into two symmetrical bunches tied on either side "
            "of the head, typically worn medium or long."
        ),
        "body_es": (
            "Peinado en el que el cabello se divide en dos coletas simetricas atadas a ambos lados "
            "de la cabeza, habitualmente de longitud media o larga."
        ),
        "aliases": ["twin_tails", "pigtails_long", "two_tails"],
    },
    {
        "name": "long_hair",
        "category": "general",
        "post_count": 4120000,
        "body_en": "Hair that extends at least past the character's shoulders.",
        "body_es": "Cabello cuya longitud supera al menos la altura de los hombros del personaje.",
        "aliases": ["longhair"],
    },
    {
        "name": "short_hair",
        "category": "general",
        "post_count": 2150000,
        "body_en": "Hair that ends above the shoulders and does not hang down the back.",
        "body_es": "Cabello que termina por encima de los hombros sin caer sobre la espalda.",
        "aliases": ["shorthair"],
    },
    {
        "name": "blue_eyes",
        "category": "general",
        "post_count": 1980000,
        "body_en": "A character with blue irises.",
        "body_es": "Personaje con iris de color azul.",
        "aliases": ["azure_eyes"],
    },
    {
        "name": "red_eyes",
        "category": "general",
        "post_count": 1410000,
        "body_en": "A character with red or crimson irises.",
        "body_es": "Personaje con iris de color rojo o carmesi.",
        "aliases": ["crimson_eyes"],
    },
    {
        "name": "monochrome",
        "category": "general",
        "post_count": 640000,
        "body_en": (
            "An image rendered using shades of a single hue or greyscale (black and white), "
            "common in manga, lineart, and tonal sketches."
        ),
        "body_es": (
            "Imagen compuesta por tonos de un solo color o en escala de grises (blanco y negro), "
            "habitual en manga, lineart y bocetos tonales."
        ),
        "aliases": ["b&w", "black_and_white", "grayscale"],
    },
    {
        "name": "chibi",
        "category": "general",
        "post_count": 370000,
        "body_en": (
            "Super-deformed art style where characters are drawn with small bodies, oversized "
            "heads, and simplified features for comedic or cute effect."
        ),
        "body_es": (
            "Estilo superdeformado en el que los personajes se dibujan con cuerpos pequenos, "
            "cabezas grandes y rasgos simplificados."
        ),
        "aliases": ["super_deformed", "sd_style"],
    },
    {
        "name": "cowboy_shot",
        "category": "general",
        "post_count": 980000,
        "body_en": (
            "A camera framing that shows a character from roughly mid-thigh or knee level up "
            "to the head, originating from classic Western film framing."
        ),
        "body_es": None,
        "aliases": ["american_shot", "thighs_up"],
    },
    {
        "name": "dutch_angle",
        "category": "general",
        "post_count": 165000,
        "body_en": (
            "A camera shot in which the horizon line is intentionally tilted relative to the "
            "bottom of the frame to create dynamism or tension."
        ),
        "body_es": None,
        "aliases": ["tilted_frame", "canted_angle"],
    },
    {
        "name": "depth_of_field",
        "category": "general",
        "post_count": 410000,
        "body_en": (
            "Optical or painted effect where the subject is sharp while the foreground or "
            "background is noticeably blurred (bokeh)."
        ),
        "body_es": None,
        "aliases": ["dof", "blurred_background_dof"],
    },
    {
        "name": "chromatic_aberration",
        "category": "general",
        "post_count": 190000,
        "body_en": (
            "Visual effect simulating lens color fringing (red/cyan or blue/yellow channel offset) "
            "along high-contrast edges."
        ),
        "body_es": None,
        "aliases": ["color_fringing", "rgb_shift"],
    },
    {
        "name": "school_uniform",
        "category": "general",
        "post_count": 1120000,
        "body_en": "Standardized clothing worn by students at an educational institution.",
        "body_es": None,
        "aliases": ["student_uniform"],
    },
    {
        "name": "serafuku",
        "category": "general",
        "post_count": 690000,
        "body_en": (
            "Traditional Japanese sailor-style school uniform featuring a sailor collar "
            "(eri) and pleated skirt."
        ),
        "body_es": (
            "Uniforme escolar japones tradicional de estilo marinero con cuello marinero "
            "(eri) y falda tableada."
        ),
        "aliases": ["sailor_uniform", "sailor_fuku"],
    },
    {
        "name": "hatsune_miku",
        "category": "character",
        "post_count": 265000,
        "body_en": (
            "Flagship Vocaloid virtual singer developed by Crypton Future Media, recognizable "
            "by her long aqua/turquoise twintails and futuristic sleeveless outfit with tie."
        ),
        "body_es": (
            "Cantante virtual insignia de Vocaloid desarrollada por Crypton Future Media, "
            "reconocible por sus largas coletas turquesas y su uniforme futurista sin mangas con corbata."
        ),
        "aliases": ["miku", "miku_hatsune", "cv01"],
    },
    {
        "name": "hakurei_reimu",
        "category": "character",
        "post_count": 182000,
        "body_en": (
            "Main protagonist of the Touhou Project series and shrine maiden (miko) of the "
            "Hakurei Shrine."
        ),
        "body_es": (
            "Protagonista principal de la saga Touhou Project y sacerdotisa (miko) del "
            "Santuario Hakurei."
        ),
        "aliases": ["reimu_hakurei", "reimu"],
    },
    {
        "name": "kirisame_marisa",
        "category": "character",
        "post_count": 156000,
        "body_en": (
            "Human magician and secondary protagonist of the Touhou Project series, known for "
            "her black witch hat and blonde hair."
        ),
        "body_es": None,
        "aliases": ["marisa_kirisame", "marisa"],
    },
    {
        "name": "artoria_pendragon_(fate)",
        "category": "character",
        "post_count": 142000,
        "body_en": (
            "Saber-class Servant from Fate/stay night and the wider Fate series, portraying "
            "a female King Arthur."
        ),
        "body_es": None,
        "aliases": ["saber", "altria_pendragon", "arturia_pendragon"],
    },
    {
        "name": "rem_(re:zero)",
        "category": "character",
        "post_count": 88000,
        "body_en": (
            "Blue-haired oni twin maid working at Roswaal L Mathers' mansion in Re:Zero."
        ),
        "body_es": None,
        "aliases": ["rem_rezero"],
    },
    {
        "name": "raiden_shogun",
        "category": "character",
        "post_count": 64000,
        "body_en": "Electro Archon (Ei) and ruler of Inazuma in Genshin Impact.",
        "body_es": None,
        "aliases": ["baal_(genshin_impact)", "raiden_ei"],
    },
    {
        "name": "vocaloid",
        "category": "copyright",
        "post_count": 415000,
        "body_en": (
            "Singing voice synthesizer software developed by Yamaha Corporation and its "
            "associated character voicebanks (such as Hatsune Miku, Kagamine Rin/Len, Megurine Luka)."
        ),
        "body_es": (
            "Software sintetizador de voz de canto desarrollado por Yamaha Corporation y sus "
            "bancos de voz asociados (como Hatsune Miku, Kagamine Rin/Len y Megurine Luka)."
        ),
        "aliases": ["project_diva_vocaloid"],
    },
    {
        "name": "touhou",
        "category": "copyright",
        "post_count": 965000,
        "body_en": (
            "Bullet-hell (danmaku) shoot-'em-up game series created by Team Shanghai Alice (ZUN), "
            "set in the fantasy realm of Gensokyo."
        ),
        "body_es": (
            "Serie de videojuegos shoot-'em-up de cortina de balas (danmaku) creada por "
            "Team Shanghai Alice (ZUN), ambientada en Gensokyo."
        ),
        "aliases": ["touhou_project", "toho_project", "project_shrine_maiden"],
    },
    {
        "name": "fate/grand_order",
        "category": "copyright",
        "post_count": 590000,
        "body_en": (
            "Turn-based RPG entry in Type-Moon's Fate franchise developed by Lasengle (formerly "
            "Delightworks)."
        ),
        "body_es": None,
        "aliases": ["fgo", "fate_grand_order"],
    },
    {
        "name": "fate_(series)",
        "category": "copyright",
        "post_count": 780000,
        "body_en": (
            "Umbrella copyright tag for Type-Moon's Fate franchise (Fate/stay night, Fate/Zero, "
            "Fate/Grand Order, Fate/Apocrypha, and spin-offs)."
        ),
        "body_es": (
            "Etiqueta global de franquicia para la saga Fate de Type-Moon (Fate/stay night, "
            "Fate/Zero, Fate/Grand Order, Fate/Apocrypha y derivados)."
        ),
        "aliases": ["fate_series", "fate_franchise"],
    },
    {
        "name": "genshin_impact",
        "category": "copyright",
        "post_count": 470000,
        "body_en": "Open-world action RPG developed and published by HoYoverse (miHoYo).",
        "body_es": (
            "Videojuego de rol de accion en mundo abierto desarrollado y publicado por HoYoverse (miHoYo)."
        ),
        "aliases": ["genshin", "yuanshen"],
    },
    {
        "name": "blue_archive",
        "category": "copyright",
        "post_count": 430000,
        "body_en": "Tactical RPG mobile game developed by Nexon Games (NAT Games) and published by Yostar.",
        "body_es": (
            "Juego de rol tactico desarrollado por Nexon Games (NAT Games) y distribuido por Yostar."
        ),
        "aliases": ["ba", "burua_kaibu"],
    },
    {
        "name": "original",
        "category": "copyright",
        "post_count": 1820000,
        "body_en": (
            "Artwork depicting characters and settings created by the artist rather than "
            "derived from an existing commercial franchise."
        ),
        "body_es": (
            "Obra que representa personajes y escenarios originales creados por el propio artista, "
            "sin pertenecer a una franquicia comercial preexistente."
        ),
        "aliases": ["original_character_work", "oc_copyright"],
    },
    {
        "name": "kantoku",
        "category": "artist",
        "post_count": 6800,
        "body_en": "Japanese illustrator and character designer (circle: 5nenme no Houkago).",
        "body_es": None,
        "aliases": ["5nenme_no_houkago"],
    },
    {
        "name": "wlop",
        "category": "artist",
        "post_count": 2100,
        "body_en": "Digital painter and creator of the GhostBlade webcomic.",
        "body_es": None,
        "aliases": ["wang_ling"],
    },
    {
        "name": "highres",
        "category": "meta",
        "post_count": 4890000,
        "body_en": (
            "Meta tag applied to high-resolution images (typically at least 1600x1200 pixels "
            "on Danbooru)."
        ),
        "body_es": (
            "Etiqueta meta aplicada a imagenes de alta resolucion (habitualmente a partir de "
            "1600x1200 pixeles en Danbooru)."
        ),
        "aliases": ["hi_res", "high_resolution", "hires"],
    },
    {
        "name": "absurdres",
        "category": "meta",
        "post_count": 1720000,
        "body_en": (
            "Meta tag applied to very high-resolution images (at least 3200x2400 pixels on Danbooru)."
        ),
        "body_es": None,
        "aliases": ["absurd_res", "ultra_highres"],
    },
    {
        "name": "commentary_request",
        "category": "meta",
        "post_count": 1150000,
        "body_en": "Meta workflow tag indicating that the original artist's commentary has not yet been transcribed.",
        "body_es": None,
        "aliases": ["needs_commentary"],
    },
]
