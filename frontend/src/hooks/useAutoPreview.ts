import { useEffect, useRef } from "react";
import { useConverterStore } from "../stores/converterStore";

/**
 * Auto-trigger preview when preconditions are met.
 * 当图片已上传、LUT 已选择、裁剪模态框已关闭时，自动触发预览（300ms 防抖）。
 *
 * Uses useRef to track the last triggered combination of imageFile + lut_name,
 * preventing duplicate triggers for the same pair.
 * 使用 useRef 追踪上次触发的 imageFile 和 lut_name 组合，避免重复触发。
 */
export function useAutoPreview(): void {
  const imageFile = useConverterStore((s) => s.imageFile);
  const lut_name = useConverterStore((s) => s.lut_name);
  const cropModalOpen = useConverterStore((s) => s.cropModalOpen);
  const hue_enable = useConverterStore((s) => s.hue_enable);
  const chroma_gate = useConverterStore((s) => s.chroma_gate);
  const submitPreview = useConverterStore((s) => s.submitPreview);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTriggeredRef = useRef<{
    imageFile: File | null;
    lut_name: string;
    hue_enable: boolean;
    chroma_gate: number;
  }>({
    imageFile: null,
    lut_name: "",
    hue_enable: false,
    chroma_gate: 15,
  });

  useEffect(() => {
    // Clear any pending timer on every dependency change
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    // Check preconditions
    if (!imageFile || !lut_name || cropModalOpen) {
      return;
    }

    // Skip if same combination was already triggered
    const last = lastTriggeredRef.current;
    if (
      last.imageFile === imageFile &&
      last.lut_name === lut_name &&
      last.hue_enable === hue_enable &&
      last.chroma_gate === chroma_gate
    ) {
      return;
    }

    // Debounce 300ms then trigger preview
    timerRef.current = setTimeout(() => {
      lastTriggeredRef.current = { imageFile, lut_name, hue_enable, chroma_gate };
      submitPreview();
    }, 300);

    // Cleanup on unmount
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [imageFile, lut_name, cropModalOpen, hue_enable, chroma_gate, submitPreview]);
}
