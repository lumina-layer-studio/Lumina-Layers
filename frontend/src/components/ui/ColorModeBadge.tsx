interface ColorModeBadgeProps {
  mode: string;
}

// Filament dot colors per mode  (hex strings for inline style)
const DOTS_RYBW    = ["#DC143C", "#FFE600", "#0064F0", "#F0F0F0"];
const DOTS_CMYW    = ["#00FFFF", "#FF00FF", "#FFFF00", "#F0F0F0"];
const DOTS_RYBWGK  = ["#00AE42", "#111111", "#DC143C", "#FFE600", "#0064F0", "#F0F0F0"];
const DOTS_CMYWGK  = ["#00AE42", "#111111", "#00FFFF", "#FF00FF", "#FFFF00", "#F0F0F0"];
const DOTS_8COLOR  = ["#C12E1F", "#FFFF00", "#0064F0", "#FF00FF", "#00FFFF", "#F0F0F0", "#00AE42", "#111111"];
const DOTS_BW      = ["#F0F0F0", "#111111"];
const DOTS_5COLOR  = ["#DC143C", "#FFE600", "#0064F0", "#F0F0F0", "#111111"];

interface BadgeInfo {
  dots: string[] | "rainbow";
  label: string;
}

function resolveBadge(mode: string): BadgeInfo {
  if (mode === "Merged") return { dots: "rainbow", label: "Merged" };
  if (mode.startsWith("8-Color"))          return { dots: DOTS_8COLOR, label: "8-Color" };
  if (mode.includes("CMYWGK"))             return { dots: DOTS_CMYWGK, label: "6-Color" };
  if (mode.includes("RYBWGK"))             return { dots: DOTS_RYBWGK, label: "6-Color" };
  if (mode.startsWith("6-Color"))          return { dots: DOTS_RYBWGK, label: "6-Color" };
  if (mode.includes("5-Color Extended"))   return { dots: DOTS_5COLOR,  label: "5-Color" };
  if (mode.startsWith("BW"))               return { dots: DOTS_BW,      label: "BW" };
  if (mode.includes("CMYW"))               return { dots: DOTS_CMYW,    label: "4-Color" };
  if (mode.includes("RYBW"))               return { dots: DOTS_RYBW,    label: "4-Color" };
  return { dots: DOTS_RYBW, label: "4-Color" };
}

function Dot({ color }: { color: string }) {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
      style={{
        backgroundColor: color,
        boxShadow: "inset 0 0 0 1px rgba(128,128,128,0.35)",
      }}
    />
  );
}

function RainbowDot() {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
      style={{
        background: "conic-gradient(#E53935, #FDD835, #43A047, #1E88E5, #9C27B0, #E91E63, #E53935)",
        boxShadow: "inset 0 0 0 1px rgba(128,128,128,0.35)",
      }}
    />
  );
}

export default function ColorModeBadge({ mode }: ColorModeBadgeProps) {
  const { dots, label } = resolveBadge(mode);
  return (
    <span
      title={mode}
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium border bg-gray-700/40 border-gray-600/40 text-gray-300"
    >
      <span className="flex items-center gap-0.5">
        {dots === "rainbow" ? (
          <RainbowDot />
        ) : (
          dots.map((c, i) => <Dot key={i} color={c} />)
        )}
      </span>
      <span>{label}</span>
    </span>
  );
}
