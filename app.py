from __future__ import annotations

import io
import math
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable, Sequence

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError


BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "icons"

# Supports either of these layouts:
#   app.py + index.html
#   app.py + templates/index.html
STANDARD_TEMPLATE_DIR = BASE_DIR / "templates"
TEMPLATE_DIR = (
    BASE_DIR
    if (BASE_DIR / "index.html").is_file()
    else STANDARD_TEMPLATE_DIR
)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

MAX_OUTPUT_SIZE = 2048
# Limit expensive pixel-by-pixel analysis on low-CPU hosting. The UI exports
# at up to 400 px, so 512 px retains clean edges while preventing Gunicorn
# request timeouts on Render Free.
PROCESSING_MAX_DIMENSION = 512
HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
RESAMPLING_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

# Catalog entries must match the filenames inside the icons folder.
ICONS_DB = [
    {
        "id": "1",
        "src": "cream.png",
        "tags": ["cream", "finger", "hand", "lotion", "moisturizer"],
    },
    {
        "id": "2",
        "src": "lotion.png",
        "tags": ["c", "drop", "pink", "white", "serum", "lotion"],
    },
    {
        "id": "3",
        "src": "guava.png",
        "tags": ["apple", "fruit", "red", "guava"],
    },
    {
        "id": "4",
        "src": "c_drop.png",
        "tags": ["c", "drop", "serum", "pink"],
    },
    {
        "id": "5",
        "src": "coffee_seed.png",
        "tags": ["coffee", "seed", "bean", "brown"],
    },
    {
        "id": "6",
        "src": "drop.png",
        "tags": ["drop", "water", "liquid", "blue"],
    },
    {
        "id": "7",
        "src": "hands.png",
        "tags": ["hands", "care", "protection", "skin"],
    },
    {
        "id": "8",
        "src": "pink_star.png",
        "tags": ["pink", "star", "badge", "sparkle"],
    },
    {
        "id": "9",
        "src": "purple_drop.png",
        "tags": ["purple", "drop", "liquid", "oil"],
    },
    {
        "id": "10",
        "src": "sponge_bar.png",
        "tags": ["sponge", "bar", "clean", "wash"],
    },
    {
        "id": "11",
        "src": "star_bar.png",
        "tags": ["star", "bar", "rating", "yellow"],
    },
]

ALLOWED_ICON_NAMES = {icon["src"] for icon in ICONS_DB}


def normalize_hex_color(value: str | None) -> tuple[int, int, int] | None:
    """Validate a browser color value and return an RGB tuple."""
    if value is None or value == "":
        return None

    match = HEX_COLOR_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("bg_color must be a six-digit hexadecimal color")

    hex_value = match.group(1)
    return tuple(int(hex_value[index : index + 2], 16) for index in (0, 2, 4))


def clamp_dimension(value: int | None) -> int | None:
    """Keep requested output dimensions within a safe range."""
    if value is None:
        return None
    return max(16, min(MAX_OUTPUT_SIZE, int(value)))


def color_distance_squared(
    first: tuple[int, int, int], second: tuple[int, int, int]
) -> int:
    return sum((first[channel] - second[channel]) ** 2 for channel in range(3))


def border_indices(width: int, height: int) -> list[int]:
    """Return all unique pixel indexes around the outer border."""
    if width <= 0 or height <= 0:
        return []

    indexes: set[int] = set()
    for x in range(width):
        indexes.add(x)
        indexes.add((height - 1) * width + x)
    for y in range(height):
        indexes.add(y * width)
        indexes.add(y * width + (width - 1))
    return list(indexes)


def ring_indices(width: int, height: int) -> list[int]:
    """
    Sample several rings around the illustration.

    Flat icon backgrounds normally occupy these rings, while the subject is
    usually concentrated closer to the center.
    """
    if width < 3 or height < 3:
        return border_indices(width, height)

    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    shortest_side = min(width, height)
    samples_per_ring = max(72, min(240, int(shortest_side * 1.25)))

    indexes: set[int] = set()
    for radius_fraction in (0.28, 0.34, 0.40):
        radius = shortest_side * radius_fraction
        for sample_number in range(samples_per_ring):
            angle = (2.0 * math.pi * sample_number) / samples_per_ring
            x = int(round(center_x + math.cos(angle) * radius))
            y = int(round(center_y + math.sin(angle) * radius))
            if 0 <= x < width and 0 <= y < height:
                indexes.add(y * width + x)

    return list(indexes)


