"""Typed public schemas for dynamic material-layer results.
动态耗材层数结果的强类型公开 Schema。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RgbChannel = Annotated[int, Field(ge=0, le=255)]
MaterialIndex = Annotated[int, Field(ge=0)]
LayerCount = Annotated[int, Field(ge=5, le=30)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
DynamicBenefitScope = Literal["all_printable_pixels", "automatic_pixels"]


class _DynamicMaterialResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DynamicMaterialLayerCapOptionResponse(_DynamicMaterialResponseModel):
    """One exact result for a cumulative effective-layer cap.
    一个累计有效层数上限对应的精确结果。
    """

    max_effective_layer_count: LayerCount
    actual_layer_count: LayerCount
    matched_srgb: tuple[RgbChannel, RgbChannel, RgbChannel]
    actual_recipe_top_to_bottom: list[MaterialIndex]
    print_recipe_top_to_bottom: list[MaterialIndex]
    delta_e00: NonNegativeFloat

    @model_validator(mode="after")
    def _validate_recipe_lengths(self) -> "DynamicMaterialLayerCapOptionResponse":
        if len(self.actual_recipe_top_to_bottom) != self.actual_layer_count:
            raise ValueError("actual recipe length must equal actual_layer_count")
        if self.actual_layer_count > self.max_effective_layer_count:
            raise ValueError("actual_layer_count must not exceed its cap")
        if len(self.print_recipe_top_to_bottom) < self.actual_layer_count:
            raise ValueError("print recipe must contain every actual layer")
        if (
            self.print_recipe_top_to_bottom[: self.actual_layer_count]
            != self.actual_recipe_top_to_bottom
        ):
            raise ValueError("print recipe must start with the actual recipe")
        padding = self.print_recipe_top_to_bottom[self.actual_layer_count :]
        if padding and any(value != padding[0] for value in padding):
            raise ValueError("print recipe padding must use one backing material")
        return self


class DynamicMaterialRecipeResponse(_DynamicMaterialResponseModel):
    """Exact selected recipe metadata for one requested target colour.
    单个目标颜色所选精确配方的元数据。
    """

    target_srgb: tuple[RgbChannel, RgbChannel, RgbChannel]
    matched_srgb: tuple[RgbChannel, RgbChannel, RgbChannel]
    actual_layer_count: LayerCount
    padding_layer_count: Annotated[int, Field(ge=0)]
    actual_recipe_top_to_bottom: list[MaterialIndex]
    print_recipe_top_to_bottom: list[MaterialIndex]
    selected_delta_e00: NonNegativeFloat
    best_range_delta_e00: NonNegativeFloat
    fixed_max_delta_e00: NonNegativeFloat
    delta_e00_sacrifice: NonNegativeFloat
    layer_cap_options: list[DynamicMaterialLayerCapOptionResponse]

    @model_validator(mode="after")
    def _validate_recipe_lengths(self) -> "DynamicMaterialRecipeResponse":
        if len(self.actual_recipe_top_to_bottom) != self.actual_layer_count:
            raise ValueError("actual recipe length must equal actual_layer_count")
        if len(self.print_recipe_top_to_bottom) != (
            self.actual_layer_count + self.padding_layer_count
        ):
            raise ValueError("print recipe length must equal actual plus padding")
        if (
            self.print_recipe_top_to_bottom[: self.actual_layer_count]
            != self.actual_recipe_top_to_bottom
        ):
            raise ValueError("print recipe must start with the actual recipe")
        selected_padding = self.print_recipe_top_to_bottom[
            self.actual_layer_count :
        ]
        if selected_padding and any(
            value != selected_padding[0] for value in selected_padding
        ):
            raise ValueError("print recipe padding must use one backing material")
        if any(
            len(option.print_recipe_top_to_bottom)
            != len(self.print_recipe_top_to_bottom)
            for option in self.layer_cap_options
        ):
            raise ValueError("layer-cap print recipes must use the selected print depth")
        caps = [option.max_effective_layer_count for option in self.layer_cap_options]
        if not caps or caps != list(range(caps[0], caps[-1] + 1)):
            raise ValueError("layer-cap options must be non-empty and consecutive")
        if caps[-1] != len(self.print_recipe_top_to_bottom):
            raise ValueError("maximum layer cap must equal the print depth")
        backing_candidates = [
            option.print_recipe_top_to_bottom[option.actual_layer_count]
            for option in self.layer_cap_options
            if len(option.print_recipe_top_to_bottom) > option.actual_layer_count
        ]
        if selected_padding:
            backing_candidates.append(selected_padding[0])
        if backing_candidates and any(
            value != backing_candidates[0] for value in backing_candidates
        ):
            raise ValueError("all layer-cap options must use one backing material")
        if not any(
            option.actual_layer_count == self.actual_layer_count
            and option.matched_srgb == self.matched_srgb
            and option.actual_recipe_top_to_bottom
            == self.actual_recipe_top_to_bottom
            and option.delta_e00 == self.selected_delta_e00
            for option in self.layer_cap_options
        ):
            raise ValueError("selected recipe must match one layer-cap option")
        return self


class MaterialLayerBenefitPointResponse(_DynamicMaterialResponseModel):
    """Pixel-weighted exact result for one effective-layer cap.
    单个有效层数上限对应的像素加权精确结果。
    """

    max_effective_layer_count: LayerCount
    weighted_mean_delta_e00: NonNegativeFloat
    marginal_delta_e00_reduction: NonNegativeFloat


class DynamicMaterialResultResponse(_DynamicMaterialResponseModel):
    """Optional dynamic result fields shared by preview and edit responses.
    预览和编辑响应共享的可选动态结果字段。
    """

    material_dynamic_recipes: list[DynamicMaterialRecipeResponse] | None = None
    material_layer_benefit_curve: list[MaterialLayerBenefitPointResponse] | None = None
    material_layer_benefit_scope: DynamicBenefitScope | None = None
    material_layer_benefit_pixel_count: Annotated[int, Field(ge=0)] | None = None
    operation_id: str | None = None
    editor_content_revision: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _validate_benefit_caps(self) -> "DynamicMaterialResultResponse":
        if (self.material_layer_benefit_scope is None) != (
            self.material_layer_benefit_pixel_count is None
        ):
            raise ValueError(
                "benefit scope and effective pixel count must be supplied together"
            )
        if not self.material_dynamic_recipes or not self.material_layer_benefit_curve:
            return self
        expected_caps = [
            option.max_effective_layer_count
            for option in self.material_dynamic_recipes[0].layer_cap_options
        ]
        if any(
            [option.max_effective_layer_count for option in recipe.layer_cap_options]
            != expected_caps
            for recipe in self.material_dynamic_recipes
        ):
            raise ValueError("all dynamic recipes must expose the same layer caps")
        curve_caps = [
            point.max_effective_layer_count
            for point in self.material_layer_benefit_curve
        ]
        if curve_caps != expected_caps:
            raise ValueError("benefit curve caps must match recipe layer caps")
        return self
