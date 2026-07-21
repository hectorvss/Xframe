from app.context.manager import ContextDetail, _format_production
from app.context.types import XframeUIContext


def test_production_context_exposes_locked_visual_links_and_sound_templates() -> None:
    context = XframeUIContext(
        project_id="project-1",
        asset_links=[
            {
                "id": "link-1",
                "scene_id": "scene-1",
                "script_line_id": "line-1",
                "asset_id": "asset-1",
                "asset_name": "Packshot aprobado",
                "asset_type": "Imagen",
                "asset_path": "project/assets/packshot.png",
                "role": "product",
                "instructions": "No cambiar la etiqueta.",
                "start_offset_ms": 1200,
                "end_offset_ms": 3400,
                "locked": True,
            }
        ],
        audio_templates=[
            {
                "id": "template-1",
                "name": "Reveal limpio",
                "kind": "sfx",
                "prompt": "Impacto corto y premium.",
                "duration_ms": 1400,
                "loop": False,
                "intensity": 0.7,
            }
        ],
    )

    rendered = _format_production(context, ContextDetail.FULL)

    assert "<screenplay_asset_links>" in rendered
    assert 'asset_id="asset-1"' in rendered
    assert 'role="product"' in rendered
    assert 'range_ms="1200-3400"' in rendered
    assert 'locked="true"' in rendered
    assert "No cambiar la etiqueta." in rendered
    assert "<sound_templates>" in rendered
    assert 'name="Reveal limpio"' in rendered
    assert "Impacto corto y premium." in rendered
