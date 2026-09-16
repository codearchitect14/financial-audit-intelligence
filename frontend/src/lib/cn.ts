import clsx, { type ClassValue } from "clsx";

/** Conditional class names. */
export function cn(...values: ClassValue[]): string {
  return clsx(values);
}
