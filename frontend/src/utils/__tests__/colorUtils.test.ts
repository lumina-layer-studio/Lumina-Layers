import { describe, it, expect } from 'vitest';
import { hexToLuminance } from '../colorUtils';

/**
 * hexToLuminance 单元测试
 * 公式: luminance = 0.299 * R + 0.587 * G + 0.114 * B
 * Validates: Requirements 9.4, 2.4, 4.3, 4.5
 */

describe('hexToLuminance 边界值与具体值', () => {
  it('000000 (纯黑) → 0', () => {
    expect(hexToLuminance('000000')).toBe(0);
  });

  it('ffffff (纯白) → 255', () => {
    expect(hexToLuminance('ffffff')).toBeCloseTo(255, 1);
  });

  it('ff0000 (纯红) → 0.299 * 255 ≈ 76.245', () => {
    expect(hexToLuminance('ff0000')).toBeCloseTo(0.299 * 255, 2);
  });

  it('00ff00 (纯绿) → 0.587 * 255 ≈ 149.685', () => {
    expect(hexToLuminance('00ff00')).toBeCloseTo(0.587 * 255, 2);
  });

  it('0000ff (纯蓝) → 0.114 * 255 ≈ 29.07', () => {
    expect(hexToLuminance('0000ff')).toBeCloseTo(0.114 * 255, 2);
  });
});
