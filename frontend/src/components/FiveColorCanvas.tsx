/**
 * FiveColorCanvas - 五色配方 3D 薄片叠加动画。
 * 用 Canvas 2D 绘制 5 层半透明薄片，选满后播放叠加动画，融合成结果颜色。
 */

import { useRef, useEffect, useCallback, useState } from "react";

interface SliceColor {
  hex: string;
  name: string;
}

interface FiveColorCanvasProps {
  /** 已选颜色（0~5 个） */
  slices: SliceColor[];
  /** 查询结果颜色 hex */
  resultHex: string | null;
  /** 是否正在查询 */
  isLoading: boolean;
}

// ===== 常量 =====
const SLICE_W = 160;
const SLICE_H = 24;
const SLICE_SKEW = 20; // 3D 倾斜偏移
const SLICE_GAP = 6;
const CORNER_R = 6;
const LABEL_FONT = "12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const LABEL_FONT_BOLD = "bold 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

/** 绘制一个带圆角的平行四边形薄片 */
function drawSlice(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  skew: number,
  r: number,
  color: string,
  alpha: number,
  shadow: boolean,
) {
  ctx.save();
  ctx.globalAlpha = alpha;
  if (shadow) {
    ctx.shadowColor = "rgba(0,0,0,0.22)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetX = 1;
    ctx.shadowOffsetY = 2;
  }

  // 平行四边形四个角
  const tl = { x: x + skew, y };
  const tr = { x: x + w + skew, y };
  const br = { x: x + w, y: y + h };
  const bl = { x: x, y: y + h };

  ctx.beginPath();
  ctx.moveTo(tl.x + r, tl.y);
  ctx.lineTo(tr.x - r, tr.y);
  ctx.quadraticCurveTo(tr.x, tr.y, tr.x, tr.y + r);
  ctx.lineTo(br.x, br.y - r);
  ctx.quadraticCurveTo(br.x, br.y, br.x - r, br.y);
  ctx.lineTo(bl.x + r, bl.y);
  ctx.quadraticCurveTo(bl.x, bl.y, bl.x, bl.y - r);
  ctx.lineTo(tl.x, tl.y + r);
  ctx.quadraticCurveTo(tl.x, tl.y, tl.x + r, tl.y);
  ctx.closePath();

  ctx.fillStyle = color;
  ctx.fill();

  // 顶部高光
  const grad = ctx.createLinearGradient(tl.x, tl.y, bl.x, bl.y);
  grad.addColorStop(0, "rgba(255,255,255,0.35)");
  grad.addColorStop(0.5, "rgba(255,255,255,0)");
  grad.addColorStop(1, "rgba(0,0,0,0.1)");
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.restore();
}

/** 绘制结果圆形色块 */
function drawResultCircle(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  color: string,
  progress: number, // 0~1
) {
  ctx.save();
  const r = radius * progress;

  // 外发光
  ctx.shadowColor = color;
  ctx.shadowBlur = 10 * progress;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.globalAlpha = progress;
  ctx.fill();

  // 高光
  const grad = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.3, 0, cx, cy, r);
  grad.addColorStop(0, "rgba(255,255,255,0.4)");
  grad.addColorStop(0.6, "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.restore();
}

/** 绘制添加位置指示图标（简洁箭头） */
function drawAddIndicator(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  isDark: boolean,
  pulseProgress: number, // 0~1 脉动进度
) {
  ctx.save();
  
  // 图标颜色
  const iconColor = isDark ? "rgba(96, 165, 250, 0.95)" : "rgba(59, 130, 246, 0.95)";
  const glowColor = isDark ? "rgba(96, 165, 250, 0.6)" : "rgba(59, 130, 246, 0.5)";
  
  // 脉动效果：左右移动 + 透明度
  const moveOffset = Math.sin(pulseProgress * Math.PI * 2) * 3;
  const alpha = 0.7 + Math.sin(pulseProgress * Math.PI * 2) * 0.3;
  const glowIntensity = 8 + Math.sin(pulseProgress * Math.PI * 2) * 4;
  
  ctx.translate(x + moveOffset, y);
  ctx.globalAlpha = alpha;
  
  // 发光效果
  ctx.shadowColor = glowColor;
  ctx.shadowBlur = glowIntensity;
  
  // 绘制三角形箭头（指向右边）
  ctx.fillStyle = iconColor;
  ctx.beginPath();
  ctx.moveTo(-8, -6);  // 左上
  ctx.lineTo(4, 0);    // 右中
  ctx.lineTo(-8, 6);   // 左下
  ctx.closePath();
  ctx.fill();
  
  // 绘制箭头尾部（两条短线）
  ctx.shadowBlur = glowIntensity * 0.5;
  ctx.strokeStyle = iconColor;
  ctx.lineWidth = 2.5;
  ctx.lineCap = "round";
  
  ctx.beginPath();
  ctx.moveTo(-8, -6);
  ctx.lineTo(-12, -6);
  ctx.stroke();
  
  ctx.beginPath();
  ctx.moveTo(-8, 6);
  ctx.lineTo(-12, 6);
  ctx.stroke();
  
  ctx.restore();
}

