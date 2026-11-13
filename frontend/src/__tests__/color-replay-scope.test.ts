import { describe, it, expect } from 'vitest';
import { DEFAULT_STATE } from '../stores/converter';
import { DEFAULT_SETTINGS } from '../stores/settingsStore';
import { buildSourceChangeProjectColorState, normalizeReplacementRegionsFromHistory } from '../stores/converter/editorState';
import { colorRemapToReplacementRegions } from '../utils/colorUtils';
import { exportConverterRecipe } from '../recipe/exportRecipe';
import type { ConverterState } from '../stores/converter/store';

const scope = { shape: [1, 2], bits: 'eJxrAAAAgQCB' };
const record = { quantized_hex: '#112233', matched_hex: '#112233', replacement_hex: '#ff0000', source_scope: scope };

describe('portable whole-color ownership', () => {
  it('retains captured ownership through receipt, material reset and preview serialization', () => {
    const records = normalizeReplacementRegionsFromHistory([record]);
    const state = { ...DEFAULT_STATE, replacement_regions: records,
      colorRemapMap: { '112233': 'ff0000' },
      palette: [{ quantized_hex: '010101', matched_hex: '112233', pixel_count: 1, percentage: 50 }],
    } as ConverterState;
    const portable = buildSourceChangeProjectColorState(state);
    expect(portable.replacement_regions).toHaveLength(1);
    expect(portable.replacement_regions[0].source_scope).toEqual(scope);
    const remaps = colorRemapToReplacementRegions(state.colorRemapMap, state.palette, records);
    expect(JSON.parse(JSON.stringify(remaps))[0].source_scope).toEqual(scope);
  });
  it('round trips ownership in saved recipe JSON', () => {
    const state = { ...DEFAULT_STATE, replacement_regions: [record] } as ConverterState;
    const converter = exportConverterRecipe(state, DEFAULT_SETTINGS, 'test');
    expect(converter.color_ops.replacement_regions[0].source_scope).toEqual(scope);

  });
});
