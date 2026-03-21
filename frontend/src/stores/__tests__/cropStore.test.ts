import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useConverterStore } from '../converterStore';

/**
 * cropStore 单元测试
 * Validates: Requirements 3.2, 3.3, 3.4, 3.5, 6.3
 */

// Mock cropImage API
vi.mock('../../api/converter', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/converter')>();
  return {
    ...actual,
    cropImage: vi.fn(),
  };
});

import { cropImage } from '../../api/converter';
const mockCropImage = vi.mocked(cropImage);

// Mock fetch (used by submitCrop to download cropped blob)
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// Mock URL.createObjectURL / revokeObjectURL
const mockCreateObjectURL = vi.fn(() => 'blob:cropped-preview');
const mockRevokeObjectURL = vi.fn();
globalThis.URL.createObjectURL = mockCreateObjectURL;
globalThis.URL.revokeObjectURL = mockRevokeObjectURL;

function resetStore(): void {
  useConverterStore.setState({
    imageFile: new File(['dummy'], 'test.png', { type: 'image/png' }),
    imagePreviewUrl: 'blob:old-preview',
    isCropping: false,
    cropModalOpen: true,
    error: null,
    enableCrop: true,
    aspectRatio: null,
  });
}

describe('submitCrop', () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  it('成功后更新 imagePreviewUrl 并关闭弹窗', async () => {
    mockCropImage.mockResolvedValue({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/abc123',
      width: 200,
      height: 100,
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['img'], { type: 'image/png' })),
    });

    await useConverterStore.getState().submitCrop(10, 20, 200, 100);

    const state = useConverterStore.getState();
    expect(state.imagePreviewUrl).toBe('blob:cropped-preview');
    expect(state.cropModalOpen).toBe(false);
    expect(state.isCropping).toBe(false);
    expect(state.error).toBeNull();
    expect(state.aspectRatio).toBe(2); // 200/100
  });

  it('失败后设置 error 状态', async () => {
    mockCropImage.mockRejectedValue(new Error('Network error'));

    await useConverterStore.getState().submitCrop(0, 0, 100, 100);

    const state = useConverterStore.getState();
    expect(state.error).toBe('Network error');
    expect(state.isCropping).toBe(false);
    expect(state.cropModalOpen).toBe(true); // stays open on failure
  });

  it('请求期间 isCropping 为 true', async () => {
    let resolveApi: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveApi = resolve; });
    mockCropImage.mockReturnValue(pending as ReturnType<typeof cropImage>);

    const promise = useConverterStore.getState().submitCrop(0, 0, 50, 50);

    // During the request, isCropping should be true
    expect(useConverterStore.getState().isCropping).toBe(true);

    // Resolve the API call
    resolveApi!({
      status: 'ok',
      message: 'Cropped',
      cropped_url: '/api/files/xyz',
      width: 50,
      height: 50,
    });
    mockFetch.mockResolvedValue({
      blob: () => Promise.resolve(new Blob(['img'], { type: 'image/png' })),
    });

    await promise;

    expect(useConverterStore.getState().isCropping).toBe(false);
  });
});

describe('使用原图 (setCropModalOpen)', () => {
  beforeEach(() => {
    resetStore();
  });

  it('setCropModalOpen(false) 关闭弹窗并保留原始图片', () => {
    expect(useConverterStore.getState().cropModalOpen).toBe(true);

    useConverterStore.getState().setCropModalOpen(false);

    const state = useConverterStore.getState();
    expect(state.cropModalOpen).toBe(false);
    // Original image is preserved
    expect(state.imagePreviewUrl).toBe('blob:old-preview');
    expect(state.imageFile).not.toBeNull();
  });
});
