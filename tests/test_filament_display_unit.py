from core.filament_display import catalog_thumbnail_metadata, filament_display


def test_resource_details_survive_public_projection_without_private_fields() -> None:
    material = {
        "brand": "Aliz", "material_name": "PETG Red", "series": "PETG",
        "description": {"zh": "实测耗材", "en": "Measured filament"},
        "contributor_name": "Legacy author",
        "purchase_links": [{"market": "CN", "label": "Product", "url": "https://shop.example.cn/red"}],
        "private_path": "/private/archive", "email": "private@example.invalid",
    }
    projected = filament_display(material)
    assert projected["purchase_links"] == material["purchase_links"]
    assert projected["description"] == material["description"]
    assert projected["series"] == "PETG"
    assert "private_path" not in projected
    assert "email" not in projected
    lut = {
        "name": "Mixed palette",
        "filaments": [
            {"slot": 0, "brand": "Aliz", "material_name": "PETG Red",
             "purchase_links": material["purchase_links"]},
            {"slot": 1, "brand": "Bambu Lab", "material_name": "PETG White"},
        ],
    }
    assert filament_display(lut)["filaments"] == lut["filaments"]
    assert catalog_thumbnail_metadata({"display": lut})["display"]["filaments"] == lut["filaments"]


def test_resource_purchase_links_exclude_credentials_and_private_link_fields() -> None:
    links = [
        {"url": "https://shop.example.com/red?variant=0123", "market": "INTL", "email": "private@example.invalid"},
        {"url": "javascript:alert(1)"},
        {"url": "https://user:password@shop.example.com/"},
    ]
    expected = [{"url": "https://shop.example.com/red?variant=0123", "market": "INTL"}]
    result = filament_display({"purchase_links": links, "filaments": [{"slot": 0, "purchase_links": links}]})
    assert result["purchase_links"] == expected
    assert result["filaments"][0]["purchase_links"] == expected