/** 绘制面标签（观赏面/底面） */
function drawFaceLabel(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  isDark: boolean,
  isBold: boolean = false,
) {
  ctx.save();
  
  const textColor = isDark ? "rgba(255, 255, 255, 0.85)" : "rgba(0, 0, 0, 0.75)";
  const bgColor = isDark ? "rgba(30, 41, 59, 0.8)" : "rgba(255, 255, 255, 0.8)";
  const borderColor = isDark ? "rgba(71, 85, 105, 0.6)" : "rgba(203, 213, 225, 0.6)";
  
  ctx.font = isBold ? LABEL_FONT_BOLD : LABEL_FONT;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  
  // 测量文字宽度
  const metrics = ctx.measureText(text);
  const textWidth = metrics.width;
  const padding = 8;
  const height = 24;
  
  // 绘制背景圆角矩形
  const rectX = x - textWidth / 2 - padding;
  const rectY = y - height / 2;
  const rectW = textWidth + padding * 2;
  const rectH = height;
  const radius = 12;
  
  ctx.beginPath();
  ctx.moveTo(rectX + radius, rectY);
  ctx.lineTo(rectX + rectW - radius, rectY);
  ctx.quadraticCurveTo(rectX + rectW, rectY, rectX + rectW, rectY + radius);
  ctx.lineTo(rectX + rectW, rectY + rectH - radius);
  ctx.quadraticCurveTo(rectX + rectW, rectY + rectH, rectX + rectW - radius, rectY + rectH);
  ctx.lineTo(rectX + radius, rectY + rectH);
  ctx.quadraticCurveTo(rectX, rectY + rectH, rectX, rectY + rectH - radius);
  ctx.lineTo(rectX, rectY + radius);
  ctx.quadraticCurveTo(rectX, rectY, rectX + radius, rectY);
  ctx.closePath();
  
  ctx.fillStyle = bgColor;
  ctx.fill();
  
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = 1;
  ctx.stroke();
  
  // 绘制文字
  ctx.fillStyle = textColor;
  ctx.fillText(text, x, y);
  
  ctx.restore();
}

