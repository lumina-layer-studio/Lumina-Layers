import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useConverterStore } from '../stores/converterStore';

describe('submitFullPipeline', () => {
  beforeEach(() => {
    useConverterStore.setState({
      sessionId: null,
      threemfDiskPath: null,
      downloadUrl: null,
      modelUrl: null,
      isLoading: false,
      error: null,
    });
  });

  // Req 2.1: 无 sessionId 时先预览再生成
  it('should call submitPreview then submitGenerate when no sessionId', async () => {
    const callOrder: string[] = [];

    const mockSubmitPreview = vi.fn(async () => {
      callOrder.push('preview');
      useConverterStore.setState({ sessionId: 'session-abc' });
    });
    const mockSubmitGenerate = vi.fn(async () => {
      callOrder.push('generate');
      useConverterStore.setState({
        threemfDiskPath: '/tmp/model.3mf',
        modelUrl: 'http://localhost:8000/api/files/glb-123',
      });
      return 'http://localhost:8000/api/files/glb-123';
    });

    useConverterStore.setState({
      sessionId: null,
      submitPreview: mockSubmitPreview,
      submitGenerate: mockSubmitGenerate,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(mockSubmitPreview).toHaveBeenCalledOnce();
    expect(mockSubmitGenerate).toHaveBeenCalledOnce();
    expect(callOrder).toEqual(['preview', 'generate']);
    expect(result).toBe('http://localhost:8000/api/files/glb-123');
  });

  // Req 2.2: 有 sessionId 时跳过预览直接生成
  it('should skip submitPreview and call submitGenerate directly when sessionId exists', async () => {
    const mockSubmitPreview = vi.fn(async () => {});
    const mockSubmitGenerate = vi.fn(async () => {
      useConverterStore.setState({
        threemfDiskPath: '/tmp/model.3mf',
        modelUrl: 'http://localhost:8000/api/files/glb-456',
      });
      return 'http://localhost:8000/api/files/glb-456';
    });

    useConverterStore.setState({
      sessionId: 'existing-session',
      submitPreview: mockSubmitPreview,
      submitGenerate: mockSubmitGenerate,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    expect(mockSubmitGenerate).toHaveBeenCalledOnce();
    expect(result).toBe('http://localhost:8000/api/files/glb-456');
  });

  // Req 5.3: 预览失败时停止流水线，不调用 generate
  it('should return null and not call submitGenerate when preview fails', async () => {
    const mockSubmitPreview = vi.fn(async () => {
      // Preview fails: sessionId remains null, error is set
      useConverterStore.setState({ error: '预览失败' });
    });
    const mockSubmitGenerate = vi.fn(async () => null);

    useConverterStore.setState({
      sessionId: null,
      submitPreview: mockSubmitPreview,
      submitGenerate: mockSubmitGenerate,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(mockSubmitPreview).toHaveBeenCalledOnce();
    expect(mockSubmitGenerate).not.toHaveBeenCalled();
    expect(result).toBeNull();
  });

  // Req 5.4: 生成失败时返回 null
  it('should return null when submitGenerate fails', async () => {
    const mockSubmitGenerate = vi.fn(async () => {
      useConverterStore.setState({ error: '生成失败' });
      return null;
    });

    useConverterStore.setState({
      sessionId: 'valid-session',
      submitGenerate: mockSubmitGenerate,
    });

    const result = await useConverterStore.getState().submitFullPipeline();

    expect(mockSubmitGenerate).toHaveBeenCalledOnce();
    expect(result).toBeNull();
  });
});
