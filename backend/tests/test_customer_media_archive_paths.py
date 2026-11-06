"""ZIP layout follows client-facing tags without unsafe or colliding paths."""
from itertools import product
from pathlib import PurePosixPath

import pytest

from app.customer_media.archive_paths import ArchiveNames, tag_folders


DIMENSIONS = [
    {"id": 1, "name": "customer_product_type", "label": "Product type"},
    {"id": 2, "name": "textures_type", "label": "Textures type"},
    {"id": 3, "name": "color_names", "label": "Color names"},
    {"id": 4, "name": "purpose", "label": "Purpose"},
]


def tag(dim, value):
    return {"dimension_id": dim, "value": value}


@pytest.mark.parametrize("present", list(product([False, True], repeat=3)))
def test_missing_levels_are_skipped_without_placeholder_folders(present):
    labels = ["Genius Weft", "Straight", "#1B"]
    tags = [tag(index + 1, label) for index, label in enumerate(labels) if present[index]]
    tags.append(tag(4, "Do not include"))
    paths = list(tag_folders(tags, DIMENSIONS))
    assert paths == [tuple(label for index, label in enumerate(labels) if present[index])]
    assert ArchiveNames().file(paths[0], "photo.jpg") == "/".join([*paths[0], "photo.jpg"])


def test_each_combination_of_multiple_tags_gets_a_copy_in_fixed_order():
    tags = [tag(3, "#60"), tag(1, "Genius Weft"), tag(2, "Straight"),
            tag(3, "#1B"), tag(2, "Wavy"), tag(3, "#1B")]
    assert list(tag_folders(tags, DIMENSIONS)) == [
        ("Genius Weft", "Straight", "#60"), ("Genius Weft", "Straight", "#1B"),
        ("Genius Weft", "Wavy", "#60"), ("Genius Weft", "Wavy", "#1B"),
    ]


def test_stable_dimension_names_and_localized_labels_both_work():
    dims = [
        {"id": 1, "name": "product_type_customer", "label": "Renamed product"},
        {"id": 2, "name": "custom_texture", "label": "纹理类型"},
        {"id": 3, "name": "custom_color", "label": "Color names"},
    ]
    assert list(tag_folders([tag(1, "产品"), tag(2, "纹理"), tag(3, "颜色")], dims)) == [("产品", "纹理", "颜色")]
    assert list(tag_folders([tag(1, "  "), tag(3, "#1B")], dims)) == [("#1B",)]


def test_unsafe_names_stay_inside_the_archive_and_keep_three_levels_at_most():
    names = ArchiveNames()
    path = names.file(("../../Wig", "CON", "#1B/60"), '..\\evil:<file>.jpg')
    parts = PurePosixPath(path).parts
    assert len(parts) == 4
    assert not PurePosixPath(path).is_absolute()
    assert not set(parts) & {".", "..", "CON"}
    assert all(not any(char in part for char in '<>:"\\|?*') for part in parts)
    assert all(not part.endswith((".", " ")) for part in parts)


def test_duplicate_names_across_batches_and_case_collisions_never_overwrite():
    names = ArchiveNames()
    assert names.file(("Wig",), "Photo.JPG") == "Wig/Photo.JPG"
    assert names.file(("Wig",), "photo.jpg") == "Wig/photo (2).jpg"
    assert names.file(("Wig",), "photo (2).jpg") == "Wig/photo (2) (2).jpg"
    first = names.file(("A/B",), "p.jpg")
    second = names.file(("A:B",), "p.jpg")
    assert first.casefold() != second.casefold()
    assert names.file(("A/B",), "q.jpg").rsplit('/', 1)[0] == first.rsplit('/', 1)[0]


def test_files_cannot_shadow_a_directory_and_long_unicode_names_remain_valid():
    names = ArchiveNames()
    first = names.file((), "folder.jpg")
    second = names.file(("folder.jpg",), "x.jpg")
    assert second.split('/')[0] != first
    long = names.file(("颜色" * 100,), "产品图片" * 100 + '.png')
    assert long.endswith('.png')
    assert all(len(part.encode('utf-8')) <= 180 for part in long.split('/'))