def dominant_color_candidates(
    pixels: Sequence[tuple[int, int, int, int]],
    indexes: Iterable[int],
    *,
    bin_size: int = 16,
    minimum_alpha: int = 24,
) -> tuple[list[tuple[tuple[int, int, int], int]], int]:
    """
    Return coarse RGB color clusters, ordered by frequency.

    Coarse bins make the detector tolerant of compression and anti-aliasing.
    """
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(
        lambda: [0, 0, 0, 0]
    )
    opaque_samples = 0

    for index in indexes:
        red, green, blue, alpha = pixels[index]
        if alpha < minimum_alpha:
            continue

        opaque_samples += 1
        key = (red // bin_size, green // bin_size, blue // bin_size)
        bucket = buckets[key]
        bucket[0] += 1
        bucket[1] += red
        bucket[2] += green
        bucket[3] += blue

    candidates: list[tuple[tuple[int, int, int], int]] = []
    for count, red_sum, green_sum, blue_sum in buckets.values():
        candidates.append(
            (
                (
                    round(red_sum / count),
                    round(green_sum / count),
                    round(blue_sum / count),
                ),
                count,
            )
        )

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates, opaque_samples


def connected_color_mask(
    pixels: Sequence[tuple[int, int, int, int]],
    width: int,
    height: int,
    seeds: Iterable[int],
    target_color: tuple[int, int, int],
    *,
    core_tolerance: float,
    edge_tolerance: float,
) -> bytearray:
    """
    Build a soft mask for pixels connected to seed points and close to a color.

    Restricting the mask to connected regions prevents similarly colored,
    isolated foreground details from being removed accidentally.
    """
    pixel_count = width * height
    visited = bytearray(pixel_count)
    mask = bytearray(pixel_count)
    queue: deque[int] = deque()

    core_squared = core_tolerance * core_tolerance
    edge_squared = edge_tolerance * edge_tolerance
    feather_range = max(0.001, edge_tolerance - core_tolerance)

    def mask_strength(index: int) -> int:
        red, green, blue, alpha = pixels[index]
        if alpha <= 2:
            return 0

        distance_squared = color_distance_squared(
            (red, green, blue), target_color
        )
        if distance_squared > edge_squared:
            return 0
        if distance_squared <= core_squared:
            return 255

        distance = math.sqrt(distance_squared)
        strength = 255.0 * (edge_tolerance - distance) / feather_range
        return max(1, min(254, round(strength)))

    for seed in seeds:
        if seed < 0 or seed >= pixel_count or visited[seed]:
            continue
        visited[seed] = 1
        strength = mask_strength(seed)
        if strength:
            mask[seed] = strength
            queue.append(seed)

    while queue:
        index = queue.popleft()
        x = index % width
        y = index // width

        neighbours: list[int] = []
        if x > 0:
            neighbours.append(index - 1)
        if x + 1 < width:
            neighbours.append(index + 1)
        if y > 0:
            neighbours.append(index - width)
        if y + 1 < height:
            neighbours.append(index + width)

        for neighbour in neighbours:
            if visited[neighbour]:
                continue
            visited[neighbour] = 1
            strength = mask_strength(neighbour)
            if strength:
                mask[neighbour] = strength
                queue.append(neighbour)

    return mask


def mask_coverage(mask: bytearray, minimum_strength: int = 24) -> float:
    if not mask:
        return 0.0
    covered = sum(1 for value in mask if value >= minimum_strength)
    return covered / len(mask)


def combine_masks(*masks: bytearray) -> bytearray:
    usable_masks = [mask for mask in masks if mask]
    if not usable_masks:
        return bytearray()

    combined = bytearray(len(usable_masks[0]))
    for index in range(len(combined)):
        combined[index] = max(mask[index] for mask in usable_masks)
    return combined


def pillow_mask(
    mask: bytearray,
    size: tuple[int, int],
    *,
    expand: bool = False,
) -> Image.Image:
    image = Image.frombytes("L", size, bytes(mask))
    if expand and min(size) >= 3:
        # One-pixel expansion removes colored anti-aliasing halos left at the
        # outside edge of transparent backgrounds.
        image = image.filter(ImageFilter.MaxFilter(3))
    # A light blur keeps anti-aliased edges natural without swallowing detail.
    return image.filter(ImageFilter.GaussianBlur(radius=0.65))


def clear_with_mask(image: Image.Image, mask: Image.Image) -> Image.Image:
    result = image.copy()
    current_alpha = result.getchannel("A")
    remaining_alpha = ImageChops.multiply(current_alpha, ImageOps.invert(mask))
    result.putalpha(remaining_alpha)
    return result


def replace_with_color(
    image: Image.Image, mask: Image.Image, color: tuple[int, int, int]
) -> Image.Image:
    solid = Image.new("RGBA", image.size, (*color, 255))
    return Image.composite(solid, image, mask)


def add_color_behind_transparent_artwork(
    image: Image.Image, color: tuple[int, int, int]
) -> Image.Image:
    """Fallback for source files that are already transparent cut-outs."""
    background = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(background)
    draw.ellipse((0, 0, image.width - 1, image.height - 1), fill=(*color, 255))
    background.alpha_composite(image)
    return background


def process_icon_image(
    image_path: Path,
    width: int | None = None,
    height: int | None = None,
    remove_background: bool = False,
    background_color: tuple[int, int, int] | None = None,
) -> io.BytesIO:
    """
    Remove or recolor a flat icon background while preserving the illustration.

    Background analysis is performed on a bounded working image rather than on
    every pixel of a potentially huge source PNG. This keeps previews fast on
    low-CPU hosting while retaining enough resolution for clean edge masks.
    """
    with Image.open(image_path) as source:
        source_image = source.convert("RGBA")

    output_width = width or source_image.width
    output_height = height or source_image.height
    output_size = (output_width, output_height)

    # A plain resize does not need any background analysis.
    if not remove_background and background_color is None:
        result = source_image
        if result.size != output_size:
            result = result.resize(output_size, RESAMPLING_LANCZOS)

        output = io.BytesIO()
        result.save(output, format="PNG", compress_level=6)
        output.seek(0)
        return output

    # Process at no less than 256px for mask quality, but never above 512px so
    # large source files cannot exhaust a free Render instance or hit a worker
    # timeout. The current UI requests at most 400px outputs.
    requested_long_side = max(output_size)
    working_long_side = min(512, max(256, requested_long_side))
    scale = working_long_side / requested_long_side
    working_size = (
        max(16, round(output_width * scale)),
        max(16, round(output_height * scale)),
    )

    image = source_image
    if image.size != working_size:
        image = image.resize(working_size, RESAMPLING_LANCZOS)

    pixel_data = list(image.getdata())
    image_width, image_height = image.size
    total_pixels = image_width * image_height

    outer_indexes = border_indices(image_width, image_height)
    outer_candidates, opaque_border_samples = dominant_color_candidates(
        pixel_data, outer_indexes
    )

    outer_color: tuple[int, int, int] | None = None
    minimum_opaque_border = max(8, round(len(outer_indexes) * 0.20))
    if outer_candidates and opaque_border_samples >= minimum_opaque_border:
        candidate_color, candidate_count = outer_candidates[0]
        if candidate_count >= max(4, round(opaque_border_samples * 0.12)):
            outer_color = candidate_color

    outer_mask = bytearray(total_pixels)
    if outer_color is not None:
        outer_seed_indexes = [
            index
            for index in outer_indexes
            if pixel_data[index][3] > 2
            and color_distance_squared(pixel_data[index][:3], outer_color)
            <= 72 * 72
        ]
        outer_mask = connected_color_mask(
            pixel_data,
            image_width,
            image_height,
            outer_seed_indexes,
            outer_color,
            core_tolerance=30,
            edge_tolerance=72,
        )
        if mask_coverage(outer_mask) < 0.002:
            outer_mask = bytearray(total_pixels)

    inner_indexes = ring_indices(image_width, image_height)
    inner_candidates, opaque_ring_samples = dominant_color_candidates(
        pixel_data, inner_indexes
    )

    inner_color: tuple[int, int, int] | None = None
    minimum_opaque_ring = max(12, round(len(inner_indexes) * 0.25))
    if inner_candidates and opaque_ring_samples >= minimum_opaque_ring:
        inner_color = inner_candidates[0][0]
        if outer_color is not None and color_distance_squared(
            inner_color, outer_color
        ) <= 44 * 44:
            for alternative_color, alternative_count in inner_candidates[1:]:
                if (
                    alternative_count >= max(8, round(opaque_ring_samples * 0.08))
                    and color_distance_squared(alternative_color, outer_color)
                    > 44 * 44
                ):
                    inner_color = alternative_color
                    break

    inner_mask = bytearray(total_pixels)
    if inner_color is not None:
        inner_seed_indexes = [
            index
            for index in inner_indexes
            if pixel_data[index][3] > 2
            and color_distance_squared(pixel_data[index][:3], inner_color)
            <= 96 * 96
        ]
        inner_mask = connected_color_mask(
            pixel_data,
            image_width,
            image_height,
            inner_seed_indexes,
            inner_color,
            core_tolerance=38,
            edge_tolerance=96,
        )
        if mask_coverage(inner_mask) < 0.02:
            inner_mask = bytearray(total_pixels)
            inner_color = None

    outer_coverage = mask_coverage(outer_mask)
    inner_coverage = mask_coverage(inner_mask)
    result = image

    if remove_background:
        removal_mask_bytes = combine_masks(outer_mask, inner_mask)
        if removal_mask_bytes and mask_coverage(removal_mask_bytes) > 0.001:
            result = clear_with_mask(
                result,
                pillow_mask(removal_mask_bytes, result.size, expand=True),
            )

    elif background_color is not None:
        colors_are_distinct = (
            outer_color is not None
            and inner_color is not None
            and color_distance_squared(outer_color, inner_color) > 44 * 44
        )

        if inner_coverage > 0:
            if colors_are_distinct:
                result = replace_with_color(
                    result,
                    pillow_mask(inner_mask, result.size),
                    background_color,
                )
                if outer_coverage > 0:
                    result = clear_with_mask(
                        result,
                        pillow_mask(outer_mask, result.size, expand=True),
                    )
            else:
                replacement_mask_bytes = combine_masks(outer_mask, inner_mask)
                result = replace_with_color(
                    result,
                    pillow_mask(replacement_mask_bytes, result.size),
                    background_color,
                )
        elif outer_coverage > 0:
            result = replace_with_color(
                result,
                pillow_mask(outer_mask, result.size),
                background_color,
            )
        else:
            result = add_color_behind_transparent_artwork(
                result, background_color
            )

    if result.size != output_size:
        result = result.resize(output_size, RESAMPLING_LANCZOS)

    output = io.BytesIO()
    # optimize=True is CPU-heavy; normal compression is faster and reliable.
    result.save(output, format="PNG", compress_level=6)
    output.seek(0)
    return output


def icon_record(icon: dict[str, object]) -> dict[str, object]:
    """Return catalog data plus whether the corresponding file is present."""
    filename = str(icon["src"])
    return {
        **icon,
        "available": (ICONS_DIR / filename).is_file(),
    }


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/search")
def search_icons():
    query = request.args.get("tag", "").strip().lower()
    icons = ICONS_DB

    if query:
        icons = [
            icon
            for icon in ICONS_DB
            if query in str(icon["src"]).lower()
            or any(query in str(tag).lower() for tag in icon["tags"])
        ]

    response = jsonify([icon_record(icon) for icon in icons])
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/icons/<path:filename>")
def raw_icon(filename: str):
    """Serve catalog images from the project-level icons folder."""
    if filename not in ALLOWED_ICON_NAMES:
        abort(404)
    return send_from_directory(str(ICONS_DIR), filename, max_age=0)


@app.get("/api/process/<icon_id>")
def process_icon(icon_id: str):
    icon = next((item for item in ICONS_DB if item["id"] == icon_id), None)
    if icon is None:
        return jsonify({"error": "Unknown icon id"}), 404

    image_path = ICONS_DIR / str(icon["src"])
    if not image_path.is_file():
        return (
            jsonify(
                {
                    "error": (
                        f"{icon['src']} was not found. Put it inside "
                        f"{ICONS_DIR}"
                    )
                }
            ),
            404,
        )

    requested_size = request.args.get("size", type=int)
    width = clamp_dimension(request.args.get("width", type=int) or requested_size)
    height = clamp_dimension(request.args.get("height", type=int) or requested_size)
    remove_background = (
        request.args.get("remove_bg", "false").strip().lower() == "true"
    )

    try:
        background_color = normalize_hex_color(request.args.get("bg_color"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    # Transparency takes precedence over a replacement color.
    if remove_background:
        background_color = None

    try:
        image_stream = process_icon_image(
            image_path=image_path,
            width=width,
            height=height,
            remove_background=remove_background,
            background_color=background_color,
        )
    except (OSError, UnidentifiedImageError) as error:
        return jsonify({"error": f"Could not read image: {error}"}), 500
    except Exception as error:  # Keeps the image endpoint useful in production.
        app.logger.exception("Icon processing failed")
        return jsonify({"error": f"Image processing failed: {error}"}), 500

    as_download = (
        request.args.get("download", "false").strip().lower() == "true"
    )
    output_name = f"{Path(str(icon['src'])).stem}_custom.png"

    response = send_file(
        image_stream,
        mimetype="image/png",
        as_attachment=as_download,
        download_name=output_name,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


if __name__ == "__main__":
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
