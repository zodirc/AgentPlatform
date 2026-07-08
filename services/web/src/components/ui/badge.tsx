import { cn } from "../../lib/utils";

type Props = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "warning";
};

export function Badge({ className, variant = "default", ...props }: Props) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
        variant === "default" && "bg-slate-800 text-slate-300",
        variant === "success" && "bg-emerald-900/50 text-emerald-300",
        variant === "warning" && "bg-amber-900/50 text-amber-300",
        className,
      )}
      {...props}
    />
  );
}
