import { useState, useRef, useCallback } from "react";
import { useI18n } from "../../i18n/context";

interface ImageUploadProps {
  onFileSelect: (file: File) => void;
  accept: string;
  preview?: string;
}

export default function ImageUpload({
  onFileSelect,
  accept,
  preview,
}: ImageUploadProps) {
  const { t } = useI18n();
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    },
    [],
  );

  const handleDragLeave = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
    },
    [],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) {
        onFileSelect(file);
      }
    },
    [onFileSelect],
  );

  const handleClick = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        onFileSelect(file);
      }
    },
    [onFileSelect],
  );

  const borderClass = isDragging
    ? "border-blue-400 bg-blue-500/10 shadow-[0_0_0_6px_var(--focus-ring)]"
    : "border-slate-300/80 dark:border-slate-700/80 border-dashed bg-white/40 dark:bg-slate-900/35";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") handleClick();
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`flex min-h-[140px] items-center justify-center rounded-[24px] border-2 px-4 py-5 text-center shadow-[var(--shadow-control)] transition-all ${borderClass} cursor-pointer`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        className="hidden"
      />
      {preview ? (
        <div
          data-testid="checkerboard-bg"
          className="rounded-[20px] border border-white/70 bg-white/80 p-3 shadow-[var(--shadow-control)] dark:border-slate-700/70 dark:bg-slate-950/70"
          style={{
            backgroundImage:
              "linear-gradient(45deg, #e0e0e0 25%, transparent 25%), " +
              "linear-gradient(-45deg, #e0e0e0 25%, transparent 25%), " +
              "linear-gradient(45deg, transparent 75%, #e0e0e0 75%), " +
              "linear-gradient(-45deg, transparent 75%, #e0e0e0 75%)",
            backgroundSize: "16px 16px",
            backgroundPosition: "0 0, 0 8px, 8px -8px, -8px 0px",
          }}
        >
          <img
            src={preview}
            alt="preview"
            className="max-h-[180px] max-w-full rounded-2xl object-contain"
          />
        </div>
      ) : (
        <span className="select-none text-sm font-medium text-slate-500 dark:text-slate-400">
          {t("upload_drag_hint")}
        </span>
      )}
    </div>
  );
}
