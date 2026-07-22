import { cn } from "../../lib/utils";

type Props = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "success" | "warning";
};

export function Badge({ className, variant = "default", ...props }: Props) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
        variant === "default" && "bg-muted text-foreground/90",
        variant === "success" && "bg-success-muted text-success",
        variant === "warning" && "bg-warning-muted text-warning",
        className,
      )}
      {...props}
    />
  );
}
