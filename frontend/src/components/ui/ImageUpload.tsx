import { useState, useRef, useCallback } from "react";

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
    ? "border-blue-500 bg-blue-500/10"
    : "border-gray-300 dark:border-gray-600 border-dashed";

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
      className={`flex items-center justify-center rounded-md border-2 cursor-pointer transition-colors ${borderClass} min-h-[120px]`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        className="hidden"
      />
      {preview ? (
        <img
          src={preview}
          alt="preview"
          className="max-h-[160px] max-w-full rounded object-contain p-2"
        />
      ) : (
        <span className="text-sm text-gray-500 dark:text-gray-400 select-none">
          拖拽图片或点击上传
        </span>
      )}
    </div>
  );
}
