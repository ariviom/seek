import { cn } from "@/lib/utils";

// Avatars are never fetched images: initials on a tint derived from the name, so the same Channel always
// looks the same without a network round trip.
const tints = [
  "bg-rose-200 text-rose-900 dark:bg-rose-900 dark:text-rose-100",
  "bg-amber-200 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
  "bg-lime-200 text-lime-900 dark:bg-lime-900 dark:text-lime-100",
  "bg-emerald-200 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100",
  "bg-teal-200 text-teal-900 dark:bg-teal-900 dark:text-teal-100",
  "bg-sky-200 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
  "bg-indigo-200 text-indigo-900 dark:bg-indigo-900 dark:text-indigo-100",
  "bg-violet-200 text-violet-900 dark:bg-violet-900 dark:text-violet-100",
] as const;

type AvatarSize = "xs" | "sm" | "md" | "lg";

const sizes: Record<AvatarSize, string> = {
  xs: "size-5 text-[9px]",
  sm: "size-6 text-[10px]",
  md: "size-8 text-xs",
  lg: "size-11 text-sm",
};

function tintOf(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return tints[Math.abs(hash) % tints.length] ?? tints[0];
}

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0];
  const last = words[words.length - 1];
  if (first === undefined || last === undefined) return "?";
  if (words.length === 1) return first.slice(0, 2).toUpperCase();
  return (first.slice(0, 1) + last.slice(0, 1)).toUpperCase();
}

export function Avatar({
  name,
  shape = "round",
  size = "md",
  className,
}: {
  name: string;
  shape?: "round" | "square";
  size?: AvatarSize;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium select-none",
        shape === "round" ? "rounded-full" : "rounded-md",
        sizes[size],
        tintOf(name),
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}

export function AvatarStack({
  names,
  shape = "round",
  size = "sm",
  className,
}: {
  names: string[];
  shape?: "round" | "square";
  size?: AvatarSize;
  className?: string;
}) {
  const shown = names.slice(0, 3);
  if (shown.length === 0) {
    return (
      <span
        aria-hidden
        className={cn(
          "inline-block shrink-0 bg-muted",
          shape === "round" ? "rounded-full" : "rounded-md",
          sizes[size],
          className,
        )}
      />
    );
  }
  return (
    <span className={cn("inline-flex shrink-0 items-center", className)}>
      {shown.map((name, index) => (
        <Avatar
          key={`${name}-${index}`}
          name={name}
          shape={shape}
          size={size}
          className={cn("ring-2 ring-sidebar", index > 0 && "-ml-2")}
        />
      ))}
    </span>
  );
}
