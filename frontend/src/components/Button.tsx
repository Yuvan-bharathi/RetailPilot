import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

export type ButtonVariant = "primary" | "secondary" | "tertiary" | "destructive";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-brand text-surface hover:bg-brand-hover border border-transparent",
  secondary: "bg-surface text-ink border border-border hover:bg-elevated",
  tertiary: "bg-transparent text-brand border border-transparent hover:bg-brand-soft",
  // design doc §8: brand and danger are close in hue — destructive is outlined with danger text
  destructive: "bg-surface text-danger border border-danger hover:bg-danger-bg",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
  icon?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

export function Button({
  variant = "primary",
  size = "md",
  icon,
  className = "",
  children,
  type,
  ref,
  ...rest
}: ButtonProps) {
  const height = size === "md" ? "h-10 px-4" : "h-8 px-3 text-[13px]";
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={`inline-flex items-center justify-center gap-2 rounded-button font-medium transition-colors disabled:cursor-not-allowed disabled:border-border disabled:bg-neutral-bg disabled:text-ink-disabled ${height} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {icon ? <span aria-hidden="true" className="inline-flex">{icon}</span> : null}
      {children}
    </button>
  );
}
