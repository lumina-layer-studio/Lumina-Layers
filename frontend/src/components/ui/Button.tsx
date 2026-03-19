import { motion } from "framer-motion";

interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary";
}

export default function Button({
  label,
  onClick,
  disabled = false,
  loading = false,
  variant = "primary",
}: ButtonProps) {
  const isDisabled = disabled || loading;

  const variantClasses =
    variant === "primary"
      ? "bg-blue-600 hover:bg-blue-700 text-white"
      : "bg-gray-200 dark:bg-gray-600 hover:bg-gray-300 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200";

  return (
    <motion.button
      whileHover={isDisabled ? {} : { scale: 1.02 }}
      whileTap={isDisabled ? {} : { scale: 0.95 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      className={`relative flex flex-shrink-0 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${variantClasses} disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-none`}
    >
      {loading && (
        <div className="relative flex h-4 w-4 items-center justify-center">
          <div className="absolute inset-[-4px] rounded-full bg-current opacity-20 blur-sm animate-glow-pulse" />
          <div className="absolute inset-0 rounded-full border border-current opacity-30" />
          <div className="absolute inset-0 rounded-full border-t-[1.5px] border-r-[1.5px] border-current opacity-90 animate-glow-spin" />
        </div>
      )}
      {label}
    </motion.button>
  );
}