export default function FiveColorCanvas({ slices, resultHex, isLoading }: FiveColorCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const phaseRef = useRef<"idle" | "stacking" | "merging" | "done">("idle");
  const progressRef = useRef(0);
  const prevSliceCountRef = useRef(0);
  const sizeRef = useRef({ width: 0, height: 0, dpr: 1 });
  const [animationEpoch, setAnimationEpoch] = useState(0);

  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return false;

    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(canvas.clientWidth));
    const height = Math.max(1, Math.round(canvas.clientHeight));
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);

    if (
      canvas.width === pixelWidth &&
      canvas.height === pixelHeight &&
      sizeRef.current.width === width &&
      sizeRef.current.height === height &&
      sizeRef.current.dpr === dpr
    ) {
      return false;
    }

    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
    sizeRef.current = { width, height, dpr };
    return true;
  }, []);

  const draw = useCallback((timestamp: number = Date.now()) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    if (sizeRef.current.width === 0 || sizeRef.current.height === 0) {
      resizeCanvas();
    }

    const { width: w, height: h, dpr } = sizeRef.current;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.clearRect(0, 0, w, h);

    const isDark = document.documentElement.classList.contains("dark");
    const textColor = isDark ? "#fff" : "#1f2937";
    const mutedTextColor = isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.25)";
    const emptySliceColor = isDark ? "#374151" : "#d1d5db";
    const loadingTextColor = isDark ? "rgba(255,255,255,0.6)" : "rgba(0,0,0,0.5)";

    const centerX = w / 2 - SLICE_W / 2 - SLICE_SKEW / 2;
    const totalStackH = 5 * SLICE_H + 4 * SLICE_GAP;
    const startY = h / 2 - totalStackH / 2;

    const phase = phaseRef.current;
    const progress = progressRef.current;

    if (slices.length === 0 && !resultHex) {
      // 空状态：绘制 5 个灰色占位薄片
      for (let i = 0; i < 5; i++) {
        const y = startY + i * (SLICE_H + SLICE_GAP);
        drawSlice(ctx, centerX, y, SLICE_W, SLICE_H, SLICE_SKEW, CORNER_R, emptySliceColor, 0.4, false);
        // 序号
        ctx.fillStyle = mutedTextColor;
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(String(i + 1), centerX + SLICE_W / 2 + SLICE_SKEW / 2, y + SLICE_H / 2 + 4);
      }
      
      // 绘制观赏面和底面标签
      drawFaceLabel(ctx, "观赏面 Viewing Face", w / 2, startY - 35, isDark, true);
      drawFaceLabel(ctx, "底面 Bottom", w / 2, startY + totalStackH + 35, isDark, false);
      
      // 绘制添加位置指示（第一个位置）
      const pulseProgress = (timestamp % 2000) / 2000; // 2秒一个周期
      drawAddIndicator(ctx, centerX - 30, startY + SLICE_H / 2, isDark, pulseProgress);
      
      return;
    }

    if (phase === "merging" || phase === "done") {
      // 合并动画：薄片向中心收缩
      const mergeY = startY + 2 * (SLICE_H + SLICE_GAP); // 中间位置
      for (let i = 0; i < slices.length; i++) {
        const originalY = startY + i * (SLICE_H + SLICE_GAP);
        const currentY = originalY + (mergeY - originalY) * Math.min(progress * 2, 1);
        const alpha = Math.max(1 - progress * 1.5, 0);
        drawSlice(ctx, centerX, currentY, SLICE_W, SLICE_H, SLICE_SKEW, CORNER_R, slices[i].hex, alpha, true);
      }

      // 结果圆形
      if (resultHex && progress > 0.3) {
        const circleProgress = Math.min((progress - 0.3) / 0.7, 1);
        const eased = 1 - Math.pow(1 - circleProgress, 3); // easeOutCubic
        drawResultCircle(
          ctx,
          w / 2,
          startY + totalStackH / 2,
          50,
          resultHex,
          eased,
        );

        // 结果文字
        if (circleProgress > 0.5) {
          const textAlpha = Math.min((circleProgress - 0.5) / 0.5, 1);
          ctx.save();
          ctx.globalAlpha = textAlpha;
          ctx.fillStyle = textColor;
          ctx.font = "bold 14px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(resultHex, w / 2, startY + totalStackH / 2 + 70);
          ctx.restore();
        }
      }
      
      // 绘制观赏面和底面标签（合并时也显示）
      if (progress < 0.5) {
        const labelAlpha = 1 - progress * 2;
        ctx.save();
        ctx.globalAlpha = labelAlpha;
        drawFaceLabel(ctx, "观赏面 Viewing Face", w / 2, startY - 35, isDark, true);
        drawFaceLabel(ctx, "底面 Bottom", w / 2, startY + totalStackH + 35, isDark, false);
        ctx.restore();
      }
    } else {
      // 正常堆叠状态
      for (let i = 0; i < 5; i++) {
        const y = startY + i * (SLICE_H + SLICE_GAP);
        if (i < slices.length) {
          // 入场动画
          const isNew = i === slices.length - 1 && phase === "stacking";
          const entryProgress = isNew ? Math.min(progress / 0.3, 1) : 1;
          const eased = 1 - Math.pow(1 - entryProgress, 3);
          const offsetX = (1 - eased) * 80;
          const alpha = eased;
          drawSlice(ctx, centerX + offsetX, y, SLICE_W, SLICE_H, SLICE_SKEW, CORNER_R, slices[i].hex, alpha, true);
          // 颜色名
          ctx.save();
          ctx.globalAlpha = alpha;
          ctx.fillStyle = textColor;
          ctx.font = "11px sans-serif";
          ctx.textAlign = "left";
          ctx.fillText(slices[i].name, centerX + SLICE_W + SLICE_SKEW + 12, y + SLICE_H / 2 + 4);
          ctx.restore();
        } else {
          // 空位
          drawSlice(ctx, centerX, y, SLICE_W, SLICE_H, SLICE_SKEW, CORNER_R, emptySliceColor, 0.25, false);
          ctx.fillStyle = mutedTextColor;
          ctx.font = "12px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(String(i + 1), centerX + SLICE_W / 2 + SLICE_SKEW / 2, y + SLICE_H / 2 + 4);
        }
      }
      
      // 绘制观赏面和底面标签
      drawFaceLabel(ctx, "观赏面 Viewing Face", w / 2, startY - 35, isDark, true);
      drawFaceLabel(ctx, "底面 Bottom", w / 2, startY + totalStackH + 35, isDark, false);
      
      // 绘制添加位置指示（下一个要添加的位置）
      if (slices.length < 5) {
        const nextY = startY + slices.length * (SLICE_H + SLICE_GAP);
        const pulseProgress = (timestamp % 2000) / 2000; // 2秒一个周期
        drawAddIndicator(ctx, centerX - 30, nextY + SLICE_H / 2, isDark, pulseProgress);
      }
    }

    // Loading 指示
    if (isLoading) {
      ctx.save();
      ctx.fillStyle = loadingTextColor;
      ctx.font = "13px sans-serif";
      ctx.textAlign = "center";
      const dots = ".".repeat(Math.floor((timestamp / 400) % 4));
      ctx.fillText(`查询中${dots}`, w / 2, h - 30);
      ctx.restore();
    }
  }, [isLoading, resizeCanvas, resultHex, slices]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const syncSize = () => {
      const resized = resizeCanvas();
      if (resized) {
        draw();
      }
    };

    syncSize();
    const observer = new ResizeObserver(syncSize);
    observer.observe(canvas);
    window.addEventListener("resize", syncSize);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncSize);
    };
  }, [draw, resizeCanvas]);

  useEffect(() => {
    const shouldAnimate =
      phaseRef.current === "stacking" ||
      phaseRef.current === "merging" ||
      isLoading;

    if (!shouldAnimate) {
      draw();
      return;
    }

    let frame = 0;
    const loop = (timestamp: number) => {
      const phase = phaseRef.current;

      if (phase === "stacking") {
        progressRef.current = Math.min(progressRef.current + 0.04, 1);
        if (progressRef.current >= 1) phaseRef.current = "idle";
      } else if (phase === "merging") {
        progressRef.current = Math.min(progressRef.current + 0.015, 1);
        if (progressRef.current >= 1) phaseRef.current = "done";
      }

      draw(timestamp);

      if (
        phaseRef.current === "stacking" ||
        phaseRef.current === "merging" ||
        isLoading
      ) {
        frame = requestAnimationFrame(loop);
        animRef.current = frame;
      }
    };

    frame = requestAnimationFrame(loop);
    animRef.current = frame;
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [animationEpoch, draw, isLoading]);

  useEffect(() => {
    if (isLoading) {
      setAnimationEpoch((value) => value + 1);
      return;
    }
    draw();
  }, [draw, isLoading]);

  // 新增颜色时触发入场动画
  useEffect(() => {
    if (slices.length > prevSliceCountRef.current && slices.length <= 5) {
      phaseRef.current = "stacking";
      progressRef.current = 0;
      setAnimationEpoch((value) => value + 1);
    }
    prevSliceCountRef.current = slices.length;
  }, [slices.length]);

  // 有结果时触发合并动画
  useEffect(() => {
    if (resultHex && slices.length === 5) {
      phaseRef.current = "merging";
      progressRef.current = 0;
      setAnimationEpoch((value) => value + 1);
    }
    // 结果被清除（如反序操作），重置回正常堆叠
    if (!resultHex && slices.length === 5 && (phaseRef.current === "merging" || phaseRef.current === "done")) {
      phaseRef.current = "idle";
      progressRef.current = 0;
      draw();
    }
  }, [draw, resultHex, slices.length]);

  // 清除时重置
  useEffect(() => {
    if (slices.length === 0) {
      phaseRef.current = "idle";
      progressRef.current = 0;
      draw();
    }
  }, [draw, slices.length]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ display: "block" }}
    />
  );
}
